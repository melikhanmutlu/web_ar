"""Multi-model scene builder (Faz 4: "Çoklu model sahne modu"): combine
several of a user's own models into one merged GLB using per-item
position/rotation/scale offsets. The merged file is registered as a brand
new UserModel via app.register_glb_as_model, so it's viewable, AR-able,
and shareable through the existing /view/<id> page like any other model.
"""

import os
import tempfile

import numpy as np
import trimesh
from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from models import UserModel

scenes_bp = Blueprint("scenes", __name__)

MIN_SCENE_ITEMS = 2
MAX_SCENE_ITEMS = 12
MAX_OFFSET_METERS = 1000


@scenes_bp.route("/scenes/new", methods=["GET"])
@login_required
def scene_builder_page():
    models = (
        UserModel.query.filter_by(user_id=current_user.id, deleted_at=None)
        .order_by(UserModel.upload_date.desc())
        .all()
    )
    return render_template("scene_builder.html", models=models,
                          min_items=MIN_SCENE_ITEMS, max_items=MAX_SCENE_ITEMS)


@scenes_bp.route("/api/scenes/build", methods=["POST"])
@login_required
def build_scene():
    """Combine `items` (each referencing one of the caller's own models plus
    a position/rotation/scale) into a single new model."""
    import app as app_module

    data = request.get_json(silent=True) or {}
    name = str(data.get("name") or "Scene").strip()[:80] or "Scene"
    items = data.get("items")
    if not isinstance(items, list) or not MIN_SCENE_ITEMS <= len(items) <= MAX_SCENE_ITEMS:
        return jsonify({
            "success": False,
            "error": f"Provide between {MIN_SCENE_ITEMS} and {MAX_SCENE_ITEMS} models",
        }), 400

    combined = trimesh.Scene()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return jsonify({"success": False, "error": "Invalid scene item"}), 400

        model_id = item.get("model_id")
        model = UserModel.query.filter_by(id=model_id, user_id=current_user.id).first()
        if not model or model.deleted_at is not None:
            return jsonify({"success": False, "error": "Model not found or not owned"}), 404
        if not model.glb_path or not os.path.exists(model.glb_path):
            return jsonify({"success": False, "error": "Model file missing"}), 404

        try:
            position = item.get("position") or {}
            px, py, pz = (float(position.get("x", 0)), float(position.get("y", 0)),
                          float(position.get("z", 0)))
            rotation_deg = float(item.get("rotation_y", 0))
            scale = float(item.get("scale", 1.0))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid position/rotation/scale"}), 400

        if not 0.01 <= scale <= 100:
            return jsonify({"success": False, "error": "scale must be between 0.01 and 100"}), 400
        if any(abs(v) > MAX_OFFSET_METERS for v in (px, py, pz)):
            return jsonify({"success": False, "error": f"position must be within +/-{MAX_OFFSET_METERS}m"}), 400

        try:
            piece = trimesh.load(model.glb_path, force="scene")
        except Exception as e:
            app_module.logger.error(f"[build_scene] Could not load model {model_id}: {e}")
            return jsonify({"success": False, "error": "Could not load model"}), 400

        transform = trimesh.transformations.concatenate_matrices(
            trimesh.transformations.translation_matrix([px, py, pz]),
            trimesh.transformations.rotation_matrix(np.radians(rotation_deg), [0, 1, 0]),
            trimesh.transformations.scale_matrix(scale),
        )
        for geom_name, geometry in piece.geometry.items():
            combined.add_geometry(geometry, node_name=f"item{i}_{geom_name}", transform=transform)

    if len(combined.geometry) == 0:
        return jsonify({"success": False, "error": "No geometry to combine"}), 400

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".glb")
    os.close(tmp_fd)
    try:
        combined.export(tmp_path, file_type="glb")
        new_model = app_module.register_glb_as_model(
            tmp_path, user_id=current_user.id, source="scene", prompt=name,
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return jsonify({
        "success": True,
        "model_id": new_model.id,
        "viewer_url": f"/view/{new_model.id}",
    }), 201
