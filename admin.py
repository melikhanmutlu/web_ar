"""Admin panel blueprint (/admin).

Server-rendered management pages guarded by admin_required. Read pages are
classic Jinja + query-string filters; mutations are small fetch POSTs that
return JSON (CSRF handled by the global fetch wrapper in _security_head.html).

This module deliberately does NOT import app.py (worker.py already does, and
app.py imports this blueprint). Anything shared with the site lives in
model_cleanup.py / site_settings.py.
"""

import csv
import io
import logging
import math
import os
import secrets
import shutil
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from model_cleanup import purge_model_completely
from models import (
    AdminAuditLog,
    AIGenerationJob,
    CameraView,
    ConversionJob,
    Folder,
    ModelHotspot,
    ModelLike,
    ModelSave,
    ModelVersion,
    User,
    UserModel,
    db,
)
from site_settings import get_setting, set_setting, setting_bool, setting_int
from version_manager import delete_version

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PER_PAGE = 25
CHART_DAYS = 30
# Mirrors worker.py's stale-processing cutoff (importing worker would pull in app.py)
STALE_PROCESSING_MINUTES = int(os.environ.get("WORKER_STALE_MINUTES", "30"))
# AI generations only advance via client-side polling (see app.py's
# generate_3d_status) — a closed tab leaves a job stuck in a non-terminal
# state forever with nothing to reconcile it server-side. This is purely a
# visibility threshold, not tied to a sweep.
AI_STALE_MINUTES = int(os.environ.get("AI_STALE_MINUTES", "30"))
# worker.py writes a heartbeat every ~30s when running; allow a few missed
# writes before calling it stale to avoid false alarms from scheduling jitter.
WORKER_HEARTBEAT_STALE_SECONDS = int(os.environ.get("WORKER_HEARTBEAT_STALE_SECONDS", "120"))


def admin_required(f):
    """login_required + is_admin. Non-admins get 404 so /admin stays hidden."""

    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(404)
        return f(*args, **kwargs)

    return wrapper


def log_action(action, target_type=None, target_id=None, detail=None):
    """Record an admin action. Adds to the pending session — the caller's
    existing db.session.commit() picks it up, keeping the log entry and the
    mutation it describes atomic. For routes with no other commit (e.g. a
    settings save that persists through SiteSetting's own commits), the
    caller must commit explicitly after calling this."""
    db.session.add(
        AdminAuditLog(
            actor_id=current_user.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail,
        )
    )


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


class Page:
    def __init__(self, items, page, per_page, total):
        self.items = items
        self.page = page
        self.per_page = per_page
        self.total = total
        self.pages = max(1, math.ceil(total / per_page)) if total else 1
        self.has_prev = page > 1
        self.has_next = page < self.pages


def paginate(query, page, per_page=PER_PAGE):
    total = query.count()
    items = query.limit(per_page).offset((page - 1) * per_page).all()
    return Page(items, page, per_page, total)


def _page_arg():
    try:
        return max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        return 1


DAY_RANGE_CHOICES = (7, 30, 90)


def _days_arg():
    try:
        days = int(request.args.get("days", CHART_DAYS))
    except (TypeError, ValueError):
        return CHART_DAYS
    return days if days in DAY_RANGE_CHOICES else CHART_DAYS


def _csv_response(filename, header, rows):
    """Build a CSV download from a header row + iterable of row tuples."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    writer.writerows(rows)
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _daily_series(date_col, days=CHART_DAYS, extra_filter=None):
    """Per-day row counts for the trailing `days` days, gap-filled."""
    start = datetime.utcnow() - timedelta(days=days - 1)
    start = datetime(start.year, start.month, start.day)
    query = (
        db.session.query(func.date(date_col), func.count())
        .filter(date_col >= start)
        .group_by(func.date(date_col))
    )
    if extra_filter is not None:
        query = query.filter(extra_filter)
    counts = {str(day): count for day, count in query.all()}
    series = []
    for i in range(days):
        day = start + timedelta(days=i)
        series.append(
            {"d": day.strftime("%b %d"), "v": counts.get(day.strftime("%Y-%m-%d"), 0)}
        )
    return series


def _effective_ai_daily_limit():
    return setting_int(
        "ai_daily_limit", current_app.config.get("AI_GEN_DAILY_LIMIT", 10)
    )


def _max_upload_ceiling_mb():
    return int(current_app.config.get("MAX_CONTENT_LENGTH", 100 * 1024 * 1024)) // (
        1024 * 1024
    )


def _effective_storage_quota_mb():
    """Per-user storage cap in MB. 0 means unlimited. Falls back to the
    STORAGE_QUOTA_MB env default (app.py's original module constant) when no
    admin override has been saved yet."""
    return setting_int("storage_quota_mb", int(os.environ.get("STORAGE_QUOTA_MB", 1024)))


def _worker_health():
    """Reads the heartbeat worker.py writes every ~30s. Returns
    (last_seen: datetime|None, seconds_ago: float|None, is_stale: bool).
    No heartbeat ever recorded (JOB_QUEUE off, or worker never started) is
    reported as stale but distinguished from a worker that stopped — the
    dashboard renders each case with different wording."""
    raw = get_setting("worker_heartbeat")
    if not raw:
        return None, None, True
    try:
        last_seen = datetime.fromisoformat(raw)
    except ValueError:
        return None, None, True
    age = (datetime.utcnow() - last_seen).total_seconds()
    return last_seen, age, age > WORKER_HEARTBEAT_STALE_SECONDS


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@admin_bp.route("/")
@admin_required
def dashboard():
    now = datetime.utcnow()
    day_ago = now - timedelta(days=1)
    stale_cutoff = now - timedelta(minutes=STALE_PROCESSING_MINUTES)

    engagement = db.session.query(
        func.coalesce(func.sum(UserModel.view_count), 0),
        func.coalesce(func.sum(UserModel.download_count), 0),
        func.coalesce(func.sum(UserModel.share_count), 0),
    ).first()

    # Each ModelVersion row is a full on-disk GLB copy — without it, "storage
    # used" undercounts real disk usage on heavily-edited models.
    version_storage_bytes = db.session.query(
        func.coalesce(func.sum(ModelVersion.file_size), 0)
    ).scalar()

    stats = {
        "users": db.session.query(func.count(User.id)).scalar() or 0,
        "active_models": UserModel.query.filter(UserModel.deleted_at.is_(None)).count(),
        "trashed_models": UserModel.query.filter(
            UserModel.deleted_at.isnot(None)
        ).count(),
        "storage_bytes": (
            db.session.query(func.coalesce(func.sum(UserModel.file_size), 0)).scalar()
            + version_storage_bytes
        ),
        "views": engagement[0],
        "downloads": engagement[1],
        "shares": engagement[2],
        "ai_ready": AIGenerationJob.query.filter_by(status="ready").count(),
        "ai_failed": AIGenerationJob.query.filter_by(status="failed").count(),
        "queue_pending": ConversionJob.query.filter_by(status="pending").count(),
    }

    ai_stale_cutoff = now - timedelta(minutes=AI_STALE_MINUTES)
    worker_last_seen, worker_seconds_ago, worker_stale = _worker_health()

    health = {
        "failed_jobs_24h": ConversionJob.query.filter(
            ConversionJob.status == "failed", ConversionJob.finished_at >= day_ago
        ).count(),
        "stale_jobs": ConversionJob.query.filter(
            ConversionJob.status == "processing",
            ConversionJob.started_at < stale_cutoff,
        ).count(),
        "stale_ai_jobs": AIGenerationJob.query.filter(
            AIGenerationJob.status == "generating",
            AIGenerationJob.updated_at < ai_stale_cutoff,
        ).count(),
        "worker_last_seen": worker_last_seen,
        "worker_seconds_ago": worker_seconds_ago,
        "worker_stale": worker_stale,
        "disk_total": None,
        "disk_free": None,
        "disk_used_pct": None,
    }
    try:
        usage = shutil.disk_usage(current_app.config["CONVERTED_FOLDER"])
        health["disk_total"] = usage.total
        health["disk_free"] = usage.free
        if usage.total:
            health["disk_used_pct"] = round((usage.total - usage.free) * 100 / usage.total)
    except OSError as e:
        logger.warning(f"disk_usage failed: {e}")

    days = _days_arg()
    charts = {
        "registrations": _daily_series(User.created_at, days=days),
        "uploads": _daily_series(UserModel.upload_date, days=days),
    }

    recent = {
        "uploads": UserModel.query.order_by(UserModel.upload_date.desc())
        .limit(8)
        .all(),
        "users": User.query.order_by(User.created_at.desc()).limit(5).all(),
        "ai_jobs": AIGenerationJob.query.order_by(AIGenerationJob.created_at.desc())
        .limit(5)
        .all(),
    }

    return render_template(
        "admin/dashboard.html", stats=stats, health=health, charts=charts, recent=recent,
        days=days, day_choices=DAY_RANGE_CHOICES, ai_stale_minutes=AI_STALE_MINUTES,
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def _users_query():
    q = (request.args.get("q") or "").strip()
    sort = request.args.get("sort", "newest")

    stats_sq = (
        db.session.query(
            UserModel.user_id.label("uid"),
            func.count(UserModel.id).label("model_count"),
            func.coalesce(func.sum(UserModel.file_size), 0).label("storage_bytes"),
        )
        .group_by(UserModel.user_id)
        .subquery()
    )
    # Version file bytes summed separately (own subquery) to avoid a join
    # fan-out: joining ModelVersion directly into stats_sq would multiply
    # model_count/file_size by each model's version count.
    version_sq = (
        db.session.query(
            UserModel.user_id.label("uid"),
            func.coalesce(func.sum(ModelVersion.file_size), 0).label("version_bytes"),
        )
        .join(ModelVersion, ModelVersion.model_id == UserModel.id)
        .group_by(UserModel.user_id)
        .subquery()
    )
    total_storage = func.coalesce(stats_sq.c.storage_bytes, 0) + func.coalesce(
        version_sq.c.version_bytes, 0
    )
    query = (
        db.session.query(User, stats_sq.c.model_count, total_storage.label("storage_bytes"))
        .outerjoin(stats_sq, User.id == stats_sq.c.uid)
        .outerjoin(version_sq, User.id == version_sq.c.uid)
    )

    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like)))

    if sort == "oldest":
        query = query.order_by(User.created_at.asc())
    elif sort == "models":
        query = query.order_by(func.coalesce(stats_sq.c.model_count, 0).desc())
    elif sort == "storage":
        query = query.order_by(total_storage.desc())
    else:
        sort = "newest"
        query = query.order_by(User.created_at.desc())

    return query, q, sort


@admin_bp.route("/users")
@admin_required
def users():
    query, q, sort = _users_query()
    page = paginate(query, _page_arg())
    return render_template("admin/users.html", page=page, q=q, sort=sort)


@admin_bp.route("/users/export.csv")
@admin_required
def export_users_csv():
    query, _, _ = _users_query()
    rows = (
        (
            u.id, u.username, u.email,
            u.created_at.isoformat() if u.created_at else "",
            model_count or 0, storage_bytes or 0, u.is_admin, u.is_active_flag,
        )
        for u, model_count, storage_bytes in query.all()
    )
    return _csv_response(
        "users.csv",
        ["id", "username", "email", "joined", "models", "storage_bytes", "is_admin", "is_active"],
        rows,
    )


@admin_bp.route("/users/<int:user_id>")
@admin_required
def user_detail(user_id):
    user = User.query.get_or_404(user_id)

    models = (
        UserModel.query.filter_by(user_id=user.id)
        .order_by(UserModel.upload_date.desc())
        .limit(10)
        .all()
    )
    model_count = UserModel.query.filter_by(user_id=user.id).count()
    storage_bytes = (
        db.session.query(func.coalesce(func.sum(UserModel.file_size), 0))
        .filter(UserModel.user_id == user.id)
        .scalar()
    )
    version_bytes = (
        db.session.query(func.coalesce(func.sum(ModelVersion.file_size), 0))
        .join(UserModel, ModelVersion.model_id == UserModel.id)
        .filter(UserModel.user_id == user.id)
        .scalar()
    )
    storage_bytes = (storage_bytes or 0) + (version_bytes or 0)

    since = datetime.utcnow() - timedelta(days=1)
    ai_used_24h = AIGenerationJob.query.filter(
        AIGenerationJob.user_id == user.id, AIGenerationJob.created_at >= since
    ).count()
    ai_total = AIGenerationJob.query.filter_by(user_id=user.id).count()

    return render_template(
        "admin/user_detail.html",
        user=user,
        models=models,
        model_count=model_count,
        storage_bytes=storage_bytes,
        ai_used_24h=ai_used_24h,
        ai_total=ai_total,
        ai_limit=_effective_ai_daily_limit(),
        likes=ModelLike.query.filter_by(user_id=user.id).count(),
        saves=ModelSave.query.filter_by(user_id=user.id).count(),
    )


@admin_bp.route("/users/<int:user_id>/toggle-admin", methods=["POST"])
@admin_required
def toggle_admin(user_id):
    if user_id == current_user.id:
        return jsonify(
            {"success": False, "error": "You cannot change your own admin status"}
        ), 400
    user = User.query.get_or_404(user_id)
    user.is_admin = not user.is_admin
    log_action("user.toggle_admin", "user", user.id, {"is_admin": user.is_admin})
    db.session.commit()
    logger.info(
        f"admin: {current_user.username} set is_admin={user.is_admin} on {user.username}"
    )
    return jsonify({"success": True, "is_admin": user.is_admin})


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def toggle_active(user_id):
    if user_id == current_user.id:
        return jsonify(
            {"success": False, "error": "You cannot deactivate your own account"}
        ), 400
    user = User.query.get_or_404(user_id)
    user.is_active_flag = not user.is_active_flag
    log_action("user.toggle_active", "user", user.id, {"is_active": user.is_active_flag})
    db.session.commit()
    logger.info(
        f"admin: {current_user.username} set is_active={user.is_active_flag} on {user.username}"
    )
    return jsonify({"success": True, "is_active": user.is_active_flag})


@admin_bp.route("/users/<int:user_id>/reset-password", methods=["POST"])
@admin_required
def reset_password(user_id):
    user = User.query.get_or_404(user_id)
    temp_password = secrets.token_urlsafe(9)
    user.set_password(temp_password)
    log_action("user.reset_password", "user", user.id)
    db.session.commit()
    logger.info(f"admin: {current_user.username} reset password for {user.username}")
    # Shown once in the response; there is no mail infrastructure to send it.
    return jsonify({"success": True, "temp_password": temp_password})


def _delete_user_and_content(user):
    """Cascade-delete a user: their models (+ files), engagement they left on
    other users' models, their jobs, and their folders. Caller commits."""
    models = UserModel.query.filter_by(user_id=user.id).all()
    for model in models:
        purge_model_completely(db.session, model)
    # Flush the pending model deletes before folders go (folder_id FK).
    db.session.flush()
    # Job rows only soft-reference models (no FK), so plain deletes suffice.
    ModelLike.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ModelSave.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    AIGenerationJob.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    ConversionJob.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    Folder.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.delete(user)
    return len(models)


def _parse_bulk_ids(cast=str):
    """Read {"ids": [...]} from the JSON body, casting/filtering each entry."""
    raw = (request.get_json(silent=True) or {}).get("ids", [])
    if not isinstance(raw, list):
        return []
    ids = []
    for item in raw:
        try:
            ids.append(cast(item))
        except (TypeError, ValueError):
            continue
    return ids


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        return jsonify(
            {"success": False, "error": "You cannot delete your own account"}
        ), 400
    user = User.query.get_or_404(user_id)
    username = user.username
    try:
        model_count = _delete_user_and_content(user)
        log_action(
            "user.delete", "user", user_id,
            {"username": username, "models_purged": model_count},
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"admin: deleting user {user_id} failed: {e}")
        return jsonify({"success": False, "error": "Delete failed"}), 500
    logger.info(
        f"admin: {current_user.username} deleted user {username} "
        f"({model_count} models purged)"
    )
    return jsonify({"success": True})


@admin_bp.route("/users/bulk-deactivate", methods=["POST"])
@admin_required
def bulk_deactivate_users():
    ids = [i for i in _parse_bulk_ids(int) if i != current_user.id]
    if not ids:
        return jsonify({"success": False, "error": "No valid users selected"}), 400
    users = User.query.filter(User.id.in_(ids)).all()
    for user in users:
        user.is_active_flag = False
    log_action(
        "user.bulk_deactivate", detail={"count": len(users), "ids": [u.id for u in users]}
    )
    db.session.commit()
    return jsonify({"success": True, "count": len(users)})


@admin_bp.route("/users/bulk-delete", methods=["POST"])
@admin_required
def bulk_delete_users():
    ids = [i for i in _parse_bulk_ids(int) if i != current_user.id]
    if not ids:
        return jsonify({"success": False, "error": "No valid users selected"}), 400
    users = User.query.filter(User.id.in_(ids)).all()
    usernames = [u.username for u in users]
    try:
        for user in users:
            _delete_user_and_content(user)
        log_action("user.bulk_delete", detail={"count": len(users), "usernames": usernames})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"admin: bulk delete users failed: {e}")
        return jsonify({"success": False, "error": "Bulk delete failed"}), 500
    return jsonify({"success": True, "count": len(users)})


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _models_query():
    q = (request.args.get("q") or "").strip()
    file_type = (request.args.get("type") or "").strip()
    owner = (request.args.get("user") or "").strip()
    status = request.args.get("status", "active")
    sort = request.args.get("sort", "date")

    query = db.session.query(User.username, UserModel).select_from(UserModel).outerjoin(
        User, UserModel.user_id == User.id
    )

    if status == "trashed":
        query = query.filter(UserModel.deleted_at.isnot(None))
    elif status == "all":
        pass
    else:
        status = "active"
        query = query.filter(UserModel.deleted_at.is_(None))

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                UserModel.display_name.ilike(like),
                UserModel.filename.ilike(like),
                UserModel.id.ilike(like),
            )
        )
    if file_type:
        query = query.filter(UserModel.file_type == file_type)

    owner_user = None
    if owner == "anonymous":
        query = query.filter(UserModel.user_id.is_(None))
    elif owner:
        try:
            owner_id = int(owner)
        except ValueError:
            owner = ""
        else:
            query = query.filter(UserModel.user_id == owner_id)
            owner_user = db.session.get(User, owner_id)

    if sort == "size":
        query = query.order_by(UserModel.file_size.desc().nullslast())
    elif sort == "views":
        query = query.order_by(UserModel.view_count.desc().nullslast())
    else:
        sort = "date"
        query = query.order_by(UserModel.upload_date.desc())

    return query, {"q": q, "file_type": file_type, "owner": owner, "owner_user": owner_user,
                    "status": status, "sort": sort}


@admin_bp.route("/models")
@admin_required
def models():
    query, ctx = _models_query()
    file_types = [
        row[0]
        for row in db.session.query(UserModel.file_type).distinct().all()
        if row[0]
    ]
    page = paginate(query, _page_arg())
    return render_template(
        "admin/models.html",
        page=page,
        file_types=sorted(file_types),
        **ctx,
    )


@admin_bp.route("/models/export.csv")
@admin_required
def export_models_csv():
    query, _ = _models_query()
    rows = (
        (
            m.id, m.display_name or m.original_filename, username or "anonymous",
            m.file_type, m.file_size or 0, m.view_count or 0, m.download_count or 0,
            m.share_count or 0,
            m.upload_date.isoformat() if m.upload_date else "",
            "trashed" if m.deleted_at else "active",
        )
        for username, m in query.all()
    )
    return _csv_response(
        "models.csv",
        ["id", "name", "owner", "type", "file_size", "views", "downloads", "shares",
         "uploaded", "status"],
        rows,
    )


@admin_bp.route("/models/<model_id>")
@admin_required
def model_detail(model_id):
    model = UserModel.query.get_or_404(model_id)

    versions = (
        ModelVersion.query.filter_by(model_id=model_id)
        .order_by(ModelVersion.version_number.desc())
        .all()
    )
    hotspots = (
        ModelHotspot.query.filter_by(model_id=model_id)
        .order_by(ModelHotspot.created_at)
        .all()
    )
    camera_views = (
        CameraView.query.filter_by(model_id=model_id)
        .order_by(CameraView.created_at)
        .all()
    )

    return render_template(
        "admin/model_detail.html",
        model=model,
        versions=versions,
        version_bytes=sum(v.file_size or 0 for v in versions),
        hotspots=hotspots,
        camera_views=camera_views,
        likes=ModelLike.query.filter_by(model_id=model_id).count(),
        saves=ModelSave.query.filter_by(model_id=model_id).count(),
    )


@admin_bp.route("/models/<model_id>/hotspots/<hotspot_id>/delete", methods=["POST"])
@admin_required
def delete_model_hotspot(model_id, hotspot_id):
    hotspot = ModelHotspot.query.filter_by(
        model_id=model_id, hotspot_id=hotspot_id
    ).first_or_404()
    log_action(
        "hotspot.delete", "model", model_id,
        {"hotspot_id": hotspot_id, "title": hotspot.title},
    )
    db.session.delete(hotspot)
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/models/<model_id>/camera-views/<int:view_id>/delete", methods=["POST"])
@admin_required
def delete_model_camera_view(model_id, view_id):
    view = CameraView.query.filter_by(id=view_id, model_id=model_id).first_or_404()
    log_action(
        "camera_view.delete", "model", model_id,
        {"view_id": view_id, "name": view.name},
    )
    db.session.delete(view)
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/models/<model_id>/versions/<int:version_number>/delete", methods=["POST"])
@admin_required
def delete_model_version_admin(model_id, version_number):
    # delete_version() manages its own transaction (models.py's version_manager);
    # only log once it's confirmed the row/file actually went away.
    if not delete_version(model_id, version_number):
        return jsonify({"success": False, "error": "Version not found or delete failed"}), 404
    log_action("version.delete", "model", model_id, {"version_number": version_number})
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/models/<model_id>/trash", methods=["POST"])
@admin_required
def trash_model(model_id):
    model = UserModel.query.get_or_404(model_id)
    model.deleted_at = datetime.utcnow()
    log_action("model.trash", "model", model_id)
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/models/<model_id>/restore", methods=["POST"])
@admin_required
def restore_model(model_id):
    model = UserModel.query.get_or_404(model_id)
    model.deleted_at = None
    log_action("model.restore", "model", model_id)
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/models/<model_id>/purge", methods=["POST"])
@admin_required
def purge_model(model_id):
    model = UserModel.query.get_or_404(model_id)
    try:
        log_action("model.purge", "model", model_id)
        purge_model_completely(db.session, model)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"admin: purging model {model_id} failed: {e}")
        return jsonify({"success": False, "error": "Purge failed"}), 500
    logger.info(f"admin: {current_user.username} purged model {model_id}")
    return jsonify({"success": True})


@admin_bp.route("/models/bulk-trash", methods=["POST"])
@admin_required
def bulk_trash_models():
    ids = _parse_bulk_ids(str)
    if not ids:
        return jsonify({"success": False, "error": "No valid models selected"}), 400
    models = UserModel.query.filter(UserModel.id.in_(ids)).all()
    for model in models:
        model.deleted_at = datetime.utcnow()
    log_action("model.bulk_trash", detail={"count": len(models), "ids": [m.id for m in models]})
    db.session.commit()
    return jsonify({"success": True, "count": len(models)})


@admin_bp.route("/models/bulk-restore", methods=["POST"])
@admin_required
def bulk_restore_models():
    ids = _parse_bulk_ids(str)
    if not ids:
        return jsonify({"success": False, "error": "No valid models selected"}), 400
    models = UserModel.query.filter(UserModel.id.in_(ids)).all()
    for model in models:
        model.deleted_at = None
    log_action("model.bulk_restore", detail={"count": len(models), "ids": [m.id for m in models]})
    db.session.commit()
    return jsonify({"success": True, "count": len(models)})


@admin_bp.route("/models/bulk-purge", methods=["POST"])
@admin_required
def bulk_purge_models():
    ids = _parse_bulk_ids(str)
    if not ids:
        return jsonify({"success": False, "error": "No valid models selected"}), 400
    models = UserModel.query.filter(UserModel.id.in_(ids)).all()
    count = len(models)
    try:
        for model in models:
            purge_model_completely(db.session, model)
        log_action("model.bulk_purge", detail={"count": count, "ids": ids})
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"admin: bulk purge models failed: {e}")
        return jsonify({"success": False, "error": "Bulk purge failed"}), 500
    return jsonify({"success": True, "count": count})


# ---------------------------------------------------------------------------
# Conversion jobs
# ---------------------------------------------------------------------------


def _jobs_query():
    status = (request.args.get("status") or "").strip()
    query = db.session.query(User.username, ConversionJob).select_from(
        ConversionJob
    ).outerjoin(User, ConversionJob.user_id == User.id)
    if status:
        query = query.filter(ConversionJob.status == status)
    query = query.order_by(ConversionJob.created_at.desc())
    return query, status


@admin_bp.route("/jobs")
@admin_required
def jobs():
    query, status = _jobs_query()
    counts = dict(
        db.session.query(ConversionJob.status, func.count())
        .group_by(ConversionJob.status)
        .all()
    )
    page = paginate(query, _page_arg())
    return render_template(
        "admin/jobs.html",
        page=page,
        status=status,
        counts=counts,
        stale_minutes=STALE_PROCESSING_MINUTES,
    )


@admin_bp.route("/jobs/export.csv")
@admin_required
def export_jobs_csv():
    query, _ = _jobs_query()
    rows = (
        (
            j.id, j.job_type, j.status, username or "anonymous", j.attempts, j.max_attempts,
            j.created_at.isoformat() if j.created_at else "",
            j.finished_at.isoformat() if j.finished_at else "",
            j.error or "",
        )
        for username, j in query.all()
    )
    return _csv_response(
        "conversion_jobs.csv",
        ["id", "type", "status", "owner", "attempts", "max_attempts", "created", "finished", "error"],
        rows,
    )


@admin_bp.route("/jobs/<job_id>/retry", methods=["POST"])
@admin_required
def retry_job(job_id):
    job = ConversionJob.query.get_or_404(job_id)
    if job.status != "failed":
        return jsonify({"success": False, "error": "Only failed jobs can be retried"}), 400
    job.status = "pending"
    job.error = None
    job.finished_at = None
    # The worker refuses jobs that already exhausted attempts; grant one more.
    job.max_attempts = max((job.attempts or 0) + 1, job.max_attempts or 1)
    log_action("job.retry", "job", job_id)
    db.session.commit()
    logger.info(f"admin: {current_user.username} requeued failed job {job_id}")
    return jsonify({"success": True})


@admin_bp.route("/jobs/requeue-stale", methods=["POST"])
@admin_required
def requeue_stale():
    """Same recovery pass the worker runs every minute (worker.requeue_stale_jobs);
    duplicated here because importing worker.py would import app.py circularly."""
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PROCESSING_MINUTES)
    stale = ConversionJob.query.filter(
        ConversionJob.status == "processing",
        ConversionJob.started_at < cutoff,
    ).all()
    requeued = failed = 0
    for job in stale:
        staged = (job.payload or {}).get("temp_file_path")
        if staged and not os.path.exists(staged):
            job.status = "failed"
            job.error = "Source file is no longer available — please re-upload the model."
            job.finished_at = datetime.utcnow()
            failed += 1
        elif (job.attempts or 0) >= (job.max_attempts or 1):
            job.status = "failed"
            job.error = "Conversion worker crashed repeatedly on this job."
            job.finished_at = datetime.utcnow()
            failed += 1
        else:
            job.status = "pending"
            requeued += 1
    if stale:
        log_action("job.requeue_stale", detail={"requeued": requeued, "failed": failed})
        db.session.commit()
    return jsonify({"success": True, "requeued": requeued, "failed": failed})


@admin_bp.route("/jobs/<job_id>/delete", methods=["POST"])
@admin_required
def delete_job(job_id):
    job = ConversionJob.query.get_or_404(job_id)
    log_action("job.delete", "job", job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# AI generations
# ---------------------------------------------------------------------------


def _ai_jobs_query():
    status = (request.args.get("status") or "").strip()
    kind = (request.args.get("kind") or "").strip()
    query = db.session.query(User.username, AIGenerationJob).select_from(
        AIGenerationJob
    ).outerjoin(User, AIGenerationJob.user_id == User.id)
    if status:
        query = query.filter(AIGenerationJob.status == status)
    if kind:
        query = query.filter(AIGenerationJob.kind == kind)
    query = query.order_by(AIGenerationJob.created_at.desc())
    return query, status, kind


@admin_bp.route("/ai-jobs")
@admin_required
def ai_jobs():
    query, status, kind = _ai_jobs_query()

    counts = dict(
        db.session.query(AIGenerationJob.status, func.count())
        .group_by(AIGenerationJob.status)
        .all()
    )

    since = datetime.utcnow() - timedelta(days=1)
    usage_24h = (
        db.session.query(User.username, func.count(AIGenerationJob.id))
        .join(User, AIGenerationJob.user_id == User.id)
        .filter(AIGenerationJob.created_at >= since)
        .group_by(User.username)
        .order_by(func.count(AIGenerationJob.id).desc())
        .limit(10)
        .all()
    )

    page = paginate(query, _page_arg())
    return render_template(
        "admin/ai_jobs.html",
        page=page,
        status=status,
        kind=kind,
        counts=counts,
        usage_24h=usage_24h,
        ai_limit=_effective_ai_daily_limit(),
        stale_minutes=AI_STALE_MINUTES,
        stale_cutoff=datetime.utcnow() - timedelta(minutes=AI_STALE_MINUTES),
    )


@admin_bp.route("/ai-jobs/export.csv")
@admin_required
def export_ai_jobs_csv():
    query, _, _ = _ai_jobs_query()
    rows = (
        (
            j.id, username or "anonymous", j.kind, j.status, j.stage or "", j.progress or 0,
            j.model_id or "", (j.prompt or "")[:200],
            j.created_at.isoformat() if j.created_at else "",
            j.error or "",
        )
        for username, j in query.all()
    )
    return _csv_response(
        "ai_jobs.csv",
        ["id", "owner", "kind", "status", "stage", "progress", "model_id", "prompt", "created", "error"],
        rows,
    )


@admin_bp.route("/ai-jobs/<job_id>/delete", methods=["POST"])
@admin_required
def delete_ai_job(job_id):
    job = AIGenerationJob.query.get_or_404(job_id)
    log_action("ai_job.delete", "ai_job", job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/ai-jobs/<job_id>/mark-failed", methods=["POST"])
@admin_required
def mark_ai_job_failed(job_id):
    """Close out a job stuck in a non-terminal state without touching Meshy —
    the client-side poll is the only thing that ever advances these jobs, so
    an abandoned tab leaves one stuck forever with no server-side retry path
    that wouldn't risk starting a duplicate (paid) generation."""
    job = AIGenerationJob.query.get_or_404(job_id)
    if job.status in ("ready", "failed"):
        return jsonify({"success": False, "error": "Job is already finished"}), 400
    job.status = "failed"
    job.error = "Marked as failed by an admin (job was stuck)."
    log_action("ai_job.mark_failed", "ai_job", job_id)
    db.session.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------


@admin_bp.route("/analytics")
@admin_required
def analytics():
    active = UserModel.query.filter(UserModel.deleted_at.is_(None))
    top = {
        "viewed": active.order_by(UserModel.view_count.desc().nullslast())
        .limit(10)
        .all(),
        "downloaded": active.order_by(UserModel.download_count.desc().nullslast())
        .limit(10)
        .all(),
        "shared": active.order_by(UserModel.share_count.desc().nullslast())
        .limit(10)
        .all(),
    }

    totals = {
        "likes": ModelLike.query.count(),
        "saves": ModelSave.query.count(),
    }

    type_breakdown = (
        db.session.query(UserModel.file_type, func.count())
        .filter(UserModel.deleted_at.is_(None))
        .group_by(UserModel.file_type)
        .order_by(func.count().desc())
        .all()
    )

    days = _days_arg()
    charts = {
        "uploads": _daily_series(UserModel.upload_date, days=days),
        "registrations": _daily_series(User.created_at, days=days),
        "likes": _daily_series(ModelLike.created_at, days=days),
        "ai_jobs": _daily_series(AIGenerationJob.created_at, days=days),
    }

    return render_template(
        "admin/analytics.html",
        top=top,
        totals=totals,
        type_breakdown=type_breakdown,
        charts=charts,
        days=days,
        day_choices=DAY_RANGE_CHOICES,
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

SETTINGS_TABS = ("general", "users", "ai", "uploads")


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    tab = request.args.get("tab", "general")
    if tab not in SETTINGS_TABS:
        tab = "general"

    if request.method == "POST":
        if tab == "general":
            set_setting(
                "maintenance_mode",
                "true" if "maintenance_mode" in request.form else "false",
            )
            set_setting(
                "announcement_text", (request.form.get("announcement_text") or "").strip()
            )
        elif tab == "users":
            set_setting(
                "registration_enabled",
                "true" if "registration_enabled" in request.form else "false",
            )
        elif tab == "ai":
            try:
                limit = int(request.form.get("ai_daily_limit", ""))
            except ValueError:
                flash("AI daily limit must be a number.", "error")
                return redirect(url_for("admin.settings", tab=tab))
            if not 0 <= limit <= 10000:
                flash("AI daily limit must be between 0 and 10000.", "error")
                return redirect(url_for("admin.settings", tab=tab))
            set_setting("ai_daily_limit", str(limit))
        elif tab == "uploads":
            ceiling = _max_upload_ceiling_mb()
            try:
                max_mb = int(request.form.get("max_upload_mb", ""))
            except ValueError:
                flash("Upload limit must be a number.", "error")
                return redirect(url_for("admin.settings", tab=tab))
            if not 1 <= max_mb <= ceiling:
                flash(f"Upload limit must be between 1 and {ceiling} MB.", "error")
                return redirect(url_for("admin.settings", tab=tab))
            set_setting("max_upload_mb", str(max_mb))

            try:
                quota_mb = int(request.form.get("storage_quota_mb", ""))
            except ValueError:
                flash("Storage quota must be a number.", "error")
                return redirect(url_for("admin.settings", tab=tab))
            if not 0 <= quota_mb <= 1_000_000:
                flash("Storage quota must be between 0 (unlimited) and 1,000,000 MB.", "error")
                return redirect(url_for("admin.settings", tab=tab))
            set_setting("storage_quota_mb", str(quota_mb))

        # set_setting() commits per-key already; the log entry needs its own
        # commit since nothing else in this branch does one.
        form_detail = {k: v for k, v in request.form.items() if k != "csrf_token"}
        log_action("settings.update", "setting", tab, form_detail)
        db.session.commit()
        flash("Settings saved. Changes take effect within a minute.", "success")
        return redirect(url_for("admin.settings", tab=tab))

    ceiling = _max_upload_ceiling_mb()
    values = {
        "maintenance_mode": setting_bool("maintenance_mode", False),
        "announcement_text": get_setting("announcement_text", "") or "",
        "registration_enabled": setting_bool("registration_enabled", True),
        "ai_daily_limit": _effective_ai_daily_limit(),
        "max_upload_mb": setting_int("max_upload_mb", ceiling),
        "storage_quota_mb": _effective_storage_quota_mb(),
    }
    return render_template(
        "admin/settings.html", tab=tab, tabs=SETTINGS_TABS, values=values, ceiling=ceiling
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------


def _audit_log_query():
    q = (request.args.get("q") or "").strip()
    action = (request.args.get("action") or "").strip()

    query = (
        db.session.query(User.username, AdminAuditLog)
        .select_from(AdminAuditLog)
        .outerjoin(User, AdminAuditLog.actor_id == User.id)
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(User.username.ilike(like), AdminAuditLog.target_id.ilike(like))
        )
    if action:
        query = query.filter(AdminAuditLog.action == action)

    query = query.order_by(AdminAuditLog.created_at.desc())
    return query, q, action


@admin_bp.route("/audit-log")
@admin_required
def audit_log():
    query, q, action = _audit_log_query()
    actions = sorted(
        row[0] for row in db.session.query(AdminAuditLog.action).distinct().all()
    )
    page = paginate(query, _page_arg())
    return render_template(
        "admin/audit_log.html", page=page, q=q, action=action, actions=actions
    )


@admin_bp.route("/audit-log/export.csv")
@admin_required
def export_audit_log_csv():
    query, _, _ = _audit_log_query()
    rows = (
        (
            e.created_at.isoformat() if e.created_at else "",
            username or "",
            e.action, e.target_type or "", e.target_id or "",
            "" if not e.detail else str(e.detail),
        )
        for username, e in query.all()
    )
    return _csv_response(
        "audit_log.csv",
        ["when", "admin", "action", "target_type", "target_id", "detail"],
        rows,
    )
