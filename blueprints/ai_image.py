"""AI image pre-processing (text-to-image / image-to-image before 3D)."""

from flask import Blueprint, jsonify, request
from flask_login import login_required

ai_image_bp = Blueprint("ai_image", __name__)

# Stateless by design: image generation finishes in seconds, produces only
# an image, and Meshy task ids are unguessable — so the task id is handed
# straight to the client which polls the status proxy below. No DB rows,
# gunicorn multi-worker safe, and it does NOT count against the 3D daily
# quota (only HTTP rate limiting applies).
_IMAGE_GEN_KINDS = ("t2i", "i2i")


@ai_image_bp.route("/api/generate-image", methods=["POST"])
@login_required
def generate_image():
    """Start a Meshy image generation task as an optional pre-step to 3D."""
    import ai_generator
    import app as app_module

    if not ai_generator.is_configured():
        return jsonify({"success": False,
                        "error": "AI generation is not configured on this server."}), 503

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "text").strip()
    prompt = (data.get("prompt") or "").strip()
    try:
        if mode == "image":
            image = (data.get("image") or "").strip()
            if not image.startswith("data:image/"):
                return jsonify({"success": False,
                                "error": "A valid image (jpg/png) is required."}), 400
            if not prompt:
                return jsonify({"success": False,
                                "error": "Describe how to transform the image."}), 400
            task_id = ai_generator.start_image_to_image(image, prompt)
            kind = "i2i"
        else:
            if not prompt:
                return jsonify({"success": False,
                                "error": "A text prompt is required."}), 400
            task_id = ai_generator.start_text_to_image(
                prompt, aspect_ratio=(data.get("aspect_ratio") or "1:1"))
            kind = "t2i"
        return jsonify({"success": True, "task_id": task_id, "kind": kind})
    except ai_generator.MeshyError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        app_module.logger.error(f"[generate-image] start error: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Failed to start image generation."}), 500


@ai_image_bp.route("/api/generate-image/<task_id>/status", methods=["GET"])
@login_required
def generate_image_status(task_id):
    """Proxy a Meshy image generation task's status to the client."""
    import ai_generator

    kind = request.args.get("kind", "t2i")
    if kind not in _IMAGE_GEN_KINDS:
        return jsonify({"success": False, "error": "Invalid kind."}), 400
    try:
        t = ai_generator.get_image_gen_task(kind, task_id)
    except ai_generator.MeshyError as e:
        return jsonify({"success": False, "error": str(e)}), 502

    status = t.get("status")
    if status == ai_generator.SUCCEEDED:
        return jsonify({"success": True, "status": "ready",
                        "progress": 100, "image_urls": t.get("image_urls") or []})
    if status in (ai_generator.FAILED, ai_generator.CANCELED):
        return jsonify({"success": True, "status": "failed",
                        "error": t.get("task_error") or "Image generation failed."})
    return jsonify({"success": True, "status": "generating",
                    "progress": t.get("progress") or 0})


def _resolve_image_task(image_task):
    """Turn a {kind, task_id, index} reference into a data URI.

    The 3D step never accepts raw URLs from the client (SSRF); the image is
    re-resolved from Meshy by task id and downloaded server-side because
    Meshy output links expire.
    """
    import ai_generator

    kind = (image_task.get("kind") or "").strip()
    task_id = (image_task.get("task_id") or "").strip()
    try:
        index = int(image_task.get("index", 0))
    except (TypeError, ValueError):
        index = -1
    if kind not in _IMAGE_GEN_KINDS or not task_id or index < 0:
        raise ai_generator.MeshyError("Invalid image task reference.")

    t = ai_generator.get_image_gen_task(kind, task_id)
    urls = t.get("image_urls") or []
    if t.get("status") != ai_generator.SUCCEEDED or index >= len(urls):
        raise ai_generator.MeshyError("The selected image is not ready.")
    return ai_generator.fetch_image_as_data_uri(urls[index])
