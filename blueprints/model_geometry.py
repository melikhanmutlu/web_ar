"""Model geometry endpoints: bounding box, GLB validation report, LOD
generation, exploded view, and derived assets (retopology/texture upscale)."""

import math
import os
import secrets
import uuid

import numpy as np
import trimesh
from flask import Blueprint, jsonify, request, url_for
from werkzeug.security import generate_password_hash

from converters.glb_quality import finalize_glb
from models import ConversionJob, ModelDerivedAsset, ModelLOD, db
from services.model_permissions import (
    check_model_mutation_allowed,
    check_model_view_allowed,
    get_live_model,
)
from services.viewer_settings import resolved_viewer_settings

model_geometry_bp = Blueprint("model_geometry", __name__)


@model_geometry_bp.route("/api/models/<model_id>/bounds")
def get_model_bounds(model_id):
    """Get model bounding box for slicer"""
    import app as app_module

    try:
        # Get model from database
        model = app_module.UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status

        # Check if model file exists (live path — the stored one goes stale
        # when the storage root moves between deploys)
        glb_path = model.glb_path
        if not glb_path or not os.path.exists(glb_path):
            return jsonify({"success": False, "error": "Model file not found"}), 404

        # Try to get bounds from database first
        if model.bounds:
            try:
                import json

                bounds_data = json.loads(model.bounds)
                if "min" in bounds_data and "max" in bounds_data:
                    return jsonify(
                        {
                            "success": True,
                            "bounds": {
                                "min": bounds_data["min"],
                                "max": bounds_data["max"],
                                "extents": bounds_data["extents"],
                            },
                        }
                    )
            except Exception as e:
                app_module.logger.warning(f"Could not parse bounds from database: {e}")

        # Calculate bounds from GLB file
        try:
            mesh = trimesh.load(glb_path, force="scene")

            # Get bounds
            if isinstance(mesh, trimesh.Scene):
                bounds = mesh.bounds
            else:
                bounds = mesh.bounds

            # Convert to list and meters
            min_bounds = bounds[0].tolist()
            max_bounds = bounds[1].tolist()
            extents = (bounds[1] - bounds[0]).tolist()

            return jsonify(
                {
                    "success": True,
                    "bounds": {
                        "min": min_bounds,
                        "max": max_bounds,
                        "extents": extents,
                    },
                }
            )

        except Exception as e:
            app_module.logger.error(f"Error calculating bounds: {e}")
            return jsonify(
                {"success": False, "error": "Failed to calculate bounds"}
            ), 500

    except Exception as e:
        app_module.logger.error(f"Error in get_model_bounds: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@model_geometry_bp.route("/api/models/<model_id>/validation")
def get_model_validation(model_id):
    import app as app_module

    model = get_live_model(model_id)
    if not model:
        return jsonify({"success": False, "error": "Model not found"}), 404
    denied = check_model_view_allowed(model_id)
    if denied:
        return jsonify({"success": False, "error": denied.error}), denied.status
    report = model.validation_report
    if report is None and model.filename and os.path.exists(model.filename):
        try:
            report = app_module.asset_quality.inspect(model.filename)
            model.validation_report = report
            model.vertices = report.get("vertices")
            model.faces = report.get("triangles")
            db.session.commit()
        except Exception as exc:
            return jsonify({"success": False, "error": f"Validation failed: {exc}"}), 422
    return jsonify({"success": True, "report": report})


@model_geometry_bp.route("/api/models/<model_id>/lods", methods=["GET", "POST"])
def model_lods(model_id):
    import app as app_module

    model = get_live_model(model_id)
    if not model:
        return jsonify({"success": False, "error": "Model not found"}), 404
    if request.method == "GET":
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        lods = ModelLOD.query.filter_by(model_id=model_id).order_by(ModelLOD.level).all()
        return jsonify({"success": True, "lods": [{
            **lod.to_dict(),
            "url": url_for("model_files.serve_converted_file", unique_id=model_id,
                           filename=os.path.basename(lod.filename)),
        } for lod in lods]})
    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    ratios = data.get("ratios", [0.5, 0.25, 0.1])
    if not isinstance(ratios, list) or not 1 <= len(ratios) <= 5:
        return jsonify({"success": False, "error": "Provide 1-5 LOD ratios"}), 400
    try:
        ratios = [float(value) for value in ratios]
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid LOD ratios"}), 400
    if any(not math.isfinite(value) or value < 0.01 or value >= 1 for value in ratios):
        return jsonify({"success": False, "error": "LOD ratios must be between 0.01 and 1"}), 400
    meshopt = data.get("meshopt", True)
    if not isinstance(meshopt, bool):
        return jsonify({"success": False, "error": "meshopt must be a boolean"}), 400
    if ratios != sorted(ratios, reverse=True):
        return jsonify({"success": False, "error": "LOD ratios must be descending"}), 400
    job_id = str(uuid.uuid4())
    status_token = secrets.token_urlsafe(32)
    job = ConversionJob(
        id=job_id,
        job_type="lod",
        status="pending",
        payload={"job_id": job_id, "model_id": model_id, "ratios": ratios,
                  "meshopt": meshopt},
        user_id=model.user_id,
        status_token_hash=generate_password_hash(status_token),
        max_attempts=2,
    )
    db.session.add(job)
    db.session.commit()
    if not app_module.JOB_QUEUE_ENABLED:
        app_module._start_local_conversion(job_id)
    return jsonify({
        "success": True, "job_id": job_id, "status": "pending",
        "status_token": status_token,
        "status_url": url_for("upload_job_status", job_id=job_id),
    }), 202


@model_geometry_bp.route("/api/models/<model_id>/exploded", methods=["GET", "POST"])
def model_exploded_asset(model_id):
    import app as app_module

    model = get_live_model(model_id)
    if not model:
        return jsonify({"success": False, "error": "Model not found"}), 404
    filename = "model_exploded.glb"
    output = os.path.join(os.path.dirname(model.filename), filename)
    if request.method == "GET":
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        return jsonify({
            "success": True, "ready": os.path.isfile(output),
            "url": url_for("model_files.serve_converted_file", unique_id=model_id, filename=filename) if os.path.isfile(output) else None,
        })
    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard
    try:
        factor = float((request.get_json(silent=True) or {}).get("factor", 0.35))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid explosion factor"}), 400
    if not math.isfinite(factor) or not 0.05 <= factor <= 2.0:
        return jsonify({"success": False, "error": "Explosion factor must be 0.05-2.0"}), 400
    try:
        scene = trimesh.load(model.filename, force="scene")
        geometries = [geometry.copy() for geometry in scene.geometry.values()]
        if len(geometries) < 2:
            return jsonify({"success": False, "error": "Exploded view requires multiple mesh parts"}), 422
        centers = np.array([geometry.centroid for geometry in geometries])
        center = centers.mean(axis=0)
        exploded = trimesh.Scene()
        for index, geometry in enumerate(geometries):
            direction = centers[index] - center
            length = float(np.linalg.norm(direction))
            if length < 1e-8:
                direction = np.array([index + 1.0, 0.0, 0.0])
                length = float(np.linalg.norm(direction))
            geometry.apply_translation((direction / length) * factor)
            exploded.add_geometry(geometry, node_name=f"exploded_{index}")
        temp_output = output + ".tmp"
        exploded.export(temp_output, file_type="glb")
        finalize_glb(temp_output, search_dirs=[os.path.dirname(model.filename)])
        os.replace(temp_output, output)
        settings = resolved_viewer_settings(model)
        settings["exploded_view"] = {"factor": factor, "filename": filename}
        model.viewer_settings = settings
        db.session.commit()
    except Exception as exc:
        app_module.logger.exception("Exploded view generation failed for %s", model_id)
        return jsonify({"success": False, "error": f"Exploded view failed: {exc}"}), 500
    return jsonify({"success": True, "url": url_for(
        "model_files.serve_converted_file", unique_id=model_id, filename=filename
    ), "factor": factor})


@model_geometry_bp.route("/api/models/<model_id>/derivatives", methods=["GET", "POST"])
def model_derivatives(model_id):
    import app as app_module

    model = get_live_model(model_id)
    if not model:
        return jsonify({"success": False, "error": "Model not found"}), 404
    if request.method == "GET":
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        assets = ModelDerivedAsset.query.filter_by(model_id=model_id).all()
        return jsonify({"success": True, "assets": [{
            "kind": asset.kind, "file_size": asset.file_size,
            "metadata": asset.asset_metadata,
            "url": url_for("model_files.serve_converted_file", unique_id=model_id,
                           filename=os.path.basename(asset.filename)),
        } for asset in assets]})
    guard = check_model_mutation_allowed(model_id)
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    kind = data.get("kind")
    if kind not in {"retopology", "texture_upscale"}:
        return jsonify({"success": False, "error": "Invalid derivative kind"}), 400
    payload = {"model_id": model_id, "kind": kind}
    if kind == "retopology":
        try:
            ratio = float(data.get("ratio", 0.65))
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid ratio"}), 400
        if not 0.1 <= ratio <= 0.9:
            return jsonify({"success": False, "error": "Ratio must be 0.1-0.9"}), 400
        payload["ratio"] = ratio
    else:
        factor = data.get("factor", 2)
        if factor not in {2, 4}:
            return jsonify({"success": False, "error": "Factor must be 2 or 4"}), 400
        payload["factor"] = factor
    job_id = str(uuid.uuid4())
    payload["job_id"] = job_id
    status_token = secrets.token_urlsafe(32)
    db.session.add(ConversionJob(
        id=job_id, job_type=kind, status="pending", payload=payload,
        user_id=model.user_id, status_token_hash=generate_password_hash(status_token),
    ))
    db.session.commit()
    if not app_module.JOB_QUEUE_ENABLED:
        app_module._start_local_conversion(job_id)
    return jsonify({
        "success": True, "job_id": job_id, "status_token": status_token,
        "status_url": url_for("upload_job_status", job_id=job_id),
    }), 202
