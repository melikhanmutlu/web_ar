"""Like/save/share/download engagement counters and per-model analytics."""

import uuid
from datetime import timedelta

from flask import Blueprint, jsonify, request, session
from flask_login import current_user, login_required

from services.time_utils import datetime
from models import ModelAnalyticsEvent, ModelLike, ModelSave, OrganizationMember, UserModel, db
from services.model_analytics import ANALYTICS_EVENT_TYPES, record_model_event
from services.model_permissions import check_model_view_allowed, get_live_model

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
