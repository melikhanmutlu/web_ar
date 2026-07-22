"""AI text/image -> 3D generation: start a Meshy generation job, poll its
status, and receive Meshy's webhook wake-up signal."""

import uuid

from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_

from blueprints.ai_image import _IMAGE_GEN_KINDS, _resolve_image_task
from blueprints.material_presets import _resolve_prompt_preset
from models import AIGenerationJob, User, db

ai_generation_bp = Blueprint("ai_generation", __name__)

_AI_TOPOLOGY_CHOICES = {"quad", "triangle"}
_AI_SYMMETRY_CHOICES = {"off", "auto", "on"}
_AI_POSE_MODE_CHOICES = {"a-pose", "t-pose"}
_AI_ORIGIN_AT_CHOICES = {"bottom", "center"}


def _parse_ai_options(raw):
    """Whitelist-parse the client-supplied 'options' sub-dict for a generation
    request. The raw client dict is never passed through to ai_generator --
    each field is extracted and validated individually here."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    negative_prompt = (raw.get("negative_prompt") or "").strip()
    if negative_prompt:
        out["negative_prompt"] = negative_prompt[:600]
    seed = raw.get("seed")
    if isinstance(seed, int) and not isinstance(seed, bool):
        out["seed"] = seed
    if raw.get("topology") in _AI_TOPOLOGY_CHOICES:
        out["topology"] = raw["topology"]
    target_polycount = raw.get("target_polycount")
    if isinstance(target_polycount, int) and not isinstance(target_polycount, bool):
        out["target_polycount"] = target_polycount
    if raw.get("symmetry_mode") in _AI_SYMMETRY_CHOICES:
        out["symmetry_mode"] = raw["symmetry_mode"]
    if isinstance(raw.get("moderation"), bool):
        out["moderation"] = raw["moderation"]
    if raw.get("pose_mode") in _AI_POSE_MODE_CHOICES:
        out["pose_mode"] = raw["pose_mode"]
    if raw.get("origin_at") in _AI_ORIGIN_AT_CHOICES:
        out["origin_at"] = raw["origin_at"]
    if raw.get("remove_lighting") is True:
        out["remove_lighting"] = True
    if isinstance(raw.get("should_texture"), bool):
        out["should_texture"] = raw["should_texture"]
    texture_prompt = (raw.get("texture_prompt") or "").strip()
    if texture_prompt:
        out["texture_prompt"] = texture_prompt[:600]
    return out


@ai_generation_bp.route("/api/generate-3d", methods=["POST"])
@login_required
def generate_3d():
    """Start a Meshy text/image -> 3D generation job (login + daily quota)."""
    import ai_generator
    import app as app_module

    if not ai_generator.is_configured():
        return jsonify({"success": False,
                        "error": "AI generation is not configured on this server."}), 503

    # Serialize quota checks per user on PostgreSQL so concurrent requests
    # cannot each observe the same remaining credit and overspend it.
    user = db.session.query(User).filter_by(id=current_user.id).with_for_update().one()
    allowed, count, limit = app_module._consume_ai_allowance(user)
    if not allowed:
        from services.upgrade import upgrade_hint
        return jsonify({"success": False,
                        "error": f"Monthly generation limit reached ({limit}) and no AI credits left. "
                                 "Buy a credit pack or upgrade your plan.",
                        "upgrade": upgrade_hint("ai_credits")}), 429

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "text").strip()
    options = _parse_ai_options(data.get("options"))
    job_id = str(uuid.uuid4())
    try:
        parent_job_id = data.get("parent_job_id")
        if parent_job_id:
            parent = AIGenerationJob.query.filter_by(
                id=parent_job_id, user_id=current_user.id
            ).first()
            if not parent:
                return jsonify({"success": False, "error": "Parent generation not found"}), 404
        if mode == "image":
            image_task = data.get("image_task")
            if isinstance(image_task, dict):
                # an AI-generated image from the pre-processing step,
                # resolved server-side from its Meshy task id
                image = _resolve_image_task(image_task)
            else:
                image = (data.get("image") or "").strip()
            if not image.startswith("data:image/"):
                return jsonify({"success": False,
                                "error": "A valid image (jpg/png) is required."}), 400
            task_id = ai_generator.start_image_to_3d(
                image, topology=options.get("topology"),
                target_polycount=options.get("target_polycount"),
                symmetry_mode=options.get("symmetry_mode"),
                moderation=options.get("moderation"),
                pose_mode=options.get("pose_mode"),
                origin_at=options.get("origin_at"),
                remove_lighting=options.get("remove_lighting"),
                should_texture=options.get("should_texture", True))
            job = AIGenerationJob(id=job_id, user_id=current_user.id, kind="image",
                                  stage="image", meshy_image_id=task_id,
                                  status="generating", progress=0, options=options,
                                  parent_job_id=parent_job_id)
            # Persist the source image (decoded from the inline data URI) for
            # admin audit -- see _persist_ai_source_image.
            job.source_image_ref = app_module._persist_ai_source_image(job_id, image)
        else:
            prompt = (data.get("prompt") or "").strip()
            if not prompt and parent_job_id:
                prompt = parent.prompt or ""
            if not prompt:
                return jsonify({"success": False,
                                "error": "A text prompt is required."}), 400
            prompt, custom_preset_id = _resolve_prompt_preset(data.get("preset_id"), prompt)
            prompt = prompt[:600]
            task_id = ai_generator.start_text_to_3d(
                prompt, negative_prompt=options.get("negative_prompt"),
                seed=options.get("seed"), topology=options.get("topology"),
                target_polycount=options.get("target_polycount"),
                symmetry_mode=options.get("symmetry_mode"),
                moderation=options.get("moderation"))
            job = AIGenerationJob(id=job_id, user_id=current_user.id, kind="text",
                                  prompt=prompt, stage="preview", meshy_preview_id=task_id,
                                  status="generating", progress=0, options=options,
                                  parent_job_id=parent_job_id,
                                  preset_id=custom_preset_id)
        texture_image_url = (data.get("options") or {}).get("texture_image_url") \
            if isinstance(data.get("options"), dict) else None
        if texture_image_url:
            job.texture_ref = app_module._stash_texture_reference(job_id, texture_image_url)
        db.session.add(job)
        db.session.commit()
        return jsonify({"success": True, "job_id": job_id})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except ai_generator.MeshyError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        app_module.logger.error(f"[generate-3d] start error: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Failed to start generation."}), 500


@ai_generation_bp.route("/api/generate-3d/<job_id>/status", methods=["GET"])
@login_required
def generate_3d_status(job_id):
    """Poll a generation job; advances text two-stage and finalizes on success."""
    import ai_generator
    import app as app_module

    # Status polling advances the external two-stage workflow. Locking prevents
    # simultaneous polls from launching duplicate paid refine/finalize work.
    job = AIGenerationJob.query.filter_by(id=job_id).with_for_update().first()
    if not job:
        return jsonify({"success": False, "error": "Job not found"}), 404
    if job.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    if job.status not in ("ready", "failed"):
        try:
            app_module._advance_ai_job(job)
        except ai_generator.MeshyError as e:
            return jsonify({"success": False, "error": str(e)}), 502
        except Exception as e:
            app_module.logger.error(f"[generate-3d] status error: {e}", exc_info=True)
            return jsonify({"success": False, "error": "Status check failed."}), 500

    resp = job.to_dict(); resp["success"] = True
    if job.status == "ready" and job.model_id:
        resp["viewer_url"] = url_for("viewer.view_model", model_id=job.model_id)
        resp["model_glb_url"] = url_for("model_files.serve_converted_file", unique_id=job.model_id,
                                        filename="model.glb")
    return jsonify(resp)


@ai_generation_bp.route("/api/webhooks/meshy", methods=["POST"])
def meshy_webhook():
    """Receive Meshy task-status-change events.

    Meshy webhooks are configured account-wide (one fixed URL) -- there is no
    per-task callback_url for text/image-to-3d, so this endpoint cannot carry
    a per-job secret. It is therefore treated purely as a "wake up and
    re-check" signal: only task_id is trusted from the payload, and the job's
    real state is always re-fetched from Meshy via _advance_ai_job, never
    read out of the request body. Always returns 200 -- including for an
    unknown or already-finished job -- so the endpoint never leaks which
    task_ids are valid/in-flight to an unauthenticated caller.
    """
    import app as app_module

    payload = request.get_json(silent=True) or {}
    task_id = payload.get("id") or payload.get("task_id")
    if not task_id:
        return jsonify({"ok": True}), 200

    job = AIGenerationJob.query.filter(
        or_(
            AIGenerationJob.meshy_preview_id == task_id,
            AIGenerationJob.meshy_refine_id == task_id,
            AIGenerationJob.meshy_image_id == task_id,
        )
    ).first()
    if not job or job.status in ("ready", "failed"):
        return jsonify({"ok": True}), 200

    try:
        app_module._advance_ai_job(job)
    except Exception as e:
        app_module.logger.warning(f"[meshy-webhook] advance failed for job {job.id}: {e}")
    return jsonify({"ok": True}), 200
