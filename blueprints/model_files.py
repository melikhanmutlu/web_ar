"""Serving converted model files, viewer-saved and on-the-fly thumbnails,
and two decommissioned legacy static-file routes."""

import base64
import io
import logging
import os
import re

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from flask_login import current_user, login_required
from werkzeug.exceptions import NotFound

from converters.glb_optimizer import readable_glb
from models import UserModel, db
from services.request_json import json_dict
from services.model_permissions import (
    check_model_mutation_allowed,
    check_model_view_allowed,
    get_live_model,
)

model_files_bp = Blueprint("model_files", __name__)
logger = logging.getLogger(__name__)

# Formats trimesh can re-export a loaded GLB scene into. These are
# geometry-only formats (no PBR materials/textures) -- an inherent
# limitation of the formats themselves, not something this endpoint works
# around.
EXPORT_FORMATS = {"stl", "obj", "ply"}

# Validate unique_id is a proper UUID to prevent path traversal.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

# Only published, viewer-facing assets may be served from a model directory.
# The dir also holds internal-only files (model_backup_<ts>.glb from Save/Slice,
# modified_<ts>.glb from Apply, temp_*.glb work files) that must never be
# handed out through this public route -- they can contain geometry the owner
# later removed. Everything the viewer/AR actually requests matches one of
# these: the canonical GLB, the iOS USDZ, and the derived variants (LODs,
# exploded view, retopology, texture upscale).
_ALLOWED_SERVE_RE = re.compile(
    r"^(?:"
    r"model\.glb"
    r"|model_lod\d+\.glb"
    r"|model_exploded\.glb"
    r"|model_retopology\.glb"
    r"|model_textures_\d+x\.glb"
    r"|[\w.-]+\.usdz"
    r")$"
)


def _scope_cache(response, model):
    """Only models with public visibility may be cached by shared caches
    (proxies/CDNs); unlisted/private/share-link/org content stays private to
    the requesting browser."""
    if model is not None and model.visibility != "public":
        response.cache_control.public = False
        response.cache_control.private = True
    return response


@model_files_bp.route("/converted_files/<path:unique_id>/<path:filename>")
def serve_converted_file(unique_id, filename):
    if not _UUID_RE.match(unique_id):
        current_app.logger.warning(f"Invalid unique_id format rejected: {unique_id}")
        return "Not Found", 404
    live_model = get_live_model(unique_id)
    if not live_model:
        return "Not Found", 404
    denied = check_model_view_allowed(unique_id)
    if denied:
        return "Not Found", 404
    directory = os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id)
    current_app.logger.info(f"Attempting to serve file: {filename} from directory: {directory}")
    # Basic security check: ensure filename is just a filename, not trying to escape
    if os.path.basename(filename) != filename:
        current_app.logger.warning(f"Potential unsafe filename detected: {filename}")
        return "Not Found", 404
    # Restrict to the published, viewer-facing asset names -- never serve
    # backups/modified/temp working files that also live in this directory.
    if not _ALLOWED_SERVE_RE.match(filename):
        current_app.logger.warning(f"Non-published filename rejected: {filename}")
        return "Not Found", 404
    try:
        # Older FBX jobs may have written textures as ``data:`` image URIs.
        # model-viewer's GLTFLoader can reject those inside a GLB and display
        # the geometry with white materials. Normalize affected legacy files
        # on their first Viewer/download request; files already using native
        # bufferView images are left untouched.
        if filename.lower().endswith(".glb"):
            glb_path = os.path.join(directory, filename)
            if os.path.isfile(glb_path):
                try:
                    from converters.glb_quality import embed_data_uri_textures

                    if embed_data_uri_textures(glb_path):
                        current_app.logger.info(
                            "Normalized data URI textures before serving %s", glb_path
                        )
                except Exception as exc:
                    # Serving the original asset is safer than making a valid
                    # model unavailable if a legacy repair cannot be applied.
                    current_app.logger.warning(
                        "Could not normalize GLB texture URIs for %s: %s",
                        glb_path,
                        exc,
                    )
        # Content is cache-busted with ?v= query params, so a 1-day TTL is
        # safe and avoids a revalidation round-trip on every viewer load.
        return _scope_cache(
            send_from_directory(directory, filename, as_attachment=False, max_age=86400),
            live_model,
        )
    except (FileNotFoundError, NotFound):
        # send_from_directory raises werkzeug's NotFound for a missing file
        current_app.logger.error(
            f"File not found in serve_converted_file: {directory}/{filename}"
        )
        return "File not found", 404
    except Exception as e:
        current_app.logger.error(f"Error serving file: {e}")
        return "Server error", 500


@model_files_bp.route("/api/models/<model_id>/export/<fmt>", methods=["GET"])
def export_model_as(model_id, fmt):
    """Download the model re-exported as an alternate geometry format
    (STL/OBJ/PLY), derived on the fly from the current GLB via trimesh."""
    if fmt not in EXPORT_FORMATS:
        return jsonify({"success": False, "error": "Unsupported export format"}), 400

    model = get_live_model(model_id)
    if not model:
        return jsonify({"success": False, "error": "Model not found"}), 404
    # Non-GLB re-exports are owner-tier, not just view-tier: only the model's
    # owner (or an editor the owner granted access to) can download STL/OBJ/PLY.
    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard

    glb_path = model.glb_path
    if not os.path.exists(glb_path):
        return jsonify({"success": False, "error": "Model file not found"}), 404

    try:
        import trimesh

        with readable_glb(glb_path) as readable_path:
            scene = trimesh.load(readable_path, force="scene")
        exported = scene.export(file_type=fmt)
        if isinstance(exported, str):
            exported = exported.encode("utf-8")
    except Exception as e:
        current_app.logger.error(f"Error exporting model {model_id} as {fmt}: {e}")
        return jsonify({"success": False, "error": "Export failed"}), 500

    base_name = os.path.splitext(model.original_filename or "")[0] or model_id
    return send_file(
        io.BytesIO(exported),
        as_attachment=True,
        download_name=f"{model.display_name or base_name}.{fmt}",
        mimetype="application/octet-stream",
    )


@model_files_bp.route("/api/thumbnail/<unique_id>", methods=["POST"])
@login_required
def save_viewer_thumbnail(unique_id):
    """Save a screenshot from the viewer as the model thumbnail."""
    model = UserModel.query.get(unique_id)
    if not model or model.user_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403

    data = json_dict()
    if not isinstance(data.get("image"), str) or not data["image"]:
        return jsonify({"error": "No image data"}), 400

    try:
        img_data = data["image"]
        # Strip data URL prefix if present
        img_data = re.sub(r"^data:image/\w+;base64,", "", img_data)
        try:
            img_bytes = base64.b64decode(img_data, validate=True)
            if len(img_bytes) > 5 * 1024 * 1024:
                return jsonify({"error": "Thumbnail exceeds 5 MB"}), 413
            from io import BytesIO
            from PIL import Image
            with Image.open(BytesIO(img_bytes)) as image:
                image.verify()
                if image.format != "PNG":
                    return jsonify({"error": "Thumbnail must be a PNG image"}), 400
        except (ValueError, OSError, base64.binascii.Error):
            return jsonify({"error": "Invalid thumbnail image"}), 400

        thumb_dir = os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id)
        os.makedirs(thumb_dir, exist_ok=True)
        thumb_path = os.path.join(thumb_dir, "thumbnail.png")

        with open(thumb_path, "wb") as f:
            f.write(img_bytes)
        from converters.thumbnail_render import mark_thumbnail_current
        mark_thumbnail_current(thumb_path)
        model.bump_asset_version()
        db.session.commit()

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Failed to save viewer thumbnail for {unique_id}: {e}")
        return jsonify({"error": "Failed to save thumbnail"}), 500


@model_files_bp.route("/thumbnail/<unique_id>")
def serve_thumbnail(unique_id):
    """Serve model thumbnail image, generating one on-the-fly if needed."""
    import app as app_module

    model = get_live_model(unique_id)
    if not model:
        # Library Trash: the owner still has to recognise what they are about
        # to restore, so serve the already-stored thumbnail of THEIR OWN
        # trashed models (privately cached, never generated on the fly).
        trashed = db.session.get(UserModel, unique_id)
        if (
            trashed is not None
            and trashed.deleted_at is not None
            and current_user.is_authenticated
            and trashed.user_id == current_user.id
        ):
            trash_thumb = os.path.join(
                current_app.config["CONVERTED_FOLDER"], unique_id, "thumbnail.png"
            )
            if os.path.exists(trash_thumb):
                response = send_from_directory(
                    os.path.dirname(trash_thumb), "thumbnail.png", max_age=3600
                )
                response.cache_control.public = False
                response.cache_control.private = True
                return response
        return "Model not found", 404
    denied = check_model_view_allowed(unique_id)
    if denied:
        return "Model not found", 404

    thumbnail_path = os.path.join(
        current_app.config["CONVERTED_FOLDER"], unique_id, "thumbnail.png"
    )

    # AI thumbnails rendered before texture sampling was added are cached on
    # the persistent volume. Refresh those once; manually captured/non-AI
    # thumbnails remain untouched.
    if os.path.exists(thumbnail_path) and (model.source or "").startswith("ai"):
        from converters.thumbnail_render import thumbnail_is_current
        if not thumbnail_is_current(thumbnail_path):
            try:
                os.remove(thumbnail_path)
            except OSError:
                pass

    # If thumbnail exists, serve it
    if os.path.exists(thumbnail_path):
        return _scope_cache(send_from_directory(
            os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id), "thumbnail.png",
            max_age=86400,
        ), model)

    model_dir = os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id)
    model_path = os.path.join(model_dir, "model.glb")
    from converters.thumbnail_render import (
        PLACEHOLDER_FILENAME, render_thumbnail, write_placeholder_thumbnail,
    )
    placeholder_path = os.path.join(model_dir, PLACEHOLDER_FILENAME)

    # A cached placeholder means the real render already failed for this
    # geometry; don't retry on every request unless the model changed since.
    def _placeholder_fresh():
        try:
            return (os.path.getmtime(placeholder_path) >= os.path.getmtime(model_path)
                    if os.path.exists(model_path) else True)
        except OSError:
            return False

    if os.path.exists(placeholder_path) and _placeholder_fresh():
        return _scope_cache(send_from_directory(model_dir, PLACEHOLDER_FILENAME, max_age=86400), model)

    # Generate thumbnail on-the-fly
    try:
        if os.path.exists(model_path):
            # Real geometry (software rasterizer; heavy/compressed models are
            # decompressed/decimated inside render_thumbnail)
            if render_thumbnail(model_path, thumbnail_path):
                return send_from_directory(model_dir, "thumbnail.png")

        write_placeholder_thumbnail(
            placeholder_path, model.original_filename, model.file_type, model.color,
        )
        return _scope_cache(send_from_directory(model_dir, PLACEHOLDER_FILENAME, max_age=86400), model)

    except Exception as e:
        current_app.logger.error(f"Error generating thumbnail for {unique_id}: {e}")
        return "Error generating thumbnail", 500


@model_files_bp.route("/converted/<path:filename>")
def get_converted_file(filename):
    """Serve converted model files."""
    try:
        # Get model from database
        model = UserModel.query.filter_by(
            filename=os.path.join(current_app.config["CONVERTED_FOLDER"], filename),
            deleted_at=None,
        ).first()
        if not model:
            current_app.logger.error(f"Model not found for file: {filename}")
            return "File not found", 404
        denied = check_model_view_allowed(model.id)
        if denied:
            return "File not found", 404

        # Check if file exists
        if not os.path.exists(model.filename):
            current_app.logger.error(f"File not found: {model.filename}")
            return "File not found", 404

        # Get directory and filename from full path
        directory = os.path.dirname(model.filename)
        basename = os.path.basename(model.filename)

        return send_from_directory(directory, basename)
    except Exception as e:
        current_app.logger.error(f"Error serving file: {str(e)}")
        return "Error serving file", 500


@model_files_bp.route("/temp/<filename>")
def get_temp_file(filename):
    """Serve temporary files (like QR codes)."""
    return "Legacy temporary-file endpoint removed", 410


@model_files_bp.route("/qr/<filename>")
def get_qr_code(filename):
    """Serve QR code files."""
    return "Legacy QR endpoint removed", 410
