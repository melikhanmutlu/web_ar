"""Model hotspots/annotations and saved camera views."""

import time

from flask import Blueprint, jsonify, request

from models import CameraView, ModelHotspot, UserModel, db
from services.model_permissions import check_model_mutation_allowed, check_model_view_allowed, get_live_model

hotspots_bp = Blueprint("hotspots", __name__)


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
