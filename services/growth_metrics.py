"""Business-metrics query layer for the admin growth dashboard (and, later,
the weekly report email): signup trend, activation funnel, active-subscriber
breakdown, MRR, 30-day renewal rate, and AI/credit usage.

Read-only aggregates; every figure is derived live from existing tables so
there is nothing to backfill or keep in sync.
"""

from collections import Counter
from datetime import timedelta

from sqlalchemy import func, or_

from models import AIGenerationJob, ModelShareLink, Payment, User, UserModel, db
from services.plans import DEFAULT_PLAN, get_plan_config
from services.time_utils import datetime


def _monthly_price(plan):
    cfg = get_plan_config(plan)
    price = cfg.get("price") or 0
    return price / 12 if cfg.get("billing_period") == "yearly" else price


def _active_paid_users(now):
    """Non-admin users currently on a paid plan (unexpired or admin-granted
    with no expiry)."""
    return User.query.filter(
        User.plan != DEFAULT_PLAN,
        User.is_admin.is_(False),
        or_(User.plan_expires_at.is_(None), User.plan_expires_at > now),
    ).all()


def collect_growth_metrics(now=None):
    now = now or datetime.utcnow()

    # --- Signups ---------------------------------------------------------
    signups = {
        "d7": User.query.filter(User.created_at >= now - timedelta(days=7)).count(),
        "d30": User.query.filter(User.created_at >= now - timedelta(days=30)).count(),
    }

    # --- Activation funnel (all-time, per user) --------------------------
    registered = db.session.query(func.count(User.id)).scalar() or 0
    uploaded = (
        db.session.query(func.count(func.distinct(UserModel.user_id)))
        .filter(UserModel.user_id.isnot(None))
        .scalar()
        or 0
    )
    # "Shared" = any sharing surface was used: a share link, a public listing,
    # or the share action on the viewer (share_count).
    shared = (
        db.session.query(func.count(func.distinct(UserModel.user_id)))
        .outerjoin(ModelShareLink, ModelShareLink.model_id == UserModel.id)
        .filter(
            UserModel.user_id.isnot(None),
            or_(
                UserModel.share_count > 0,
                UserModel.visibility == "public",
                ModelShareLink.id.isnot(None),
            ),
        )
        .scalar()
        or 0
    )

    # --- Subscribers + MRR -----------------------------------------------
    paid_users = _active_paid_users(now)
    plan_breakdown = dict(Counter(u.plan for u in paid_users))
    mrr = round(sum(_monthly_price(u.plan) for u in paid_users), 2)

    funnel = {
        "registered": registered,
        "uploaded": uploaded,
        "shared": shared,
        "paid": len(paid_users),
    }

    # --- Renewal rate: paid periods that ended in the last 30 days -------
    window_start = (now - timedelta(days=30)).date()
    ended = Payment.query.filter(
        Payment.status == "paid",
        Payment.kind == "plan",
        Payment.user_id.isnot(None),
        Payment.period_end.isnot(None),
        Payment.period_end >= window_start,
        Payment.period_end < now.date(),
    ).all()
    ended_users = {p.user_id for p in ended}
    paid_ids = {u.id for u in paid_users}
    renewed = len(ended_users & paid_ids)
    renewal = {
        "ended": len(ended_users),
        "renewed": renewed,
        "rate": round(renewed / len(ended_users), 3) if ended_users else None,
    }

    # --- AI / credit usage (last 30 days) --------------------------------
    ai_generations_30d = AIGenerationJob.query.filter(
        AIGenerationJob.created_at >= now - timedelta(days=30)
    ).count()
    credits_sold_30d = (
        db.session.query(func.coalesce(func.sum(Payment.credits), 0))
        .filter(
            Payment.status == "paid",
            Payment.kind == "topup",
            Payment.created_at >= now - timedelta(days=30),
        )
        .scalar()
        or 0
    )

    return {
        "signups": signups,
        "funnel": funnel,
        "plan_breakdown": plan_breakdown,
        "mrr": mrr,
        "renewal": renewal,
        "ai_generations_30d": ai_generations_30d,
        "credits_sold_30d": credits_sold_30d,
    }
