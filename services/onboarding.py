"""In-product onboarding checklist (F3.4): the 4 activation steps, derived
live from existing data (no new tables). Returns None once every step is done
so the caller can hide the widget."""

from sqlalchemy import or_

from models import AIGenerationJob, ModelAnalyticsEvent, ModelShareLink, UserModel, db


def checklist_state(user_id):
    """List of {key, label, done} for the 4 steps, or None when all complete."""
    live = UserModel.deleted_at.is_(None)

    uploaded = db.session.query(
        UserModel.query.filter(UserModel.user_id == user_id, live).exists()
    ).scalar()

    opened_ar = db.session.query(
        ModelAnalyticsEvent.query.join(
            UserModel, ModelAnalyticsEvent.model_id == UserModel.id
        ).filter(
            UserModel.user_id == user_id,
            ModelAnalyticsEvent.event_type == "ar_launch",
        ).exists()
    ).scalar()

    shared = db.session.query(
        UserModel.query.outerjoin(
            ModelShareLink, ModelShareLink.model_id == UserModel.id
        ).filter(
            UserModel.user_id == user_id, live,
            or_(
                UserModel.share_count > 0,
                UserModel.visibility == "public",
                ModelShareLink.id.isnot(None),
            ),
        ).exists()
    ).scalar()

    tried_ai = db.session.query(
        AIGenerationJob.query.filter(AIGenerationJob.user_id == user_id).exists()
    ).scalar() or db.session.query(
        UserModel.query.filter(
            UserModel.user_id == user_id, live,
            UserModel.source.isnot(None), UserModel.source.like("ai%"),
        ).exists()
    ).scalar()

    steps = [
        {"key": "upload", "label": "Upload your first model", "done": bool(uploaded)},
        {"key": "ar", "label": "Open it in AR on your phone", "done": bool(opened_ar)},
        {"key": "share", "label": "Share the AR link", "done": bool(shared)},
        {"key": "ai", "label": "Try AI 3D generation", "done": bool(tried_ai)},
    ]
    if all(step["done"] for step in steps):
        return None
    return steps
