"""Trash retention and per-user storage quota accounting."""

import os
import shutil

from flask import current_app

from services.time_utils import datetime
from models import ConversionJob, User, UserModel, db
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


# --- Atomic check-and-reserve -------------------------------------------------
# Quota is enforced against committed UserModel rows, but an upload only becomes
# a UserModel after conversion. Without a reservation, N concurrent uploads each
# see the same "used" figure and all pass. So every path that adds bytes to a
# user's account (a) takes a row lock on the user (SELECT ... FOR UPDATE on
# PostgreSQL; SQLAlchemy omits it on SQLite, whose writer lock already
# serializes the transaction; we take it up front with a no-op UPDATE), (b) counts bytes still in flight, and (c) records
# its own reservation in the same transaction. Reservations live on the pending
# ConversionJob (reserved_bytes) and stop counting by themselves once the job
# leaves pending/processing, so there is nothing to release or leak.

_IN_FLIGHT_STATUSES = ("pending", "processing")


def lock_user_storage(user_id):
    """Serialize quota decisions for one user until the transaction ends."""
    if db.session.get_bind().dialect.name == "sqlite":
        # SQLite has no row locks; a no-op write takes the database write lock
        # up front, so a concurrent request waits here instead of reading the
        # same usage and then failing on the read->write lock upgrade.
        db.session.execute(db.update(User).where(User.id == user_id).values(id=User.id))
        return
    db.session.execute(
        db.select(User.id).where(User.id == user_id).with_for_update()
    ).first()


def reserved_bytes_for(user_id):
    """Bytes promised to this user's not-yet-finished upload jobs."""
    return (
        db.session.query(db.func.coalesce(db.func.sum(ConversionJob.reserved_bytes), 0))
        .filter(
            ConversionJob.user_id == user_id,
            ConversionJob.status.in_(_IN_FLIGHT_STATUSES),
        )
        .scalar()
    )


def reserve_storage(user, incoming_bytes):
    """Lock `user`, then check used + in-flight + incoming against their quota.

    Returns None when it fits (the caller must now store `incoming_bytes` as the
    new job's reserved_bytes and commit in this same transaction, which also
    releases the lock) or the quota in MB when it doesn't (the transaction is
    rolled back). Unlimited (0) quotas and anonymous users always fit.
    """
    if user is None or not getattr(user, "is_authenticated", True):
        return None
    quota_bytes = _storage_quota_bytes(user)
    if not quota_bytes:
        return None
    lock_user_storage(user.id)
    total = _storage_usage_for(user.id) + reserved_bytes_for(user.id) + (incoming_bytes or 0)
    if total > quota_bytes:
        db.session.rollback()
        return quota_bytes // (1024 * 1024)
    return None
