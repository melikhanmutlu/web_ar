"""
Optional GLB post-processing: shrink converted output with gltfpack (meshoptimizer).

Disabled by default. Set the environment variable GLB_OPTIMIZE=true to enable it.
The step is intentionally fail-safe: if gltfpack is missing, errors, or does not
produce a smaller file, the original GLB is left completely untouched so the
conversion pipeline can never regress.

NOTE: gltfpack -cc output uses EXT_meshopt_compression / KHR_mesh_quantization.
<model-viewer> does NOT decode EXT_meshopt_compression by default (unlike DRACO,
which ships with a built-in decoder location) -- the app must explicitly set
ModelViewerElement.meshoptDecoderLocation before any model loads, or a
meshopt-compressed GLB is valid but silently never renders. See the
<script> block right after model-viewer's own <script> tag in
templates/view.html, embed.html, compare.html, and index.html.
"""

import os
import shutil
import logging
import platform
import subprocess
import tempfile
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def _safe_remove(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


# Compression extensions that trimesh cannot decode. Any GLB requiring one of
# these must be decompressed before a server-side geometry op (dimensions,
# slicer bounds, slicing, exploded view) can read it -- otherwise trimesh loads
# an empty scene and every measurement/operation silently returns zeros/None.
_COMPRESSION_EXTENSIONS = ("EXT_meshopt_compression", "KHR_draco_mesh_compression")


def glb_needs_decompression(glb_path: str) -> bool:
    """True if the GLB is meshopt- or draco-compressed (trimesh can't read it)."""
    try:
        if not glb_path or not os.path.exists(glb_path):
            return False
        from pygltflib import GLTF2

        gltf = GLTF2().load(glb_path)
        required = list(getattr(gltf, "extensionsRequired", None) or [])
        return any(ext in required for ext in _COMPRESSION_EXTENSIONS)
    except Exception:
        # Dependency-light fallback: scan the GLB JSON chunk for the names.
        try:
            with open(glb_path, "rb") as f:
                head = f.read(262144)
            return any(ext.encode() in head for ext in _COMPRESSION_EXTENSIONS)
        except Exception:
            return False


def _decompress_glb_to_temp(glb_path: str, timeout: int = 120):
    """Produce an uncompressed temp copy of a compressed GLB via gltfpack (which
    decodes meshopt and draco input natively). Returns the temp path, or None if
    gltfpack is unavailable or fails. Caller owns the returned temp file."""
    cmd_base = _resolve_gltfpack()
    if not cmd_base:
        logger.warning("GLB needs decompression but gltfpack is unavailable: %s", glb_path)
        return None
    fd, tmp_out = tempfile.mkstemp(suffix=".glb", prefix="decompressed_")
    os.close(fd)
    # -noq: no quantization -- re-export plain float attributes trimesh can read.
    # Deliberately omit -cc so the output is uncompressed.
    cmd = cmd_base + ["-i", glb_path, "-o", tmp_out, "-noq", "-kn", "-ke", "-km"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        logger.warning("gltfpack decompression failed to run for %s: %s", glb_path, e)
        _safe_remove(tmp_out)
        return None
    if result.returncode != 0 or not os.path.exists(tmp_out) or os.path.getsize(tmp_out) == 0:
        logger.warning("gltfpack decompression returned %s for %s", result.returncode, glb_path)
        _safe_remove(tmp_out)
        return None
    return tmp_out


def decompress_glb_in_place(glb_path: str) -> bool:
    """If glb_path is meshopt/draco-compressed, replace it with an uncompressed
    (editable) version so trimesh-based edits (slice / transform / material)
    can run. Returns True if it decompressed the file, False if it was already
    editable or decompression was unavailable/failed (caller decides whether to
    treat that as fatal). The edit inherently rewrites geometry to an
    uncompressed form anyway, so converting up front keeps the model editable
    going forward instead of hard-blocking every edit."""
    if not glb_needs_decompression(glb_path):
        return False
    tmp = _decompress_glb_to_temp(glb_path)
    if not tmp:
        return False
    try:
        shutil.move(tmp, glb_path)
        return True
    except Exception as e:
        logger.warning("Could not replace %s with decompressed copy: %s", glb_path, e)
        _safe_remove(tmp)
        return False


@contextmanager
def readable_glb(glb_path: str):
    """Yield a filesystem path to a GLB that trimesh can read.

    If glb_path is meshopt/draco-compressed, yields a temporary uncompressed
    copy (auto-removed on exit); otherwise yields glb_path unchanged. Use this
    to wrap every server-side `trimesh.load(...)` on a stored model.glb so
    compression never silently zeroes out dimensions/bounds/slicing.
    """
    tmp = None
    if glb_needs_decompression(glb_path):
        tmp = _decompress_glb_to_temp(glb_path)
    try:
        yield tmp or glb_path
    finally:
        if tmp:
            _safe_remove(tmp)


def glb_requires_meshopt(glb_path: str) -> bool:
    """Return True if the GLB requires EXT_meshopt_compression.

    gltfpack output (when GLB_OPTIMIZE is on) uses meshopt compression, which
    trimesh CANNOT decode. Editing such a file (slice / material / transform) would
    silently corrupt it, so callers should refuse to edit when this returns True.
    """
    try:
        if not glb_path or not os.path.exists(glb_path):
            return False
        from pygltflib import GLTF2

        gltf = GLTF2().load(glb_path)
        required = list(getattr(gltf, "extensionsRequired", None) or [])
        return "EXT_meshopt_compression" in required
    except Exception:
        # Dependency-light fallback: scan the GLB JSON chunk for the extension name.
        try:
            with open(glb_path, "rb") as f:
                head = f.read(262144)
            return b"EXT_meshopt_compression" in head
        except Exception:
            return False


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


def _resolve_gltf_transform():
    direct = shutil.which("gltf-transform")
    if direct:
        return [direct]
    npx = shutil.which("npx")
    if not npx and platform.system() == "Windows":
        win_npx = r"C:\Program Files\nodejs\npx.cmd"
        npx = win_npx if os.path.exists(win_npx) else None
    return [npx, "gltf-transform"] if npx else None


def is_enabled() -> bool:
    return os.environ.get("GLB_OPTIMIZE", "false").strip().lower() == "true"


def optimize_glb(glb_path: str, timeout: int = 300, enabled=None, mode="meshopt") -> bool:
    """Compress a GLB in place with gltfpack when GLB_OPTIMIZE=true.

    Returns True only if optimization ran and replaced the file with a smaller one;
    False otherwise (disabled, unavailable, errored, or not smaller). The original
    file is always preserved on any non-success path.
    """
    if enabled is None:
        enabled = is_enabled()
    if not enabled:
        return False
    if not glb_path or not os.path.exists(glb_path):
        return False

    if mode not in {"meshopt", "draco"}:
        logger.warning("Unknown GLB compression mode: %s", mode)
        return False
    cmd_base = _resolve_gltf_transform() if mode == "draco" else _resolve_gltfpack()
    if not cmd_base:
        logger.warning("GLB_OPTIMIZE is on but the %s optimizer is not available; skipping", mode)
        return False

    tmp_out = glb_path + ".opt.glb"
    # -cc: meshopt compression (decoded natively by model-viewer)
    # -kn / -ke / -km: keep named nodes, extras and materials so the material editor,
    #                  hotspots and animations keep working after optimization.
    if mode == "draco":
        cmd = cmd_base + ["optimize", glb_path, tmp_out, "--compress", "draco"]
    else:
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
        # Atomic swap: viewer requests never see a half-written GLB
        os.replace(tmp_out, glb_path)
    except Exception as e:
        logger.warning(f"Could not replace GLB with optimized file: {e}")
        _safe_remove(tmp_out)
        return False

    logger.info(
        f"GLB optimized with gltfpack: {before} -> {after} bytes "
        f"({100 * (1 - after / before):.1f}% smaller)"
    )
    return True
