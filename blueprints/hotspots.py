"""Model hotspots/annotations and saved camera views."""

import time

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models import CameraView, HotspotComment, ModelHotspot, UserModel, db
from services.model_permissions import check_model_mutation_allowed, check_model_view_allowed, get_live_model

hotspots_bp = Blueprint("hotspots", __name__)

HOTSPOT_COMMENT_MAX_LENGTH = 2000


@hotspots_bp.route("/api/models/<model_id>/hotspots", methods=["GET"])
def get_hotspots(model_id):
    """Get all hotspots for a model"""
    import app as app_module

    try:
        model = get_live_model(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status

        hotspots = ModelHotspot.query.filter_by(model_id=model_id).order_by(ModelHotspot.created_at).all()
        return jsonify({
            "success": True,
            "hotspots": [h.to_dict() for h in hotspots],
            "hotspots_visible": model.hotspots_visible
        })
    except Exception as e:
        app_module.logger.error(f"Error getting hotspots for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/hotspots", methods=["POST"])
def create_hotspot(model_id):
    """Create a new hotspot on a model"""
    import app as app_module

    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        hotspot = ModelHotspot(
            model_id=model_id,
            hotspot_id=data.get("id", f"hotspot-{int(time.time()*1000)}"),
            title=data.get("title", "Untitled"),
            description=data.get("description"),
            position_x=data["position"]["x"],
            position_y=data["position"]["y"],
            position_z=data["position"]["z"],
            normal_x=data.get("normal", {}).get("x"),
            normal_y=data.get("normal", {}).get("y"),
            normal_z=data.get("normal", {}).get("z"),
        )

        # Optional camera view
        camera = data.get("cameraView")
        if camera:
            hotspot.camera_view_id = data.get("cameraViewId")
            orbit = camera.get("orbit", {})
            hotspot.camera_orbit_theta = orbit.get("theta")
            hotspot.camera_orbit_phi = orbit.get("phi")
            hotspot.camera_orbit_radius = orbit.get("radius")
            target = camera.get("target", {})
            hotspot.camera_target_x = target.get("x")
            hotspot.camera_target_y = target.get("y")
            hotspot.camera_target_z = target.get("z")
            hotspot.camera_fov = camera.get("fov")

        db.session.add(hotspot)
        db.session.commit()

        return jsonify({"success": True, "hotspot": hotspot.to_dict()}), 201
    except KeyError as e:
        return jsonify({"success": False, "error": f"Missing required field: {e}"}), 400
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error creating hotspot for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/hotspots/<hotspot_id>", methods=["DELETE"])
def delete_hotspot(model_id, hotspot_id):
    """Delete a specific hotspot"""
    import app as app_module

    try:
        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        hotspot = ModelHotspot.query.filter_by(
            model_id=model_id, hotspot_id=hotspot_id
        ).first()
        if not hotspot:
            return jsonify({"success": False, "error": "Hotspot not found"}), 404

        db.session.delete(hotspot)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error deleting hotspot {hotspot_id} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


def _get_hotspot_or_404(model_id, hotspot_id):
    return ModelHotspot.query.filter_by(model_id=model_id, hotspot_id=hotspot_id).first()


@hotspots_bp.route("/api/models/<model_id>/hotspots/<hotspot_id>/comments", methods=["GET"])
def get_hotspot_comments(model_id, hotspot_id):
    """List a hotspot's discussion thread — same read access as the model itself."""
    import app as app_module

    try:
        if not get_live_model(model_id):
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status

        hotspot = _get_hotspot_or_404(model_id, hotspot_id)
        if not hotspot:
            return jsonify({"success": False, "error": "Hotspot not found"}), 404

        return jsonify({"success": True, "comments": [c.to_dict() for c in hotspot.comments]})
    except Exception as e:
        app_module.logger.error(f"Error getting comments for hotspot {hotspot_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/hotspots/<hotspot_id>/comments", methods=["POST"])
@login_required
def create_hotspot_comment(model_id, hotspot_id):
    """Post a reply to a hotspot's discussion thread. Open to anyone who can
    view the model (not editor-only) — a discussion is meant to collect
    feedback from viewers, not just people who can edit the hotspot itself."""
    import app as app_module

    try:
        if not get_live_model(model_id):
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status

        hotspot = _get_hotspot_or_404(model_id, hotspot_id)
        if not hotspot:
            return jsonify({"success": False, "error": "Hotspot not found"}), 404

        data = request.get_json(silent=True) or {}
        body = (data.get("body") or "").strip()
        if not body:
            return jsonify({"success": False, "error": "Comment cannot be empty"}), 400
        if len(body) > HOTSPOT_COMMENT_MAX_LENGTH:
            return jsonify({"success": False, "error": "Comment is too long"}), 400

        comment = HotspotComment(hotspot_id=hotspot.id, user_id=current_user.id, body=body)
        db.session.add(comment)
        db.session.commit()
        return jsonify({"success": True, "comment": comment.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error posting comment on hotspot {hotspot_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/hotspots/<hotspot_id>/comments/<int:comment_id>", methods=["DELETE"])
@login_required
def delete_hotspot_comment(model_id, hotspot_id, comment_id):
    """A comment's own author, or the model owner (moderation), can delete it."""
    import app as app_module

    try:
        model = get_live_model(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        hotspot = _get_hotspot_or_404(model_id, hotspot_id)
        if not hotspot:
            return jsonify({"success": False, "error": "Hotspot not found"}), 404

        comment = HotspotComment.query.filter_by(id=comment_id, hotspot_id=hotspot.id).first()
        if not comment:
            return jsonify({"success": False, "error": "Comment not found"}), 404

        is_author = comment.user_id == current_user.id
        is_model_owner = model.user_id == current_user.id
        if not (is_author or is_model_owner):
            return jsonify({"success": False, "error": "Forbidden"}), 403

        db.session.delete(comment)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error deleting comment {comment_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/hotspots", methods=["DELETE"])
def delete_all_hotspots(model_id):
    """Delete all hotspots for a model"""
    import app as app_module

    try:
        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        ModelHotspot.query.filter_by(model_id=model_id).delete()
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error deleting all hotspots for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/hotspots/visibility", methods=["PATCH"])
def toggle_hotspots_visibility(model_id):
    """Toggle hotspot visibility for a model"""
    import app as app_module

    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        data = request.get_json()
        model.hotspots_visible = data.get("visible", not model.hotspots_visible)
        db.session.commit()
        return jsonify({"success": True, "hotspots_visible": model.hotspots_visible})
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error toggling hotspot visibility for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/camera-views", methods=["GET"])
def get_camera_views(model_id):
    """Get all saved camera views for a model"""
    import app as app_module

    try:
        if not get_live_model(model_id):
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        views = CameraView.query.filter_by(model_id=model_id).order_by(CameraView.created_at).all()
        return jsonify({"success": True, "views": [v.to_dict() for v in views]})
    except Exception as e:
        app_module.logger.error(f"Error getting camera views for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/camera-views", methods=["POST"])
def create_camera_view(model_id):
    """Save a camera view"""
    import app as app_module

    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        data = request.get_json()
        orbit = data.get("orbit", {})
        target = data.get("target", {})

        view = CameraView(
            model_id=model_id,
            name=data.get("name", "View"),
            orbit_theta=orbit.get("theta", 0),
            orbit_phi=orbit.get("phi", 0),
            orbit_radius=orbit.get("radius", 0),
            target_x=target.get("x", 0),
            target_y=target.get("y", 0),
            target_z=target.get("z", 0),
            fov=data.get("fov"),
        )
        db.session.add(view)
        db.session.commit()
        return jsonify({"success": True, "view": view.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error creating camera view for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@hotspots_bp.route("/api/models/<model_id>/camera-views/<int:view_id>", methods=["DELETE"])
def delete_camera_view(model_id, view_id):
    """Delete a camera view"""
    import app as app_module

    try:
        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        view = CameraView.query.filter_by(id=view_id, model_id=model_id).first()
        if not view:
            return jsonify({"success": False, "error": "View not found"}), 404
        db.session.delete(view)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        app_module.logger.error(f"Error deleting camera view {view_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
