"""GLB -> USDZ (iOS Quick Look) conversion via Blender, plus the background
refresh that runs after a model's GLB is edited.

Extracted from app.py. Callers should reference these through the module
(``services.usdz.refresh_usdz_after_edit``) so tests can monkeypatch them.
"""

import logging
import os
import shutil
import subprocess
import threading
import time

from flask import current_app

from models import UserModel, db

logger = logging.getLogger(__name__)


def _sweep_stale_usdz_temps(output_usdz_path, max_age_seconds=3600):
    """Remove leftover USDZ temp files (new ``*.tmp<pid>.usdz`` and the legacy
    ``*.usdz.tmp<pid>[.usdz]`` names) older than ``max_age_seconds``."""
    directory = os.path.dirname(output_usdz_path) or "."
    stem = os.path.splitext(os.path.basename(output_usdz_path))[0]
    try:
        names = os.listdir(directory)
    except OSError:
        return
    now = time.time()
    for name in names:
        if not (name.startswith(f"{stem}.tmp") or name.startswith(f"{stem}.usdz.tmp")):
            continue
        path = os.path.join(directory, name)
        try:
            if now - os.path.getmtime(path) > max_age_seconds:
                os.remove(path)
        except OSError:
            pass


def convert_to_usdz(input_glb_path, output_usdz_path):
    """
    Convert GLB to USDZ using Blender script.
    Returns True if successful, False otherwise.
    """
    # Must end in ".usdz": tools/blender_usdz_export.py appends ".usdz" to any
    # other path, which would put the file somewhere we never look.
    temp_usdz_path = f"{os.path.splitext(output_usdz_path)[0]}.tmp{os.getpid()}.usdz"
    _sweep_stale_usdz_temps(output_usdz_path)
    try:
        logger.info(f"Starting USDZ conversion: {input_glb_path} -> {output_usdz_path}")

        # Path to the blender script
        blender_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools",
            "blender_usdz_export.py",
        )

        # Check for blender executable
        blender_exec = "blender"
        # On Windows, try to find commonly used paths if not in PATH
        if os.name == "nt":
            possible_paths = [
                r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
            ]
            # Check if 'blender' is in PATH first
            if shutil.which("blender"):
                blender_exec = "blender"
            else:
                for p in possible_paths:
                    if os.path.exists(p):
                        blender_exec = p
                        break

        # Blender writes to a temp path first, then we atomically rename onto
        # output_usdz_path — this runs in a daemon thread (see
        # refresh_usdz_after_edit) that can be killed mid-write by a deploy;
        # without this, a kill mid-export permanently corrupts an existing
        # model's USDZ with nothing to ever regenerate it.
        # Construct command
        cmd = [
            blender_exec,
            "--background",
            "--python",
            blender_script,
            "--",
            input_glb_path,
            temp_usdz_path,
        ]

        logger.info(f"Running Blender command: {cmd}")

        # Run conversion
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if (
            process.returncode == 0
            and os.path.isfile(temp_usdz_path)
            and os.path.getsize(temp_usdz_path) > 0
        ):
            os.replace(temp_usdz_path, output_usdz_path)
            logger.info(f"USDZ conversion successful: {output_usdz_path}")
            return True
        else:
            logger.warning(f"USDZ conversion failed. Return code: {process.returncode}")
            logger.warning(f"Stdout: {process.stdout}")
            logger.warning(f"Stderr: {process.stderr}")
            if os.path.exists(temp_usdz_path):
                try:
                    os.remove(temp_usdz_path)
                except OSError:
                    pass
            return False

    except Exception as e:
        logger.error(f"Error during USDZ conversion: {e}")
        if os.path.exists(temp_usdz_path):
            try:
                os.remove(temp_usdz_path)
            except OSError:
                pass
        return False


def convert_usdz_async(model_id, input_glb_path, output_usdz_path, flask_app=None):
    """
    Background task to convert GLB to USDZ and update database.
    This runs in a separate thread to not block the upload response.
    """
    try:
        flask_app = flask_app or current_app._get_current_object()
        logger.info(f"[USDZ Async - {model_id}] Starting background USDZ conversion")

        # Blender can't import meshopt/draco GLBs: convert a decompressed copy.
        from converters.glb_optimizer import readable_glb

        with readable_glb(input_glb_path) as readable_path:
            success = convert_to_usdz(readable_path, output_usdz_path)

        if success:
            # Update database with USDZ path
            with flask_app.app_context():
                model = UserModel.query.get(model_id)
                if model:
                    model.usdz_filename = output_usdz_path
                    db.session.commit()
                    logger.info(
                        f"[USDZ Async - {model_id}] Database updated with USDZ path"
                    )
                else:
                    logger.warning(
                        f"[USDZ Async - {model_id}] Model not found in database"
                    )
        else:
            logger.warning(f"[USDZ Async - {model_id}] USDZ conversion failed")

    except Exception as e:
        logger.error(f"[USDZ Async - {model_id}] Error in background conversion: {e}")


def refresh_usdz_after_edit(model_id, glb_path):
    """Regenerate the iOS USDZ in the background after model.glb is rewritten.

    Quick Look serves the USDZ (ios-src), not the GLB — without this, scale/
    material/slice edits show up in the viewer and on Android but iPhone AR
    keeps placing the model at its original size and look.
    """
    usdz_path = os.path.join(current_app.config["CONVERTED_FOLDER"], model_id, "model.usdz")
    try:
        threading.Thread(
            target=convert_usdz_async,
            args=(model_id, glb_path, usdz_path, current_app._get_current_object()),
            daemon=True,
        ).start()
        logger.info(f"[usdz-refresh - {model_id}] Regeneration thread started")
    except Exception as e:
        logger.error(f"[usdz-refresh - {model_id}] Failed to start thread: {e}")
