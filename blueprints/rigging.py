"""Rigging + Animation (Meshy) -- applies to any existing model, uploaded or
AI-generated, not just "one prompt -> one generation"."""

import uuid

from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required

from models import AIGenerationJob, RigAnimationJob, UserModel, db
from services.model_permissions import check_model_mutation_allowed

rigging_bp = Blueprint("rigging", __name__)


@rigging_bp.route("/api/models/<model_id>/rig", methods=["POST"])
@login_required
def rig_model(model_id):
    """Start a Meshy auto-rig (+ animate) job for an existing model (upload
    or AI-generated). height_meters + up to 10 animation_action_ids are
    collected up front so rig->animate runs as one chained job."""
    import ai_generator
    import app as app_module

    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard

    if not ai_generator.is_configured():
        return jsonify({"success": False,
                        "error": "AI generation is not configured on this server."}), 503

    exceeded, count, limit = app_module._ai_quota_state(current_user.id)
    if exceeded:
        return jsonify({"success": False,
                        "error": f"Daily generation limit reached ({limit}). Try again tomorrow."}), 429

    model = UserModel.query.get(model_id)
    data = request.get_json(silent=True) or {}

    try:
        height_meters = float(data.get("height_meters"))
        if not (0.05 <= height_meters <= 10):
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"success": False,
                        "error": "A valid height_meters (0.05-10) is required."}), 400

    action_ids = data.get("animation_action_ids")
    if not isinstance(action_ids, list) or not action_ids:
        return jsonify({"success": False, "error": "At least one animation is required."}), 400
    try:
        action_ids = [int(a) for a in action_ids][:10]
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid animation selection."}), 400

    # AI-generated models can reference their originating Meshy task directly;
    # plain uploads have no such task and go through model_url instead.
    ai_job = AIGenerationJob.query.filter_by(model_id=model_id).first()
    input_task_id = None
    if ai_job:
        input_task_id = ai_job.meshy_refine_id or ai_job.meshy_image_id or ai_job.meshy_preview_id

    faces = model.faces
    if faces is None:
        try:
            import trimesh
            mesh = trimesh.load(model.glb_path)
            if isinstance(mesh, trimesh.Scene):
                faces = sum(len(g.faces) for g in mesh.geometry.values()
                           if hasattr(g, "faces"))
            else:
                faces = len(mesh.faces)
        except Exception as e:
            app_module.logger.warning(f"[rig] face count check failed: {e}")
            faces = None

    job_id = str(uuid.uuid4())
    try:
        if faces is not None and faces > ai_generator.RIG_MAX_FACES:
            if not input_task_id:
                return jsonify({"success": False, "error":
                    f"This model has too many polygons for rigging (max "
                    f"{ai_generator.RIG_MAX_FACES:,}) and automatic "
                    f"reduction is only available for AI-generated models."}), 400
            remesh_id = ai_generator.start_remesh(input_task_id)
            job = RigAnimationJob(id=job_id, model_id=model_id, user_id=current_user.id,
                                  height_meters=height_meters, animation_action_ids=action_ids,
                                  meshy_remesh_id=remesh_id, stage="remeshing",
                                  status="generating", progress=0)
        else:
            if input_task_id:
                rig_id = ai_generator.start_rig(input_task_id=input_task_id,
                                                height_meters=height_meters)
            else:
                model_url = url_for("model_files.serve_converted_file", unique_id=model.id,
                                    filename="model.glb", _external=True)
                rig_id = ai_generator.start_rig(model_url=model_url, height_meters=height_meters)
            job = RigAnimationJob(id=job_id, model_id=model_id, user_id=current_user.id,
                                  height_meters=height_meters, animation_action_ids=action_ids,
                                  meshy_rig_id=rig_id, stage="rigging",
                                  status="generating", progress=20)
        db.session.add(job)
        db.session.commit()
        return jsonify({"success": True, "job_id": job_id})
    except ai_generator.MeshyError as e:
        if job.status == "finalizing":
            job.status = "failed"
            job.error = str(e)[:2000]
            db.session.commit()
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        app_module.logger.error(f"[rig] start error: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Failed to start rigging."}), 500


@rigging_bp.route("/api/rig-jobs/<job_id>/status", methods=["GET"])
@login_required
def rig_job_status(job_id):
    import ai_generator
    import app as app_module

    job = RigAnimationJob.query.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job not found"}), 404
    if job.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    if job.status not in ("ready", "failed"):
        try:
            app_module._advance_rig_job(job)
        except ai_generator.MeshyError as e:
            return jsonify({"success": False, "error": str(e)}), 502
        except Exception as e:
            app_module.logger.error(f"[rig-status] error: {e}", exc_info=True)
            return jsonify({"success": False, "error": "Status check failed."}), 500

    resp = job.to_dict(); resp["success"] = True
    if job.status == "ready" and job.result_model_id:
        resp["viewer_url"] = url_for("viewer.view_model", model_id=job.result_model_id)
    return jsonify(resp)
