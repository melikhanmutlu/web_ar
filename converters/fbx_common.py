"""Shared low-level helpers for the FBX conversion pipeline (fbx_converter.py,
fbx_probe.py): pyassimp lifecycle/library-path setup and generic filesystem
helpers. Split out of fbx_converter.py (Faz 5 refactor) so fbx_probe.py no
longer has to reach back into the converter module for them.
"""

import contextlib
import glob
import logging
import os
import sys

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def _pyassimp_scene(pyassimp, path, processing=None):
    """Load an assimp scene and guarantee release().

    pyassimp builds disagree on whether load() supports the context-manager
    protocol — several versions (incl. the 4.1.x pinned here) return a plain
    Scene, so `with pyassimp.load(...) as scene` raises
    'Scene object does not support the context manager protocol' and the
    whole FBX dimension/texture/rescue path silently dies. Load explicitly,
    yield, then always release the native scene so peak memory stays low on
    large FBX files (which matters: this used to OOM-kill the worker).
    """
    scene = (pyassimp.load(path, processing=processing)
             if processing is not None else pyassimp.load(path))
    try:
        yield scene
    finally:
        try:
            pyassimp.release(scene)
        except Exception:
            pass


def _ensure_assimp_library_path():
    """Make libassimp discoverable before pyassimp is imported.

    pyassimp resolves the shared library via LD_LIBRARY_PATH; on nix-based
    deploys (Railway/nixpacks) libassimp lives under /nix/store or the nix
    profile, which is not on the default search path.
    """
    if "pyassimp" in sys.modules:
        return
    candidates = []
    for pattern in (
        "/root/.nix-profile/lib/libassimp.so*",
        "/nix/var/nix/profiles/default/lib/libassimp.so*",
        "/nix/store/*/lib/libassimp.so*",
    ):
        candidates = glob.glob(pattern)
        if candidates:
            break
    if not candidates:
        return
    lib_dir = os.path.dirname(candidates[0])
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if lib_dir not in current.split(":"):
        os.environ["LD_LIBRARY_PATH"] = f"{current}:{lib_dir}" if current else lib_dir
        logger.info(f"Added assimp library directory to LD_LIBRARY_PATH: {lib_dir}")


def ensure_directory(path):
    """Ensure directory exists, create if needed."""
    os.makedirs(path, exist_ok=True)


def safe_delete_file(path):
    """Safely delete a file if it exists."""
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def is_valid_extension(filename, extensions):
    """Check if filename has valid extension."""
    return any(filename.lower().endswith(ext) for ext in extensions)
