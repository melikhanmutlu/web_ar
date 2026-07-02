"""Admin panel blueprint (/admin).

Server-rendered management pages guarded by admin_required. Read pages are
classic Jinja + query-string filters; mutations are small fetch POSTs that
return JSON (CSRF handled by the global fetch wrapper in _security_head.html).

This module deliberately does NOT import app.py (worker.py already does, and
app.py imports this blueprint). Anything shared with the site lives in
model_cleanup.py / site_settings.py.
"""

import logging
import math
import os
import secrets
import shutil
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Blueprint,
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
    AIGenerationJob,
    ConversionJob,
    Folder,
    ModelLike,
    ModelSave,
    User,
    UserModel,
    db,
)
from site_settings import get_setting, set_setting, setting_bool, setting_int

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PER_PAGE = 25
CHART_DAYS = 30
# Mirrors worker.py's stale-processing cutoff (importing worker would pull in app.py)
STALE_PROCESSING_MINUTES = int(os.environ.get("WORKER_STALE_MINUTES", "30"))


def admin_required(f):
    """login_required + is_admin. Non-admins get 404 so /admin stays hidden."""

    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if not getattr(current_user, "is_admin", False):
            abort(404)
        return f(*args, **kwargs)

    return wrapper


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

    stats = {
        "users": db.session.query(func.count(User.id)).scalar() or 0,
        "active_models": UserModel.query.filter(UserModel.deleted_at.is_(None)).count(),
        "trashed_models": UserModel.query.filter(
            UserModel.deleted_at.isnot(None)
        ).count(),
        "storage_bytes": db.session.query(
            func.coalesce(func.sum(UserModel.file_size), 0)
        ).scalar(),
        "views": engagement[0],
        "downloads": engagement[1],
        "shares": engagement[2],
        "ai_ready": AIGenerationJob.query.filter_by(status="ready").count(),
        "ai_failed": AIGenerationJob.query.filter_by(status="failed").count(),
        "queue_pending": ConversionJob.query.filter_by(status="pending").count(),
    }

    health = {
        "failed_jobs_24h": ConversionJob.query.filter(
            ConversionJob.status == "failed", ConversionJob.finished_at >= day_ago
        ).count(),
        "stale_jobs": ConversionJob.query.filter(
            ConversionJob.status == "processing",
            ConversionJob.started_at < stale_cutoff,
        ).count(),
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

    charts = {
        "registrations": _daily_series(User.created_at),
        "uploads": _daily_series(UserModel.upload_date),
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
        "admin/dashboard.html", stats=stats, health=health, charts=charts, recent=recent
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@admin_bp.route("/users")
@admin_required
def users():
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
    query = db.session.query(
        User, stats_sq.c.model_count, stats_sq.c.storage_bytes
    ).outerjoin(stats_sq, User.id == stats_sq.c.uid)

    if q:
        like = f"%{q}%"
        query = query.filter(or_(User.username.ilike(like), User.email.ilike(like)))

    if sort == "oldest":
        query = query.order_by(User.created_at.asc())
    elif sort == "models":
        query = query.order_by(func.coalesce(stats_sq.c.model_count, 0).desc())
    elif sort == "storage":
        query = query.order_by(func.coalesce(stats_sq.c.storage_bytes, 0).desc())
    else:
        sort = "newest"
        query = query.order_by(User.created_at.desc())

    page = paginate(query, _page_arg())
    return render_template("admin/users.html", page=page, q=q, sort=sort)


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
    db.session.commit()
    logger.info(f"admin: {current_user.username} reset password for {user.username}")
    # Shown once in the response; there is no mail infrastructure to send it.
    return jsonify({"success": True, "temp_password": temp_password})


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
        models = UserModel.query.filter_by(user_id=user.id).all()
        for model in models:
            purge_model_completely(db.session, model)
        # Flush the pending model deletes before folders go (folder_id FK).
        db.session.flush()
        # Engagement the user left on other people's models, then their jobs
        # and folders. Job rows only soft-reference models, so plain deletes.
        ModelLike.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        ModelSave.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        AIGenerationJob.query.filter_by(user_id=user.id).delete(
            synchronize_session=False
        )
        ConversionJob.query.filter_by(user_id=user.id).delete(
            synchronize_session=False
        )
        Folder.query.filter_by(user_id=user.id).delete(synchronize_session=False)
        db.session.delete(user)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"admin: deleting user {user_id} failed: {e}")
        return jsonify({"success": False, "error": "Delete failed"}), 500
    logger.info(
        f"admin: {current_user.username} deleted user {username} "
        f"({len(models)} models purged)"
    )
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


@admin_bp.route("/models")
@admin_required
def models():
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

    file_types = [
        row[0]
        for row in db.session.query(UserModel.file_type).distinct().all()
        if row[0]
    ]

    page = paginate(query, _page_arg())
    return render_template(
        "admin/models.html",
        page=page,
        q=q,
        file_type=file_type,
        file_types=sorted(file_types),
        owner=owner,
        owner_user=owner_user,
        status=status,
        sort=sort,
    )


@admin_bp.route("/models/<model_id>/trash", methods=["POST"])
@admin_required
def trash_model(model_id):
    model = UserModel.query.get_or_404(model_id)
    model.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/models/<model_id>/restore", methods=["POST"])
@admin_required
def restore_model(model_id):
    model = UserModel.query.get_or_404(model_id)
    model.deleted_at = None
    db.session.commit()
    return jsonify({"success": True})


@admin_bp.route("/models/<model_id>/purge", methods=["POST"])
@admin_required
def purge_model(model_id):
    model = UserModel.query.get_or_404(model_id)
    try:
        purge_model_completely(db.session, model)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"admin: purging model {model_id} failed: {e}")
        return jsonify({"success": False, "error": "Purge failed"}), 500
    logger.info(f"admin: {current_user.username} purged model {model_id}")
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Conversion jobs
# ---------------------------------------------------------------------------


@admin_bp.route("/jobs")
@admin_required
def jobs():
    status = (request.args.get("status") or "").strip()

    counts = dict(
        db.session.query(ConversionJob.status, func.count())
        .group_by(ConversionJob.status)
        .all()
    )

    query = db.session.query(User.username, ConversionJob).select_from(
        ConversionJob
    ).outerjoin(User, ConversionJob.user_id == User.id)
    if status:
        query = query.filter(ConversionJob.status == status)
    query = query.order_by(ConversionJob.created_at.desc())

    page = paginate(query, _page_arg())
    return render_template(
        "admin/jobs.html",
        page=page,
        status=status,
        counts=counts,
        stale_minutes=STALE_PROCESSING_MINUTES,
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
        db.session.commit()
    return jsonify({"success": True, "requeued": requeued, "failed": failed})


@admin_bp.route("/jobs/<job_id>/delete", methods=["POST"])
@admin_required
def delete_job(job_id):
    job = ConversionJob.query.get_or_404(job_id)
    db.session.delete(job)
    db.session.commit()
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# AI generations
# ---------------------------------------------------------------------------


@admin_bp.route("/ai-jobs")
@admin_required
def ai_jobs():
    status = (request.args.get("status") or "").strip()
    kind = (request.args.get("kind") or "").strip()

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

    query = db.session.query(User.username, AIGenerationJob).select_from(
        AIGenerationJob
    ).outerjoin(User, AIGenerationJob.user_id == User.id)
    if status:
        query = query.filter(AIGenerationJob.status == status)
    if kind:
        query = query.filter(AIGenerationJob.kind == kind)
    query = query.order_by(AIGenerationJob.created_at.desc())

    page = paginate(query, _page_arg())
    return render_template(
        "admin/ai_jobs.html",
        page=page,
        status=status,
        kind=kind,
        counts=counts,
        usage_24h=usage_24h,
        ai_limit=_effective_ai_daily_limit(),
    )


@admin_bp.route("/ai-jobs/<job_id>/delete", methods=["POST"])
@admin_required
def delete_ai_job(job_id):
    job = AIGenerationJob.query.get_or_404(job_id)
    db.session.delete(job)
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

    charts = {
        "uploads": _daily_series(UserModel.upload_date),
        "registrations": _daily_series(User.created_at),
        "likes": _daily_series(ModelLike.created_at),
        "ai_jobs": _daily_series(AIGenerationJob.created_at),
    }

    return render_template(
        "admin/analytics.html",
        top=top,
        totals=totals,
        type_breakdown=type_breakdown,
        charts=charts,
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
        flash("Settings saved. Changes take effect within a minute.", "success")
        return redirect(url_for("admin.settings", tab=tab))

    ceiling = _max_upload_ceiling_mb()
    values = {
        "maintenance_mode": setting_bool("maintenance_mode", False),
        "announcement_text": get_setting("announcement_text", "") or "",
        "registration_enabled": setting_bool("registration_enabled", True),
        "ai_daily_limit": _effective_ai_daily_limit(),
        "max_upload_mb": setting_int("max_upload_mb", ceiling),
    }
    return render_template(
        "admin/settings.html", tab=tab, tabs=SETTINGS_TABS, values=values, ceiling=ceiling
    )
