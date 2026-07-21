"""Like/save/share/download engagement counters and per-model analytics."""

import csv
import io
import uuid
from datetime import timedelta

from flask import Blueprint, Response, jsonify, request, session
from flask_login import current_user, login_required

from services.time_utils import datetime
from models import ModelAnalyticsEvent, ModelLike, ModelSave, Organization, OrganizationMember, UserModel, db
from services.model_analytics import ANALYTICS_EVENT_TYPES, record_model_event
from services.model_permissions import check_model_view_allowed, get_live_model
from services.org_membership import _organization_membership
from services.plans import plan_limit

engagement_bp = Blueprint("engagement", __name__)


@engagement_bp.route("/api/models/<model_id>/like", methods=["POST"])
def toggle_like(model_id):
    model = UserModel.query.get_or_404(model_id)
    denied = check_model_view_allowed(model_id)
    if denied:
        return jsonify({"error": denied.error}), denied.status
    if current_user.is_authenticated:
        existing = ModelLike.query.filter_by(
            model_id=model_id, user_id=current_user.id
        ).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify(
                {
                    "liked": False,
                    "count": ModelLike.query.filter_by(model_id=model_id).count(),
                }
            )
        like = ModelLike(model_id=model_id, user_id=current_user.id)
    else:
        sid = session.get("_id", str(uuid.uuid4()))
        session["_id"] = sid
        existing = ModelLike.query.filter_by(model_id=model_id, session_id=sid).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify(
                {
                    "liked": False,
                    "count": ModelLike.query.filter_by(model_id=model_id).count(),
                }
            )
        like = ModelLike(model_id=model_id, session_id=sid)
    db.session.add(like)
    db.session.commit()
    return jsonify(
        {"liked": True, "count": ModelLike.query.filter_by(model_id=model_id).count()}
    )


@engagement_bp.route("/api/models/<model_id>/save", methods=["POST"])
@login_required
def toggle_save(model_id):
    model = UserModel.query.get_or_404(model_id)
    denied = check_model_view_allowed(model_id)
    if denied:
        return jsonify({"error": denied.error}), denied.status
    existing = ModelSave.query.filter_by(
        model_id=model_id, user_id=current_user.id
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"saved": False})
    save = ModelSave(model_id=model_id, user_id=current_user.id)
    db.session.add(save)
    db.session.commit()
    return jsonify({"saved": True})


@engagement_bp.route("/api/models/<model_id>/share", methods=["POST"])
def track_share(model_id):
    model = UserModel.query.get_or_404(model_id)
    denied = check_model_view_allowed(model_id)
    if denied:
        return jsonify({"error": denied.error}), denied.status
    UserModel.query.filter_by(id=model_id).update({
        UserModel.share_count: db.func.coalesce(UserModel.share_count, 0) + 1
    })
    record_model_event(model_id, "share")
    db.session.refresh(model)
    return jsonify({"shares": model.share_count})


@engagement_bp.route("/api/models/<model_id>/track-download", methods=["POST"])
def track_download(model_id):
    model = UserModel.query.get_or_404(model_id)
    denied = check_model_view_allowed(model_id)
    if denied:
        return jsonify({"error": denied.error}), denied.status
    UserModel.query.filter_by(id=model_id).update({
        UserModel.download_count: db.func.coalesce(UserModel.download_count, 0) + 1
    })
    record_model_event(model_id, "download")
    db.session.refresh(model)
    return jsonify({"downloads": model.download_count})


@engagement_bp.route("/api/models/<model_id>/events", methods=["POST"])
def create_model_analytics_event(model_id):
    if not get_live_model(model_id):
        return jsonify({"success": False, "error": "Model not found"}), 404
    denied = check_model_view_allowed(model_id)
    if denied:
        return jsonify({"success": False, "error": denied.error}), denied.status
    data = request.get_json(silent=True) or {}
    event_type = data.get("event_type")
    if event_type not in ANALYTICS_EVENT_TYPES - {"view", "embed_view"}:
        return jsonify({"success": False, "error": "Invalid event type"}), 400
    record_model_event(model_id, event_type, data.get("metadata"))
    return jsonify({"success": True}), 202


@engagement_bp.route("/api/models/<model_id>/analytics", methods=["GET"])
@login_required
def model_analytics_summary(model_id):
    model = UserModel.query.get_or_404(model_id)
    authorized = model.user_id == current_user.id
    if not authorized and model.organization_id:
        membership = OrganizationMember.query.filter_by(
            organization_id=model.organization_id, user_id=current_user.id
        ).first()
        authorized = bool(membership and membership.role in {"owner", "admin"})
    if not authorized:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    try:
        days = max(1, min(365, int(request.args.get("days", 30))))
    except ValueError:
        return jsonify({"success": False, "error": "Invalid days"}), 400
    since = datetime.utcnow() - timedelta(days=days)
    base = ModelAnalyticsEvent.query.filter(
        ModelAnalyticsEvent.model_id == model_id,
        ModelAnalyticsEvent.created_at >= since,
    )
    totals = dict(
        db.session.query(ModelAnalyticsEvent.event_type, db.func.count(ModelAnalyticsEvent.id))
        .filter(ModelAnalyticsEvent.model_id == model_id, ModelAnalyticsEvent.created_at >= since)
        .group_by(ModelAnalyticsEvent.event_type).all()
    )
    unique_visitors = base.with_entities(
        db.func.count(db.distinct(ModelAnalyticsEvent.visitor_hash))
    ).scalar() or 0
    timeline_rows = (
        db.session.query(
            db.func.date(ModelAnalyticsEvent.created_at),
            ModelAnalyticsEvent.event_type,
            db.func.count(ModelAnalyticsEvent.id),
        )
        .filter(ModelAnalyticsEvent.model_id == model_id, ModelAnalyticsEvent.created_at >= since)
        .group_by(db.func.date(ModelAnalyticsEvent.created_at), ModelAnalyticsEvent.event_type)
        .order_by(db.func.date(ModelAnalyticsEvent.created_at)).all()
    )
    timeline = [
        {"date": str(day), "event_type": event_type, "count": count}
        for day, event_type, count in timeline_rows
    ]
    referrers = [
        {"domain": domain or "direct", "count": count}
        for domain, count in (
            db.session.query(ModelAnalyticsEvent.referrer_domain, db.func.count(ModelAnalyticsEvent.id))
            .filter(ModelAnalyticsEvent.model_id == model_id, ModelAnalyticsEvent.created_at >= since)
            .group_by(ModelAnalyticsEvent.referrer_domain)
            .order_by(db.func.count(ModelAnalyticsEvent.id).desc()).limit(20).all()
        )
    ]
    return jsonify({
        "success": True,
        "period_days": days,
        "totals": totals,
        "unique_visitors": unique_visitors,
        "timeline": timeline,
        "referrers": referrers,
    })


# Event columns exported per model, in a stable order (matches the ANALYTICS
# event types the recorder writes).
_ORG_ANALYTICS_COLUMNS = ["view", "embed_view", "ar_launch", "download", "share", "qr_open"]


def _org_analytics_window(organization_id):
    """Resolve (models, since, days) for an org analytics request, capping the
    requested window to the plan's analytics_retention_days. Returns
    (window, None) on success or (None, error_response) on a bad `days`."""
    try:
        requested = max(1, int(request.args.get("days", 30)))
    except (TypeError, ValueError):
        return None, (jsonify({"success": False, "error": "Invalid days"}), 400)
    retention = plan_limit(current_user, "analytics_retention_days", 365)
    days = min(requested, retention or 365)
    since = datetime.utcnow() - timedelta(days=days)
    models = UserModel.query.filter(
        UserModel.organization_id == organization_id,
        UserModel.deleted_at.is_(None),
    ).all()
    return (models, since, days), None


def _org_analytics_rows(models, since):
    """Per-model aggregated event counts + unique visitors for the given models
    since `since`. Returns a list of {model_id, name, counts, unique_visitors}."""
    model_ids = [model.id for model in models]
    counts_by_model = {mid: {column: 0 for column in _ORG_ANALYTICS_COLUMNS} for mid in model_ids}
    if model_ids:
        for model_id, event_type, count in (
            db.session.query(
                ModelAnalyticsEvent.model_id,
                ModelAnalyticsEvent.event_type,
                db.func.count(ModelAnalyticsEvent.id),
            )
            .filter(
                ModelAnalyticsEvent.model_id.in_(model_ids),
                ModelAnalyticsEvent.created_at >= since,
            )
            .group_by(ModelAnalyticsEvent.model_id, ModelAnalyticsEvent.event_type)
            .all()
        ):
            if event_type in counts_by_model.get(model_id, {}):
                counts_by_model[model_id][event_type] = count
        visitors_by_model = dict(
            db.session.query(
                ModelAnalyticsEvent.model_id,
                db.func.count(db.distinct(ModelAnalyticsEvent.visitor_hash)),
            )
            .filter(
                ModelAnalyticsEvent.model_id.in_(model_ids),
                ModelAnalyticsEvent.created_at >= since,
            )
            .group_by(ModelAnalyticsEvent.model_id)
            .all()
        )
    else:
        visitors_by_model = {}
    return [
        {
            "model_id": model.id,
            "name": model.display_name or model.filename,
            "counts": counts_by_model[model.id],
            "unique_visitors": int(visitors_by_model.get(model.id, 0)),
        }
        for model in models
    ]


@engagement_bp.route("/api/organizations/<int:organization_id>/analytics", methods=["GET"])
@login_required
def organization_analytics_summary(organization_id):
    """Analytics rolled up across every model in an organization. Owner/admin
    only; the requested window is capped to the plan's retention."""
    if not _organization_membership(organization_id, {"owner", "admin"}):
        return jsonify({"success": False, "error": "Organization admin role required"}), 403
    window, error = _org_analytics_window(organization_id)
    if error:
        return error
    models, since, days = window
    rows = _org_analytics_rows(models, since)
    totals = {column: 0 for column in _ORG_ANALYTICS_COLUMNS}
    for row in rows:
        for column, value in row["counts"].items():
            totals[column] += value
    org_unique_visitors = 0
    model_ids = [model.id for model in models]
    if model_ids:
        org_unique_visitors = db.session.query(
            db.func.count(db.distinct(ModelAnalyticsEvent.visitor_hash))
        ).filter(
            ModelAnalyticsEvent.model_id.in_(model_ids),
            ModelAnalyticsEvent.created_at >= since,
        ).scalar() or 0
    return jsonify({
        "success": True,
        "period_days": days,
        "model_count": len(models),
        "totals": totals,
        "unique_visitors": int(org_unique_visitors),
        "models": rows,
    })


@engagement_bp.route("/api/organizations/<int:organization_id>/analytics/export", methods=["GET"])
@login_required
def organization_analytics_export(organization_id):
    """CSV export of per-model event counts across an organization (one row per
    model). Owner/admin only; window capped to the plan's retention."""
    if not _organization_membership(organization_id, {"owner", "admin"}):
        return jsonify({"success": False, "error": "Organization admin role required"}), 403
    window, error = _org_analytics_window(organization_id)
    if error:
        return error
    models, since, days = window
    rows = _org_analytics_rows(models, since)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["model_id", "name", *_ORG_ANALYTICS_COLUMNS, "unique_visitors"])
    for row in rows:
        writer.writerow([
            row["model_id"], row["name"],
            *[row["counts"][column] for column in _ORG_ANALYTICS_COLUMNS],
            row["unique_visitors"],
        ])
    organization = db.session.get(Organization, organization_id)
    filename = f"{organization.slug if organization else 'organization'}-analytics-{days}d.csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
