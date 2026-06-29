"""Isolated, memory-capped FBX metadata probe.

pyassimp.load() can allocate gigabytes parsing pathological FBX files and
OOM-kill the entire gunicorn/worker process (observed: a 20s parse then
SIGKILL). The data it extracts is purely auxiliary — unit scale, embedded
textures, and vertices/faces for the zero-geometry rescue — none of it is
required for the actual FBX2glTF conversion.

So we run the probe in a separate child process with an RLIMIT_AS cap: a
runaway parse hits its own address-space limit (clean failure) instead of
the kernel OOM-killing the server, and the converter then proceeds with
FBX2glTF alone. Run as a module:

    python -m converters.fbx_probe <input.fbx> <work_dir> <out_manifest.json>
"""

import json
import os
import subprocess
import sys
import tempfile

# Default address-space cap for the child. Tunable via FBX_PROBE_MEM_MB.
# High enough for imports + a normal FBX parse, low enough to fail before a
# pathological file exhausts a typical container. Lower it on small dynos.
DEFAULT_MEM_MB = int(os.environ.get("FBX_PROBE_MEM_MB", "1536"))
DEFAULT_TIMEOUT = int(os.environ.get("FBX_PROBE_TIMEOUT", "90"))

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def probe_fbx(input_path, work_dir):
    """Extract FBX metadata via assimp. Returns a manifest dict:

        {unit_scale, material_textures, original_dimensions, vertices_npz}

    Embedded textures are written next to input_path (unchanged behaviour);
    vertices/faces (for the rescue path) go to an .npz in work_dir. Raises on
    an assimp import failure — the caller treats that as "probe unavailable".
    """
    import numpy as np

    # Reuse the converter's library-path + lifecycle helpers (lazy import to
    # avoid any import cycle; fbx_converter never imports this module at top).
    from .fbx_converter import _ensure_assimp_library_path, _pyassimp_scene
    from .base_converter import safe_texture_ext

    _ensure_assimp_library_path()
    import pyassimp
    from pyassimp import postprocess

    manifest = {
        "unit_scale": 0.01,
        "material_textures": {},
        "original_dimensions": None,
        "vertices_npz": None,
    }

    with _pyassimp_scene(
        pyassimp, input_path, processing=postprocess.aiProcess_Triangulate
    ) as scene:
        # --- FBX unit scale -> meters ---
        unit_scale = 1.0
        try:
            if getattr(scene, "metadata", None):
                for key in scene.metadata:
                    key_str = key.decode("utf-8", "ignore") if isinstance(key, bytes) else str(key)
                    if key_str.lower() in ("unitscalefactor", "unit_scale_factor"):
                        val = scene.metadata[key]
                        if hasattr(val, "data"):
                            val = val.data
                        unit_scale = float(val) / 100.0
                        break
            if unit_scale == 1.0:
                unit_scale = 0.01  # default FBX unit is cm
        except Exception:
            unit_scale = 0.01
        manifest["unit_scale"] = unit_scale

        # --- embedded textures (written next to the FBX) ---
        extracted = {}
        texture_dir = os.path.dirname(input_path)
        for idx, texture in enumerate(getattr(scene, "textures", None) or []):
            try:
                hint = getattr(texture, "achFormatHint", None)
                if isinstance(hint, bytes):
                    hint = hint.decode("utf-8", "ignore")
                ext = safe_texture_ext(hint) if hint else ".png"
                data = getattr(texture, "pcData", None)
                if data:
                    path = os.path.join(texture_dir, f"texture_{idx}{ext}")
                    with open(path, "wb") as fh:
                        fh.write(data)
                    extracted[idx] = path
            except Exception:
                pass

        # --- material -> texture mappings ---
        materials = getattr(scene, "materials", None) or []
        for mat_idx, material in enumerate(materials):
            mat_name = material.properties.get("?mat.name", f"Material_{mat_idx}")
            tex_file = material.properties.get("$tex.file")
            if not tex_file:
                for k in material.properties.keys():
                    if "$tex.file" in k:
                        tex_file = material.properties[k]
                        break
            if tex_file:
                manifest["material_textures"][mat_name] = tex_file
            elif len(extracted) == 1 and len(materials) == 1:
                manifest["material_textures"][mat_name] = list(extracted.values())[0]

        # --- vertices + faces (only for the zero-geometry rescue) ---
        all_vertices, all_faces = [], []
        for mesh in getattr(scene, "meshes", None) or []:
            if getattr(mesh, "vertices", None) is not None and len(mesh.vertices) > 0:
                all_vertices.append(np.array(mesh.vertices))
                faces = []
                for face in getattr(mesh, "faces", None) or []:
                    if len(face) >= 3:
                        faces.append([face[0], face[1], face[2]])
                all_faces.append(np.array(faces) if faces else None)

        if all_vertices:
            combined_v = np.vstack(all_vertices)
            extents = combined_v.max(axis=0) - combined_v.min(axis=0)

            combined_f = None
            if any(f is not None for f in all_faces):
                parts, offset = [], 0
                for i, faces in enumerate(all_faces):
                    if faces is not None:
                        parts.append(faces + offset)
                    offset += len(all_vertices[i])
                if parts:
                    combined_f = np.vstack(parts)

            npz_path = os.path.join(work_dir, "fbx_geometry.npz")
            if combined_f is not None:
                np.savez_compressed(npz_path, vertices=combined_v, faces=combined_f)
            else:
                np.savez_compressed(npz_path, vertices=combined_v)
            manifest["vertices_npz"] = npz_path

            if float(max(extents)) > 0.001:
                extents_m = extents * unit_scale
                manifest["original_dimensions"] = {
                    "x": float(extents_m[0]), "y": float(extents_m[1]),
                    "z": float(extents_m[2]), "max": float(max(extents_m)),
                    "unit_scale": unit_scale,
                }

    return manifest


def run_isolated(input_path, mem_mb=None, timeout=None):
    """Run probe_fbx() in a memory-capped child process.

    Returns a manifest dict with in-memory `vertices`/`faces` arrays (the npz
    is loaded then deleted), or {"error": ...} on any failure — the converter
    treats an error as "skip the probe, use FBX2glTF only".
    """
    import numpy as np

    timeout = timeout or DEFAULT_TIMEOUT
    work_dir = tempfile.mkdtemp(prefix="fbxprobe_")
    out_json = os.path.join(work_dir, "manifest.json")
    env = dict(os.environ)
    if mem_mb:
        env["FBX_PROBE_MEM_MB"] = str(mem_mb)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "converters.fbx_probe", input_path, work_dir, out_json],
            capture_output=True, text=True, timeout=timeout, cwd=_REPO_ROOT, env=env,
        )
        if not os.path.exists(out_json):
            tail = (proc.stderr or proc.stdout or "")[-300:]
            return {"error": f"probe exited {proc.returncode}: {tail}"}
        with open(out_json) as fh:
            manifest = json.load(fh)
        if manifest.get("error"):
            return manifest
        npz = manifest.pop("vertices_npz", None)
        if npz and os.path.exists(npz):
            with np.load(npz) as data:
                manifest["vertices"] = data["vertices"] if "vertices" in data else None
                manifest["faces"] = data["faces"] if "faces" in data else None
        return manifest
    except subprocess.TimeoutExpired:
        return {"error": f"probe timed out after {timeout}s"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"probe runner error: {e}"}
    finally:
        try:
            import shutil
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass


def _main():
    input_path, work_dir, out_json = sys.argv[1], sys.argv[2], sys.argv[3]
    mem_mb = int(os.environ.get("FBX_PROBE_MEM_MB", str(DEFAULT_MEM_MB)))
    try:
        import resource

        cap = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
    except Exception:
        pass  # RLIMIT_AS unsupported here; isolation alone still contains OOM
    try:
        manifest = probe_fbx(input_path, work_dir)
        with open(out_json, "w") as fh:
            json.dump(manifest, fh)
        sys.exit(0)
    except BaseException as e:  # includes MemoryError / assimp failures
        try:
            with open(out_json, "w") as fh:
                json.dump({"error": str(e)[:500]}, fh)
        except Exception:
            pass
        sys.exit(3)


if __name__ == "__main__":
    _main()
