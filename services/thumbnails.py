"""Thumbnail generation helpers (real render with a cached placeholder
fallback). Extracted from app.py."""

import logging
import os

from flask import current_app

from models import UserModel

logger = logging.getLogger(__name__)


def _atomic_replace(dest_path, tmp_path):
    """Atomically move a fully-written temp file onto dest_path.

    Thumbnail/USDZ generation runs in daemon threads that a deploy can kill
    mid-write; writing straight to dest_path would leave a permanently
    corrupt file behind (nothing ever re-checks an existing file for
    validity). Writing to tmp_path first and renaming here means dest_path
    only ever holds a complete file.
    """
    try:
        os.replace(tmp_path, dest_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def generate_thumbnail_async(model_id, input_glb_path, color=None, flask_app=None):
    """
    Background task to generate a thumbnail image for a 3D model.
    This runs in a separate thread to not block the upload response.
    """
    try:
        flask_app = flask_app or current_app._get_current_object()
        logger.info(
            f"[Thumbnail Async - {model_id}] Starting background thumbnail generation"
        )

        thumbnail_path = os.path.join(
            flask_app.config["CONVERTED_FOLDER"], model_id, "thumbnail.png"
        )

        # If thumbnail already exists, skip
        if os.path.exists(thumbnail_path):
            logger.info(
                f"[Thumbnail Async - {model_id}] Thumbnail already exists, skipping"
            )
            return

        # First choice: render the actual geometry (software rasterizer, no GPU)
        from converters.thumbnail_render import render_thumbnail

        if render_thumbnail(input_glb_path, thumbnail_path):
            logger.info(
                f"[Thumbnail Async - {model_id}] Real 3D thumbnail rendered"
            )
            return

        # The real render is not possible (empty/degenerate scene, missing
        # decoder...): cache a gradient placeholder PNG next to the model so the
        # route does not retry the render on every request. It lives in its own
        # file so a later successful render still writes thumbnail.png.
        from converters.thumbnail_render import PLACEHOLDER_FILENAME, write_placeholder_thumbnail

        with flask_app.app_context():
            model = UserModel.query.get(model_id)
            if not model:
                logger.warning(
                    f"[Thumbnail Async - {model_id}] Model not found in database"
                )
                return
            write_placeholder_thumbnail(
                os.path.join(os.path.dirname(thumbnail_path), PLACEHOLDER_FILENAME),
                model.original_filename, model.file_type, color or model.color,
            )
            logger.info(f"[Thumbnail Async - {model_id}] Placeholder thumbnail cached")

    except Exception as e:
        logger.error(
            f"[Thumbnail Async - {model_id}] Error in thumbnail generation: {e}"
        )
