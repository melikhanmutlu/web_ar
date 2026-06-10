"""3D model conversion pipeline.

Everything is normalised to GLB because <model-viewer> consumes GLB on the
web and Android (Scene Viewer). iOS Quick Look needs USDZ, which we export
best-effort with Blender (present in the Nixpacks build).

Format strategy:
    glb   -> copied as-is
    gltf  -> repacked to binary GLB with trimesh
    stl   -> trimesh (geometry only, a neutral material is applied)
    obj   -> obj2gltf (Node, keeps .mtl materials) with trimesh fallback
    fbx   -> FBX2glTF native binary (tools/FBX2glTF)
"""

import logging
import shutil
import subprocess
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger(__name__)

CONVERT_TIMEOUT = 300  # seconds per external tool call


class ConversionError(Exception):
    """Raised when a model cannot be converted to GLB."""


def convert_to_glb(source: Path, output: Path, tools_dir: Path) -> None:
    """Convert `source` (extension decides the strategy) into GLB `output`."""
    source, output = Path(source), Path(output)
    ext = source.suffix.lower().lstrip(".")
    output.parent.mkdir(parents=True, exist_ok=True)

    if ext == "glb":
        shutil.copyfile(source, output)
    elif ext == "gltf":
        _convert_with_trimesh(source, output)
    elif ext == "stl":
        _convert_stl(source, output)
    elif ext == "obj":
        _convert_obj(source, output)
    elif ext == "fbx":
        _convert_fbx(source, output, tools_dir)
    else:
        raise ConversionError(f"Unsupported format: .{ext}")

    if not output.exists() or output.stat().st_size == 0:
        raise ConversionError("Conversion produced no output")


def inspect_glb(path: Path) -> dict:
    """Return vertex/face counts and bounding box dimensions of a GLB."""
    try:
        scene = trimesh.load(str(path), force="scene")
        extents = scene.extents if scene.extents is not None else [0, 0, 0]
        vertices = faces = 0
        for geom in scene.geometry.values():
            vertices += int(getattr(geom, "vertices", np.empty((0, 3))).shape[0])
            faces += int(getattr(geom, "faces", np.empty((0, 3))).shape[0])
        return {
            "vertices": vertices,
            "faces": faces,
            "dimensions": {
                "x": round(float(extents[0]), 4),
                "y": round(float(extents[1]), 4),
                "z": round(float(extents[2]), 4),
            },
        }
    except Exception as e:  # stats are nice-to-have, never fatal
        logger.warning(f"inspect_glb failed for {path}: {e}")
        return {"vertices": None, "faces": None, "dimensions": None}


def export_usdz(glb_path: Path, usdz_path: Path, tools_dir: Path) -> bool:
    """Export USDZ for iOS Quick Look via Blender. Returns False on any
    failure — USDZ is an enhancement, not a requirement."""
    blender = shutil.which("blender")
    script = Path(tools_dir) / "usdz_export.py"
    if not blender or not script.exists():
        return False
    try:
        result = subprocess.run(
            [blender, "--background", "--factory-startup", "--python", str(script),
             "--", str(glb_path), str(usdz_path)],
            capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
        )
        ok = result.returncode == 0 and usdz_path.exists() and usdz_path.stat().st_size > 0
        if not ok:
            logger.warning(f"USDZ export failed: {result.stderr[-500:] if result.stderr else result.returncode}")
        return ok
    except Exception as e:
        logger.warning(f"USDZ export error: {e}")
        return False


# --- per-format converters -------------------------------------------------

def _convert_with_trimesh(source: Path, output: Path) -> None:
    try:
        scene = trimesh.load(str(source), force="scene")
        if not scene.geometry:
            raise ConversionError("Model contains no geometry")
        output.write_bytes(scene.export(file_type="glb"))
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"trimesh conversion failed: {e}") from e


def _convert_stl(source: Path, output: Path) -> None:
    try:
        mesh = trimesh.load(str(source), force="mesh")
        if mesh.is_empty:
            raise ConversionError("STL contains no geometry")
        # STL has no material/colour information — give it a neutral PBR
        # material so it doesn't render pitch black in viewers.
        mesh.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=[0.62, 0.66, 0.71, 1.0],
                metallicFactor=0.1,
                roughnessFactor=0.7,
            )
        )
        scene = trimesh.Scene(mesh)
        output.write_bytes(scene.export(file_type="glb"))
    except ConversionError:
        raise
    except Exception as e:
        raise ConversionError(f"STL conversion failed: {e}") from e


def _convert_obj(source: Path, output: Path) -> None:
    # obj2gltf preserves .mtl materials and textures, so prefer it when the
    # node_modules install is available; otherwise trimesh still produces
    # valid geometry.
    obj2gltf = _find_node_bin("obj2gltf")
    if obj2gltf:
        try:
            result = subprocess.run(
                [*obj2gltf, "--binary", "--input", str(source), "--output", str(output)],
                capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
            )
            if result.returncode == 0 and output.exists() and output.stat().st_size > 0:
                return
            logger.warning(f"obj2gltf failed, falling back to trimesh: {result.stderr[-300:]}")
        except Exception as e:
            logger.warning(f"obj2gltf error, falling back to trimesh: {e}")
    _convert_with_trimesh(source, output)


def _convert_fbx(source: Path, output: Path, tools_dir: Path) -> None:
    binary = Path(tools_dir) / "FBX2glTF"
    if not binary.exists():
        binary_which = shutil.which("FBX2glTF")
        if not binary_which:
            raise ConversionError("FBX2glTF binary not found")
        binary = Path(binary_which)
    try:
        result = subprocess.run(
            [str(binary), "--binary", "--pbr-metallic-roughness",
             "--input", str(source), "--output", str(output.with_suffix(""))],
            capture_output=True, text=True, timeout=CONVERT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise ConversionError("FBX conversion timed out") from e
    except OSError as e:
        raise ConversionError(f"FBX2glTF could not run: {e}") from e

    # FBX2glTF appends .glb to the output base name itself.
    produced = output.with_suffix("").with_suffix(".glb")
    if result.returncode != 0 or not produced.exists():
        raise ConversionError(f"FBX2glTF failed: {(result.stderr or result.stdout)[-300:]}")
    if produced != output:
        shutil.move(str(produced), str(output))


def _find_node_bin(name: str) -> list[str] | None:
    """Locate a Node CLI from the project's node_modules, or via npx."""
    base = Path(__file__).resolve().parent.parent
    local = base / "node_modules" / ".bin" / name
    if local.exists():
        return [str(local)]
    if shutil.which(name):
        return [name]
    if shutil.which("npx"):
        return ["npx", "--no-install", name]
    return None
