"""Serving converted model files, viewer-saved and on-the-fly thumbnails,
and two decommissioned legacy static-file routes."""

import base64
import io
import logging
import os
import re

from flask import Blueprint, current_app, jsonify, request, send_file, send_from_directory
from flask_login import current_user, login_required

from models import UserModel, db
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


@model_files_bp.route("/converted_files/<path:unique_id>/<path:filename>")
def serve_converted_file(unique_id, filename):
    if not _UUID_RE.match(unique_id):
        current_app.logger.warning(f"Invalid unique_id format rejected: {unique_id}")
        return "Not Found", 404
    if not get_live_model(unique_id):
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
    try:
        return send_from_directory(directory, filename, as_attachment=False)
    except FileNotFoundError:
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

        scene = trimesh.load(glb_path, force="scene")
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

    data = request.get_json()
    if not data or not data.get("image"):
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

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Failed to save viewer thumbnail for {unique_id}: {e}")
        return jsonify({"error": "Failed to save thumbnail"}), 500


@model_files_bp.route("/thumbnail/<unique_id>")
def serve_thumbnail(unique_id):
    """Serve model thumbnail image, generating one on-the-fly if needed."""
    import app as app_module

    if not get_live_model(unique_id):
        return "Model not found", 404
    denied = check_model_view_allowed(unique_id)
    if denied:
        return "Model not found", 404

    thumbnail_path = os.path.join(
        current_app.config["CONVERTED_FOLDER"], unique_id, "thumbnail.png"
    )

    # If thumbnail exists, serve it
    if os.path.exists(thumbnail_path):
        return send_from_directory(
            os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id), "thumbnail.png"
        )

    # Generate thumbnail on-the-fly
    try:
        model = UserModel.query.get(unique_id)
        if not model:
            return "Model not found", 404

        # Try to generate from 3D model using trimesh
        model_path = os.path.join(
            current_app.config["CONVERTED_FOLDER"], unique_id, "model.glb"
        )

        if os.path.exists(model_path):
            # First choice: render the actual geometry (software rasterizer)
            from converters.thumbnail_render import render_thumbnail

            if render_thumbnail(model_path, thumbnail_path):
                return send_from_directory(
                    os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id),
                    "thumbnail.png",
                )

            try:
                import trimesh

                # Load mesh
                mesh = trimesh.load(model_path, file_type="glb")

                # Get scene if it's a Scene object
                if isinstance(mesh, trimesh.Scene):
                    # Combine all geometries
                    meshes = [
                        g
                        for g in mesh.geometry.values()
                        if isinstance(g, trimesh.Trimesh)
                    ]
                    if meshes:
                        combined = trimesh.util.concatenate(meshes)
                    else:
                        raise ValueError("No meshes found in scene")
                else:
                    combined = mesh

                # Render using trimesh's built-in rendering
                # Create a simple PNG with model info
                from PIL import Image, ImageDraw, ImageFont

                img = Image.new("RGB", (256, 256), color=(30, 30, 40))
                draw = ImageDraw.Draw(img)

                # Try to use default font
                try:
                    font = ImageFont.truetype("arial.ttf", 14)
                    font_small = ImageFont.truetype("arial.ttf", 10)
                except:
                    font = ImageFont.load_default()
                    font_small = font

                # Draw model name
                name = model.original_filename[:25]
                draw.text(
                    (128, 100), name, fill=(255, 255, 255), font=font, anchor="mm"
                )

                # Draw model stats
                stats = []
                if hasattr(combined, "vertices"):
                    stats.append(f"{len(combined.vertices)} vertices")
                if hasattr(combined, "faces"):
                    stats.append(f"{len(combined.faces)} faces")

                for i, stat in enumerate(stats):
                    draw.text(
                        (128, 130 + i * 20),
                        stat,
                        fill=(150, 160, 180),
                        font=font_small,
                        anchor="mm",
                    )

                # Save thumbnail (via temp file + atomic rename — see _atomic_replace)
                tmp_thumbnail_path = f"{thumbnail_path}.tmp{os.getpid()}"
                img.save(tmp_thumbnail_path, "PNG")
                app_module._atomic_replace(thumbnail_path, tmp_thumbnail_path)
                return send_from_directory(
                    os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id),
                    "thumbnail.png",
                )

            except Exception as e:
                current_app.logger.warning(
                    f"Failed to generate 3D thumbnail for {unique_id}: {e}"
                )

        # Fallback: Generate SVG-based gradient thumbnail
        import html as html_module

        color = model.color if model.color else "#667eea"
        name = html_module.escape(model.original_filename[:20])
        file_type = html_module.escape(model.file_type or "GLB")

        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
            <defs>
                <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" style="stop-color:{color};stop-opacity:1" />
                    <stop offset="100%" style="stop-color:{color}cc;stop-opacity:1" />
                </linearGradient>
                <radialGradient id="glow" cx="50%" cy="60%" r="50%">
                    <stop offset="0%" style="stop-color:rgba(255,255,255,0.2);stop-opacity:1" />
                    <stop offset="100%" style="stop-color:rgba(255,255,255,0);stop-opacity:1" />
                </radialGradient>
            </defs>
            <rect width="256" height="256" fill="url(#bg)"/>
            <rect width="256" height="256" fill="url(#glow)"/>
            <text x="128" y="120" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-size="16" font-weight="bold">
                {name}
            </text>
            <text x="128" y="145" text-anchor="middle" fill="rgba(255,255,255,0.7)" font-family="Arial, sans-serif" font-size="12">
                {file_type} Model
            </text>
        </svg>"""

        # Save SVG and return directly
        try:
            svg_path = os.path.join(
                current_app.config["CONVERTED_FOLDER"], unique_id, "thumbnail.svg"
            )
            os.makedirs(os.path.dirname(svg_path), exist_ok=True)
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

            return current_app.response_class(
                response=svg_content, status=200, mimetype="image/svg+xml"
            )
        except Exception as e:
            current_app.logger.warning(f"Failed to save SVG thumbnail for {unique_id}: {e}")
            return current_app.response_class(
                response=svg_content, status=200, mimetype="image/svg+xml"
            )

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
