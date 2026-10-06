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
    from model_cleanup import purge_model_completely

    cutoff = datetime.utcnow() - timedelta(days=TRASH_RETENTION_DAYS)
    expired = UserModel.query.filter(
        UserModel.user_id == user_id, UserModel.deleted_at < cutoff
    ).all()
    for model in expired:
        # Use the shared purge helper so engagement rows (ModelLike/ModelSave)
        # are cleared too — a bare db.session.delete(model) can raise an
        # IntegrityError at commit under Postgres FK enforcement.
        purge_model_completely(db.session, model)
    if expired:
        db.session.commit()
        current_app.logger.info(f"Purged {len(expired)} expired trash models for user {user_id}")


def _storage_usage_for(user_id):
    """Bytes counted against a user's storage quota.

    Product decision (ADM-31): ModelVersion files do NOT count toward the
    quota. Version history is bounded by keep_last_n, so it is a capped
    overhead we absorb rather than bill. The quota is the sum of the models'
    own files, including trashed ones (still on disk until purged). This is
    the one source of truth: upload/API quota checks, the profile, the
    library and the admin screens all call it (admin builds the same sum in
    SQL for per-user listings and must not add version bytes).
    """
    return (
        db.session.query(db.func.coalesce(db.func.sum(UserModel.file_size), 0))
        .filter(UserModel.user_id == user_id)
        .scalar()
    )


def global_storage_quota_mb():
    """Site-wide storage quota (admin setting, else env default)."""
    return setting_int("storage_quota_mb", int(os.getenv("STORAGE_QUOTA_MB", 1024)))


def _storage_quota_bytes(user=None):
    """user's plan (services/plans.py) can override the global site-wide
    default; pass None (or omit) to get the plain global quota."""
    global_default = global_storage_quota_mb()
    return effective_storage_quota_mb(user, global_default) * 1024 * 1024
