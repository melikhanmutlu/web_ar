import os
import subprocess

from .glb_optimizer import _resolve_gltfpack
from .glb_quality import ensure_pbr_materials, validate_glb_quality


class LODGenerationError(RuntimeError):
    pass


def generate_lods(source_path, output_dir, ratios=(0.5, 0.25, 0.1), *, meshopt=True, timeout=600):
    command = _resolve_gltfpack()
    if not command:
        raise LODGenerationError("gltfpack is required for LOD generation")
    if not os.path.isfile(source_path):
        raise LODGenerationError("Source GLB is missing")
    os.makedirs(output_dir, exist_ok=True)
    source_size = os.path.getsize(source_path)
    outputs = []
    for level, ratio in enumerate(ratios, start=1):
        ratio = float(ratio)
        if not 0.01 <= ratio < 1:
            raise LODGenerationError("LOD ratios must be between 0.01 and 1")
        filename = f"model_lod{level}.glb"
        destination = os.path.join(output_dir, filename)
        args = command + [
            "-i", source_path, "-o", destination,
            "-si", str(ratio), "-kn", "-ke", "-km",
        ]
        if meshopt:
            args.append("-cc")
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
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
