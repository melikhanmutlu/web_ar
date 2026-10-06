import os
import subprocess

from .glb_optimizer import _resolve_gltfpack, readable_glb
from .glb_quality import ensure_pbr_materials, validate_glb_quality


class LODGenerationError(RuntimeError):
    pass


def _triangle_count(path):
    """Triangle count from the glTF accessors (works on meshopt output too,
    where accessor counts still describe the decoded data)."""
    from pygltflib import GLTF2

    gltf = GLTF2().load(path)
    total = 0
    for mesh in gltf.meshes or []:
        for primitive in mesh.primitives or []:
            if primitive.mode not in (None, 4):  # TRIANGLES only
                continue
            accessor_index = primitive.indices
            if accessor_index is None:
                accessor_index = primitive.attributes.POSITION
            if accessor_index is not None:
                total += (gltf.accessors[accessor_index].count or 0) // 3
    return total


def _run_gltfpack(command, source, destination, ratio, meshopt, timeout, aggressive=False):
    args = command + [
        "-i", source, "-o", destination,
        "-si", str(ratio), "-kn", "-ke", "-km",
    ]
    if aggressive:
        args.append("-sa")
    if meshopt:
        args.append("-cc")
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def generate_lods(source_path, output_dir, ratios=(0.5, 0.25, 0.1), *, meshopt=True, timeout=600):
    command = _resolve_gltfpack()
    if not command:
        raise LODGenerationError("gltfpack is required for LOD generation")
    if not os.path.isfile(source_path):
        raise LODGenerationError("Source GLB is missing")
    os.makedirs(output_dir, exist_ok=True)
    source_size = os.path.getsize(source_path)
    outputs = []
    # gltfpack cannot decode Draco; hand it a decompressed copy if needed.
    with readable_glb(source_path) as readable_source:
        source_triangles = _triangle_count(readable_source)
        for level, ratio in enumerate(ratios, start=1):
            ratio = float(ratio)
            if not 0.01 <= ratio < 1:
                raise LODGenerationError("LOD ratios must be between 0.01 and 1")
            filename = f"model_lod{level}.glb"
            destination = os.path.join(output_dir, filename)
            result = _run_gltfpack(command, readable_source, destination, ratio, meshopt, timeout)
            # Unwelded sources (per-face normals/UVs, e.g. STL-derived meshes)
            # leave every vertex on a seam, which gltfpack's default
            # simplification refuses to collapse: the "LOD" comes back at
            # full triangle count. Retry aggressively when the target was missed.
            if (result.returncode == 0 and os.path.isfile(destination)
                    and source_triangles
                    and _triangle_count(destination) > source_triangles * ratio * 1.5):
                result = _run_gltfpack(command, readable_source, destination, ratio, meshopt,
                                       timeout, aggressive=True)
            if result.returncode != 0 or not os.path.isfile(destination):
                try:
                    os.remove(destination)
                except OSError:
                    pass
                raise LODGenerationError(f"LOD {level} generation failed: {(result.stderr or '')[:300]}")
            ensure_pbr_materials(destination)
            validate_glb_quality(destination)
            size = os.path.getsize(destination)
            if size >= source_size:
                os.remove(destination)
                continue
            outputs.append({
                "level": level, "ratio": ratio, "filename": filename,
                "path": destination, "file_size": size,
            })
    if not outputs:
        raise LODGenerationError("LOD generation produced no smaller assets")
    return outputs


def simplify_glb(source_path, destination_path, target_triangles, *, meshopt=True, timeout=600):
    """Simplify a GLB down to ~`target_triangles` with gltfpack (-si ratio, and
    -sa when the first pass misses the target, as generate_lods does).

    Writes `destination_path` only; the source is never touched. Returns
    {"ratio", "triangles_before", "triangles_after"}."""
    command = _resolve_gltfpack()
    if not command:
        raise LODGenerationError("gltfpack is required for simplification")
    if not os.path.isfile(source_path):
        raise LODGenerationError("Source GLB is missing")
    target_triangles = int(target_triangles)
    with readable_glb(source_path) as readable_source:
        before = _triangle_count(readable_source)
        if before <= target_triangles:
            raise LODGenerationError("The model is already within the triangle target")
        ratio = target_triangles / before
        if ratio < 0.01:
            raise LODGenerationError("The triangle target is too low for this model")
        result = _run_gltfpack(command, readable_source, destination_path, ratio, meshopt, timeout)
        if (result.returncode == 0 and os.path.isfile(destination_path)
                and _triangle_count(destination_path) > target_triangles * 1.5):
            result = _run_gltfpack(command, readable_source, destination_path, ratio, meshopt,
                                   timeout, aggressive=True)
        if result.returncode != 0 or not os.path.isfile(destination_path):
            try:
                os.remove(destination_path)
            except OSError:
                pass
            raise LODGenerationError(f"Simplification failed: {(result.stderr or '')[:300]}")
    ensure_pbr_materials(destination_path)
    validate_glb_quality(destination_path)
    return {"ratio": ratio, "triangles_before": before,
            "triangles_after": _triangle_count(destination_path)}
