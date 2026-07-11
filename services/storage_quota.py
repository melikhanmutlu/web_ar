"""Trash retention and per-user storage quota accounting."""

import os
import shutil

from flask import current_app

from services.time_utils import datetime
from models import UserModel, db
from services.plans import effective_storage_quota_mb
from site_settings import setting_int

TRASH_RETENTION_DAYS = int(os.getenv("TRASH_RETENTION_DAYS", 30))


def _purge_expired_trash(user_id):
    """Permanently delete this user's trashed models older than retention."""
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=TRASH_RETENTION_DAYS)
    expired = UserModel.query.filter(
        UserModel.user_id == user_id, UserModel.deleted_at < cutoff
    ).all()
    for model in expired:
        for base in (current_app.config["CONVERTED_FOLDER"], current_app.config["UPLOAD_FOLDER"]):
            d = os.path.join(base, str(model.id))
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
        db.session.delete(model)
    if expired:
        db.session.commit()
        current_app.logger.info(f"Purged {len(expired)} expired trash models for user {user_id}")


def _storage_usage_for(user_id):
    """Bytes used across all of a user's models, including trash (still on disk)."""
    return (
        db.session.query(db.func.coalesce(db.func.sum(UserModel.file_size), 0))
        .filter(UserModel.user_id == user_id)
        .scalar()
    )


def _storage_quota_bytes(user=None):
    """user's plan (services/plans.py) can override the global site-wide
    default; pass None (or omit) to get the plain global quota."""
    global_default = setting_int("storage_quota_mb", int(os.getenv("STORAGE_QUOTA_MB", 1024)))
    return effective_storage_quota_mb(user, global_default) * 1024 * 1024
