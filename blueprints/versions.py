"""Model version history: list, restore, delete, download a specific version."""

import os

from flask import Blueprint, jsonify, send_from_directory

from models import ModelVersion
from services.model_permissions import check_model_mutation_allowed, check_model_view_allowed, get_live_model
from version_manager import delete_version, get_version_history, restore_version, version_path

versions_bp = Blueprint("versions", __name__)


@versions_bp.route("/api/versions/<model_id>", methods=["GET"])
def get_versions(model_id):
    """Get version history for a model"""
    import app as app_module

    try:
        if not get_live_model(model_id):
            return jsonify({"success": False, "error": "Model not found"}), 404
        denied = check_model_view_allowed(model_id)
        if denied:
            return jsonify({"success": False, "error": denied.error}), denied.status
        versions = get_version_history(model_id)
        return jsonify(
            {
                "success": True,
                "versions": [
                    {
                        "id": v.id,
                        "version_number": v.version_number,
                        "operation_type": v.operation_type,
                        "operation_details": v.operation_details,
                        "dimensions": v.dimensions,
                        "vertices": v.vertices,
                        "faces": v.faces,
                        "file_size": v.file_size,
                        "file_size_formatted": v.file_size_formatted,
                        "created_at": v.created_at_formatted,
                        "comment": v.comment,
                    }
                    for v in versions
                ],
            }
        )
    except Exception as e:
        app_module.logger.error(f"Failed to get versions for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@versions_bp.route("/api/versions/<model_id>/restore/<int:version_number>", methods=["POST"])
def restore_model_version(model_id, version_number):
    """Restore model to a specific version"""
    import app as app_module

    try:
        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        success = restore_version(model_id, version_number)
        if success:
            # The restored GLB replaced model.glb — rebuild the iOS USDZ too.
            glb_path = os.path.join(
                app_module.app.config["CONVERTED_FOLDER"], model_id, "model.glb"
            )
            app_module.refresh_usdz_after_edit(model_id, glb_path)
            return jsonify(
                {"success": True, "message": f"Restored to version {version_number}"}
            )
        else:
            return jsonify(
                {"success": False, "error": "Failed to restore version"}
            ), 500
    except Exception as e:
        app_module.logger.error(f"Failed to restore version {version_number} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@versions_bp.route("/api/versions/<model_id>/delete/<int:version_number>", methods=["DELETE"])
def delete_model_version(model_id, version_number):
    """Delete a specific version"""
    import app as app_module

    try:
        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        success = delete_version(model_id, version_number)
        if success:
            return jsonify(
                {"success": True, "message": f"Deleted version {version_number}"}
            )
        else:
            return jsonify({"success": False, "error": "Failed to delete version"}), 500
    except Exception as e:
        app_module.logger.error(f"Failed to delete version {version_number} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@versions_bp.route("/api/versions/<model_id>/download/<int:version_number>", methods=["GET"])
def download_version(model_id, version_number):
    """Download a specific version"""
    import app as app_module

    try:
        guard = check_model_mutation_allowed(model_id)
        if guard is not None:
            return guard
        version = ModelVersion.query.filter_by(
            model_id=model_id, version_number=version_number
        ).first()
        if not version:
            return jsonify({"success": False, "error": "Version not found"}), 404

        version_file = version_path(version)
        if not os.path.exists(version_file):
            return jsonify({"success": False, "error": "Version file not found"}), 404

        directory = os.path.dirname(version_file)
        filename = os.path.basename(version_file)

        return send_from_directory(
            directory,
            filename,
            as_attachment=True,
            download_name=f"model_v{version_number}.glb",
        )
    except Exception as e:
        app_module.logger.error(f"Failed to download version {version_number} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
