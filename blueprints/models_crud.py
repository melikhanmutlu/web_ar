"""Library listing (my_models/trash), folders, and model CRUD: download,
info, color update, soft/hard delete, move, restore, rename."""

import logging
import os
import re
import secrets
import traceback

from flask import Blueprint, current_app, flash, jsonify, redirect, request, send_file, url_for
from flask_login import current_user, login_required
from slugify import slugify
from sqlalchemy.orm import Session

from services.time_utils import datetime
from models import Folder, UserModel, db
from model_cleanup import purge_model_completely
from services.storage_quota import (
    TRASH_RETENTION_DAYS,
    _purge_expired_trash,
    _storage_quota_bytes,
    _storage_usage_for,
)
from version_manager import create_version

models_crud_bp = Blueprint("models_crud", __name__)
logger = logging.getLogger(__name__)


@models_crud_bp.route("/my_models")
@models_crud_bp.route("/my_models/<folder_id>")
@login_required
def my_models(folder_id=None):
    try:
        _purge_expired_trash(current_user.id)

        live = UserModel.deleted_at.is_(None)
        if folder_id:
            current_folder = Folder.query.get_or_404(folder_id)
            if current_folder.user_id != current_user.id:
                from flask import abort
                abort(403)
            folders = Folder.query.filter_by(parent_id=folder_id, user_id=current_user.id).all()
            models = UserModel.query.filter(
                UserModel.folder_id == folder_id, UserModel.user_id == current_user.id, live
            ).all()
        else:
            current_folder = None
            folders = Folder.query.filter_by(parent_id=None, user_id=current_user.id).all()
            models = UserModel.query.filter(
                UserModel.folder_id.is_(None), UserModel.user_id == current_user.id, live
            ).all()

        # Per-folder live model counts + up to 4 thumbnail ids for the cover collage
        folder_model_counts = {}
        folder_previews = {}
        for folder in folders:
            folder_q = UserModel.query.filter(UserModel.folder_id == folder.id, live)
            folder_model_counts[folder.id] = folder_q.count()
            folder_previews[folder.id] = [
                m.id for m in folder_q.order_by(UserModel.upload_date.desc()).limit(4).all()
            ]

        # Trash shows up as its own "folder" card — only need the count here,
        # the dedicated /my_models/trash view renders the actual list.
        trash_count = 0
        if not folder_id:
            trash_count = UserModel.query.filter(
                UserModel.user_id == current_user.id, UserModel.deleted_at.isnot(None)
            ).count()

        from flask import render_template
        return render_template(
            "my_models.html",
            folders=folders,
            models=models,
            current_folder=current_folder,
            folder_model_counts=folder_model_counts,
            folder_previews=folder_previews,
            trash_view=False,
            trash_count=trash_count,
            trash_retention_days=TRASH_RETENTION_DAYS,
            storage_used=_storage_usage_for(current_user.id),
            storage_quota=_storage_quota_bytes(current_user),
        )
    except Exception as e:
        current_app.logger.error(f"Error in my_models: {str(e)}")
        return redirect("/")


@models_crud_bp.route("/my_models/trash")
@login_required
def my_models_trash():
    try:
        _purge_expired_trash(current_user.id)

        trashed_models = (
            UserModel.query.filter(
                UserModel.user_id == current_user.id, UserModel.deleted_at.isnot(None)
            )
            .order_by(UserModel.deleted_at.desc())
            .all()
        )

        from flask import render_template
        return render_template(
            "my_models.html",
            folders=[],
            models=trashed_models,
            current_folder=None,
            folder_model_counts={},
            folder_previews={},
            trash_view=True,
            trash_count=len(trashed_models),
            trash_retention_days=TRASH_RETENTION_DAYS,
            storage_used=_storage_usage_for(current_user.id),
            storage_quota=_storage_quota_bytes(current_user),
        )
    except Exception as e:
        current_app.logger.error(f"Error in my_models_trash: {str(e)}")
        return redirect(url_for("models_crud.my_models"))


@models_crud_bp.route("/download/<model_id>")
@login_required
def download_model(model_id):
    """Download the converted model file."""
    try:
        # Get the model from database
        session = Session(db.engine)
        model = session.get(UserModel, model_id)
        if model is None or model.deleted_at is not None:
            return "Model not found", 404

        if model is None:
            return "File not found", 404

        # Check if user owns this model
        if model.user_id != current_user.id:
            return "Unauthorized", 403

        file_path = os.path.join(current_app.config["CONVERTED_FOLDER"], model_id, "model.glb")
        if not os.path.exists(file_path):
            return "File not found", 404

        base_name = os.path.splitext(model.original_filename)[0] or model_id
        return send_file(
            file_path,
            as_attachment=True,
            download_name=f"{model.display_name or base_name}.glb",
            mimetype="application/octet-stream",
        )
    except Exception as e:
        logger.error(f"Error in download_model: {str(e)}")
        return "An error occurred while downloading the file", 500


# Model ids are UUID strings — the old <int:model_id> converter could never
# match a real id, so this route was unreachable as written.
@models_crud_bp.route("/api/model-info/<model_id>")
@login_required
def get_model_info_api(model_id):
    import app as app_module

    session = Session(db.engine)
    model = session.get(UserModel, model_id)
    if model is None or model.deleted_at is not None:
        return jsonify({"error": "Model not found"}), 404
    if model.user_id != current_user.id:
        flash("You don't have permission to access this model.", "error")
        return redirect(url_for("auth.profile"))

    model_info = app_module.get_file_info(model.glb_path)
    if model_info is None:
        return jsonify({"error": "Model not found"}), 404

    return jsonify(model_info)


@models_crud_bp.route("/api/update-model-color", methods=["POST"])
@login_required
def update_model_color():
    import app as app_module
    from glb_modifier import modify_glb

    try:
        data = request.get_json()
        model_id = data.get("model_id")
        color = data.get("color")

        if not model_id or not color:
            return jsonify(
                {"success": False, "error": "Missing model_id or color"}
            ), 400

        # Get the model
        model = UserModel.query.get(model_id)
        if not model or model.user_id != current_user.id:
            return jsonify(
                {"success": False, "error": "Model not found or unauthorized"}
            ), 404

        try:
            color = app_module.validate_color(color)
            output_path = model.filename
            temp_output = output_path + ".color.tmp.glb"
            if not modify_glb(
                output_path,
                temp_output,
                {"material": {"color": color, "tint_textures": False}},
            ):
                return jsonify({"success": False, "error": "Failed to update model color"}), 500
            os.replace(temp_output, output_path)
            model.color = color
            model.validation_report = app_module.asset_quality.inspect(output_path)
            db.session.commit()
            create_version(
                model_id=model_id,
                operation_type="material",
                operation_details={"color": color},
                comment="Updated model color",
            )
            return jsonify({"success": True}), 200
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error converting model with new color: {str(e)}")
            return jsonify(
                {"success": False, "error": "Failed to update model color"}
            ), 500

    except Exception as e:
        logger.error(f"Error in update_model_color: {str(e)}")
        return jsonify({"success": False, "error": "Server error"}), 500


@models_crud_bp.route("/delete_model/<string:model_id>", methods=["POST"])
@login_required
def delete_model(model_id):
    session = None
    try:
        logger.info(f"Attempting to delete model with ID: {model_id}")
        session = Session(db.engine)

        # Get the model and log its details
        model = session.get(UserModel, model_id)
        if not model:
            logger.warning(f"Model {model_id} not found in database")
            return jsonify({"error": "Model not found"}), 404

        # Ownership check: only the model owner can delete it
        if model.user_id != current_user.id:
            logger.warning(
                f"Unauthorized delete attempt: user {current_user.id} tried to delete model {model_id} owned by {model.user_id}"
            )
            return jsonify({"error": "Unauthorized"}), 403

        logger.info(f"Found model: ID={model.id}")

        # Soft delete by default; permanent only when explicitly requested
        # (from the trash UI) or when the model is already in the trash.
        data = request.get_json(silent=True) or {}
        permanent = bool(data.get("permanent")) or model.deleted_at is not None

        if not permanent:
            try:
                model.deleted_at = datetime.utcnow()
                session.commit()
                logger.info(f"Moved model {model_id} to trash")
                return jsonify({"success": True, "trashed": True}), 200
            except Exception as e:
                session.rollback()
                logger.error(f"Database error trashing model {model_id}: {str(e)}")
                return jsonify({"error": "Database error"}), 500

        # Permanent delete: files + engagement rows + model row (shared helper;
        # file errors are logged and tolerated inside purge_model_completely)
        try:
            purge_model_completely(session, model)
            session.commit()
            logger.info(f"Deleted model {model_id} from database")
            return jsonify({"success": True}), 200
        except Exception as e:
            session.rollback()
            logger.error(f"Database error while deleting model {model_id}: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({"error": "Database error"}), 500

    except Exception as e:
        logger.error(f"Unexpected error deleting model {model_id}: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Unexpected error"}), 500
    finally:
        # ALWAYS close the session
        if session:
            session.close()
            logger.debug(f"Session closed for model {model_id}")


@models_crud_bp.route("/delete_all_models", methods=["POST"])
@login_required
def delete_all_models():
    try:
        # Get all models for the current user
        session = Session(db.engine)
        models = session.query(UserModel).filter_by(user_id=current_user.id).all()
        deleted_count = 0
        failed_count = 0

        # Delete files for each model
        for model in models:
            try:
                purge_model_completely(session, model)
                deleted_count += 1

            except Exception as e:
                failed_count += 1
                logger.error(f"Error deleting model {model.id}: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")

        # Commit database changes
        session.commit()
        logger.info(
            f"Deleted {deleted_count} models, failed to delete {failed_count} models"
        )

        if failed_count > 0:
            return jsonify(
                {
                    "message": f"Partially successful: deleted {deleted_count} models, failed to delete {failed_count} models"
                }
            ), 207
        return jsonify({"message": f"Successfully deleted {deleted_count} models"}), 200

    except Exception as e:
        logger.error(f"Error deleting all models: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Error deleting models"}), 500


@models_crud_bp.route("/delete_selected_models", methods=["POST"])
@login_required
def delete_selected_models():
    try:
        data = request.get_json()
        model_ids = data.get("model_ids", [])

        if not model_ids:
            return jsonify({"success": False, "message": "No models selected"})

        # Get all models that belong to the current user
        models = UserModel.query.filter(
            UserModel.id.in_(model_ids), UserModel.user_id == current_user.id
        ).all()

        if not models:
            return jsonify({"success": False, "message": "No valid models found"})

        for model in models:
            purge_model_completely(db.session, model)

        db.session.commit()
        return jsonify(
            {"success": True, "message": f"Successfully deleted {len(models)} models"}
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting models: {str(e)}")
        return jsonify({"success": False, "message": str(e)})


@models_crud_bp.route("/create_folder", methods=["POST"])
@login_required
def create_folder():
    try:
        folder_name = request.form.get("folder_name")
        parent_id = request.form.get("parent_id")

        if not folder_name:
            flash("Folder name is required", "error")
            return redirect(url_for("models_crud.my_models"))

        # Convert parent_id to int if it exists, otherwise None
        parent_id = int(parent_id) if parent_id else None
        if parent_id is not None and not Folder.query.filter_by(
            id=parent_id, user_id=current_user.id, organization_id=None
        ).first():
            flash("Parent folder not found", "error")
            return redirect(url_for("models_crud.my_models"))

        # Create a URL-friendly slug from the folder name
        slug = f"{slugify(folder_name)[:80] or 'folder'}-{secrets.token_hex(4)}"

        # Check if folder with same name exists in the same parent
        existing_folder = Folder.query.filter_by(
            name=folder_name, parent_id=parent_id, user_id=current_user.id,
            organization_id=None
        ).first()

        if existing_folder:
            flash("A folder with this name already exists", "error")
            return redirect(
                url_for("models_crud.my_models", folder_id=parent_id)
                if parent_id
                else url_for("models_crud.my_models")
            )

        new_folder = Folder(
            name=folder_name, slug=slug, parent_id=parent_id, user_id=current_user.id
        )

        db.session.add(new_folder)
        db.session.commit()

        flash("Folder created successfully", "success")
        return redirect(
            url_for("models_crud.my_models", folder_id=parent_id)
            if parent_id
            else url_for("models_crud.my_models")
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error creating folder: {str(e)}")
        flash("An error occurred while creating the folder", "error")
        return redirect(url_for("models_crud.my_models"))


def delete_folder_recursive(folder):
    # First, recursively delete all subfolders
    for subfolder in Folder.query.filter_by(parent_id=folder.id).all():
        delete_folder_recursive(subfolder)

    # Delete all models in this folder
    UserModel.query.filter_by(folder_id=folder.id).update({"folder_id": None})

    # Delete the folder itself
    db.session.delete(folder)


@models_crud_bp.route("/delete_folder/<int:folder_id>", methods=["POST"])
@login_required
def delete_folder(folder_id):
    try:
        folder = Folder.query.get_or_404(folder_id)

        # Check if folder belongs to current user
        if folder.user_id != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403

        # Recursively delete folder and its contents
        delete_folder_recursive(folder)

        db.session.commit()
        current_app.logger.info(f"Folder {folder_id} deleted successfully")
        return jsonify({"success": True, "message": "Folder deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting folder {folder_id}: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@models_crud_bp.route("/move_model", methods=["POST"])
@login_required
def move_model():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data received"}), 400

        model_id = data.get("model_id")
        folder_id = data.get("folder_id")

        if not model_id:
            return jsonify({"success": False, "error": "Model ID is required"}), 400

        # Convert folder_id to int if it exists, otherwise None
        folder_id = int(folder_id) if folder_id else None

        # Get the model
        model = UserModel.query.get_or_404(model_id)

        # Check if the model belongs to the current user
        if model.user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        # If folder_id is provided, check if the folder exists and belongs to the user
        if folder_id:
            folder = Folder.query.get_or_404(folder_id)
            if folder.user_id != current_user.id:
                return jsonify({"success": False, "error": "Unauthorized"}), 403

        # Update model's folder
        model.folder_id = folder_id
        db.session.commit()

        return jsonify({"success": True, "message": "Model moved successfully"}), 200

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error moving model: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@models_crud_bp.route("/restore_model/<string:model_id>", methods=["POST"])
@login_required
def restore_model(model_id):
    """Bring a model back from the trash."""
    try:
        model = UserModel.query.get_or_404(model_id)
        if model.user_id != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403
        if model.deleted_at is None:
            return jsonify({"success": True, "message": "Model is not in trash"}), 200
        model.deleted_at = None
        # Its folder may have been deleted while the model sat in trash
        if model.folder_id and not Folder.query.get(model.folder_id):
            model.folder_id = None
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error restoring model {model_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@models_crud_bp.route("/restore_selected_models", methods=["POST"])
@login_required
def restore_selected_models():
    """Bulk-restore trashed models back to the active library."""
    try:
        data = request.get_json()
        model_ids = data.get("model_ids", [])

        if not model_ids:
            return jsonify({"success": False, "error": "No models selected"}), 400

        models = UserModel.query.filter(
            UserModel.id.in_(model_ids), UserModel.user_id == current_user.id
        ).all()

        if len(models) != len(model_ids):
            return jsonify(
                {
                    "success": False,
                    "error": "Some models were not found or do not belong to you",
                }
            ), 403

        for model in models:
            model.deleted_at = None
            # Its folder may have been deleted while the model sat in trash
            if model.folder_id and not Folder.query.get(model.folder_id):
                model.folder_id = None

        db.session.commit()
        return jsonify(
            {"success": True, "message": f"Successfully restored {len(models)} models"}
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error restoring models: {str(e)}")
        return jsonify({"success": False, "error": "Failed to restore models"}), 500


@models_crud_bp.route("/rename_folder/<int:folder_id>", methods=["POST"])
@login_required
def rename_folder(folder_id):
    try:
        folder = Folder.query.get_or_404(folder_id)
        if folder.user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        data = request.get_json(silent=True) or {}
        new_name = (data.get("name") or "").strip()[:100]
        if not new_name:
            return jsonify({"success": False, "error": "Folder name is required"}), 400

        duplicate = Folder.query.filter(
            Folder.name == new_name,
            Folder.parent_id == folder.parent_id,
            Folder.user_id == current_user.id,
            Folder.organization_id.is_(None),
            Folder.id != folder.id,
        ).first()
        if duplicate:
            return jsonify({"success": False, "error": "A folder with this name already exists"}), 409

        folder.name = new_name
        db.session.commit()
        return jsonify({"success": True, "name": folder.name}), 200
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error renaming folder {folder_id}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@models_crud_bp.route("/move_selected_models", methods=["POST"])
@login_required
def move_selected_models():
    try:
        data = request.get_json()
        model_ids = data.get("model_ids", [])
        folder_id = data.get("folder_id")

        if not model_ids:
            return jsonify({"success": False, "error": "No models selected"}), 400

        # JS sends folder_id as a string; Integer column needs int (or None)
        folder_id = int(folder_id) if folder_id else None

        # Verify folder exists and belongs to user if folder_id is provided
        if folder_id:
            folder = Folder.query.get_or_404(folder_id)
            if folder.user_id != current_user.id:
                return jsonify({"success": False, "error": "Unauthorized"}), 403

        # Move all selected models
        models = UserModel.query.filter(
            UserModel.id.in_(model_ids), UserModel.user_id == current_user.id
        ).all()

        if len(models) != len(model_ids):
            return jsonify(
                {
                    "success": False,
                    "error": "Some models were not found or do not belong to you",
                }
            ), 403

        for model in models:
            model.folder_id = folder_id

        db.session.commit()
        return jsonify(
            {"success": True, "message": f"Successfully moved {len(models)} models"}
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error moving models: {str(e)}")
        return jsonify({"success": False, "error": "Failed to move models"}), 500


@models_crud_bp.route("/bulk_update_visibility", methods=["POST"])
@login_required
def bulk_update_visibility():
    """Set sharing visibility (private/unlisted/public) on multiple models at once."""
    try:
        data = request.get_json()
        model_ids = data.get("model_ids", [])
        visibility = data.get("visibility")

        if not model_ids:
            return jsonify({"success": False, "error": "No models selected"}), 400
        if visibility not in {"private", "unlisted", "public"}:
            return jsonify({"success": False, "error": "Invalid visibility"}), 400

        models = UserModel.query.filter(
            UserModel.id.in_(model_ids), UserModel.user_id == current_user.id
        ).all()
        if len(models) != len(model_ids):
            return jsonify(
                {"success": False, "error": "Some models were not found or do not belong to you"}
            ), 403

        for model in models:
            model.visibility = visibility
        db.session.commit()
        return jsonify(
            {"success": True, "message": f"Updated visibility for {len(models)} models"}
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk-updating visibility: {str(e)}")
        return jsonify({"success": False, "error": "Failed to update visibility"}), 500


@models_crud_bp.route("/bulk_add_tags", methods=["POST"])
@login_required
def bulk_add_tags():
    """Add one or more tags to multiple models at once (existing tags on
    each model are kept — this only adds, matching the per-model tag editor's
    max of 10 tags of up to 30 chars each)."""
    try:
        data = request.get_json()
        model_ids = data.get("model_ids", [])
        raw_tags = data.get("tags", [])

        if not model_ids:
            return jsonify({"success": False, "error": "No models selected"}), 400
        if not isinstance(raw_tags, list) or not raw_tags:
            return jsonify({"success": False, "error": "tags must be a non-empty list"}), 400

        new_tags = []
        for tag in raw_tags:
            tag = re.sub(r"[^a-z0-9 -]", "", str(tag).strip().lower())[:30]
            if tag and tag not in new_tags:
                new_tags.append(tag)
        if not new_tags:
            return jsonify({"success": False, "error": "No valid tags provided"}), 400

        models = UserModel.query.filter(
            UserModel.id.in_(model_ids), UserModel.user_id == current_user.id
        ).all()
        if len(models) != len(model_ids):
            return jsonify(
                {"success": False, "error": "Some models were not found or do not belong to you"}
            ), 403

        for model in models:
            existing = model.tags.split(",") if model.tags else []
            combined = existing + [t for t in new_tags if t not in existing]
            model.tags = ",".join(combined[:10]) or None
        db.session.commit()
        return jsonify({"success": True, "message": f"Added tags to {len(models)} models"})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk-adding tags: {str(e)}")
        return jsonify({"success": False, "error": "Failed to add tags"}), 500
