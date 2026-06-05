"""
Optional GLB post-processing: shrink converted output with gltfpack (meshoptimizer).

Disabled by default. Set the environment variable GLB_OPTIMIZE=true to enable it.
The step is intentionally fail-safe: if gltfpack is missing, errors, or does not
produce a smaller file, the original GLB is left completely untouched so the
conversion pipeline can never regress.

NOTE: gltfpack output uses KHR_meshopt_compression / KHR_mesh_quantization, which
<model-viewer> decodes natively. Verify a few representative models in the viewer
and AR before turning this on in production.
"""

import os
import shutil
import logging
import platform
import subprocess

logger = logging.getLogger(__name__)


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def _resolve_gltfpack():
    """Return a runnable gltfpack command prefix, or None if unavailable."""
    direct = shutil.which("gltfpack")
    if direct:
        return [direct]

    npx = shutil.which("npx")
    if not npx and platform.system() == "Windows":
        win_npx = r"C:\Program Files\nodejs\npx.cmd"
        npx = win_npx if os.path.exists(win_npx) else None
    if npx:
        # gltfpack is declared in package.json, so `npx gltfpack` resolves locally.
        return [npx, "gltfpack"]
    return None


def is_enabled() -> bool:
    return os.environ.get("GLB_OPTIMIZE", "false").strip().lower() == "true"


def optimize_glb(glb_path: str, timeout: int = 300) -> bool:
    """Compress a GLB in place with gltfpack when GLB_OPTIMIZE=true.

    Returns True only if optimization ran and replaced the file with a smaller one;
    False otherwise (disabled, unavailable, errored, or not smaller). The original
    file is always preserved on any non-success path.
    """
    if not is_enabled():
        return False
    if not glb_path or not os.path.exists(glb_path):
        return False

    cmd_base = _resolve_gltfpack()
    if not cmd_base:
        logger.warning("GLB_OPTIMIZE is on but gltfpack is not available; skipping")
        return False

    tmp_out = glb_path + ".opt.glb"
    # -cc: meshopt compression (decoded natively by model-viewer)
    # -kn / -ke / -km: keep named nodes, extras and materials so the material editor,
    #                  hotspots and animations keep working after optimization.
    cmd = cmd_base + ["-i", glb_path, "-o", tmp_out, "-cc", "-kn", "-ke", "-km"]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        logger.warning(f"gltfpack failed to run: {e}; keeping original GLB")
        _safe_remove(tmp_out)
        return False

    if (
        result.returncode != 0
        or not os.path.exists(tmp_out)
        or os.path.getsize(tmp_out) == 0
    ):
        logger.warning(
            f"gltfpack returned {result.returncode}; keeping original GLB. "
            f"stderr: {(result.stderr or '')[:500]}"
        )
        _safe_remove(tmp_out)
        return False

    before = os.path.getsize(glb_path)
    after = os.path.getsize(tmp_out)
    if after >= before:
        logger.info(
            f"gltfpack output not smaller ({after} >= {before} bytes); keeping original"
        )
        _safe_remove(tmp_out)
        return False

    try:
        shutil.move(tmp_out, glb_path)
    except Exception as e:
        logger.warning(f"Could not replace GLB with optimized file: {e}")
        _safe_remove(tmp_out)
        return False

    logger.info(
        f"GLB optimized with gltfpack: {before} -> {after} bytes "
        f"({100 * (1 - after / before):.1f}% smaller)"
    )
    return True
