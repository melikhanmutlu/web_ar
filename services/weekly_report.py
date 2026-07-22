"""Weekly business report email (F3.5).

Builds a plain-text digest from the same growth_metrics query layer the admin
dashboard uses, adds the week's top models and orgs, and emails every admin.
Deduped through LifecycleEmail keyed on the ISO week, so it goes out at most
once per calendar week however often the worker calls it.
"""

import logging

from sqlalchemy import func

from models import Organization, User, UserModel, db
from services import send_email
from services.growth_metrics import collect_growth_metrics
from services.time_utils import datetime
from site_settings import get_setting, set_setting

logger = logging.getLogger(__name__)

# SiteSetting key holding the ISO week ("YYYY-Www") of the last sent report —
# the per-week dedupe sentinel (LifecycleEmail can't be used: its user_id is a
# NOT NULL FK, and this email isn't tied to any single user).
LAST_SENT_SETTING = "weekly_report_last_week"
# Only send on Mondays (worker calls daily; this keeps it to one day/week even
# before the dedupe kicks in).
REPORT_WEEKDAY = 0  # Monday


def _top_models(limit=5):
    return (
        UserModel.query.filter(UserModel.deleted_at.is_(None))
        .order_by(UserModel.view_count.desc().nullslast())
        .limit(limit)
        .all()
    )


def _top_orgs(limit=5):
    rows = (
        db.session.query(Organization.name, func.count(UserModel.id))
        .outerjoin(UserModel, UserModel.organization_id == Organization.id)
        .group_by(Organization.id)
        .order_by(func.count(UserModel.id).desc())
        .limit(limit)
        .all()
    )
    return rows


def _build_body(metrics, now):
    m = metrics
    lines = [
        f"ARVision weekly report — week of {now.date().isoformat()}",
        "",
        f"Signups: {m['signups']['d7']} (7d) / {m['signups']['d30']} (30d)",
        f"Active subscribers: {m['funnel']['paid']}  |  MRR: {m['mrr']}",
        f"Plan breakdown: {m['plan_breakdown'] or '—'}",
        (
            f"Renewal rate (30d): "
            + (f"{round(m['renewal']['rate'] * 100, 1)}%"
               if m['renewal']['rate'] is not None else "n/a")
            + f" ({m['renewal']['renewed']}/{m['renewal']['ended']})"
        ),
        f"AI generations (30d): {m['ai_generations_30d']}  |  Credits sold (30d): {m['credits_sold_30d']}",
        "",
        "Activation funnel (all-time):",
        f"  registered {m['funnel']['registered']} -> uploaded {m['funnel']['uploaded']} "
        f"-> shared {m['funnel']['shared']} -> paid {m['funnel']['paid']}",
        "",
        "Top models by views:",
    ]
    top = _top_models()
    if top:
        for model in top:
            name = model.display_name or model.source_filename or model.id
            lines.append(f"  {model.view_count or 0} views — {name}")
    else:
        lines.append("  (none yet)")
    lines.append("")
    lines.append("Top orgs by model count:")
    orgs = _top_orgs()
    if orgs:
        for name, count in orgs:
            lines.append(f"  {count} models — {name}")
    else:
        lines.append("  (none yet)")
    return "\n".join(lines)


def _week_key(now):
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def send_weekly_report(now=None, force=False):
    """Email the weekly report to all admins. No-op unless it's the report
    weekday (or force=True) and it hasn't already gone out this ISO week.
    Returns True if a report was sent."""
    now = now or datetime.utcnow()
    if not force and now.weekday() != REPORT_WEEKDAY:
        return False
    week_key = _week_key(now)
    if get_setting(LAST_SENT_SETTING) == week_key:
        return False

    admins = User.query.filter_by(is_admin=True).all()
    recipients = [a.email for a in admins if a.email]
    if not recipients:
        return False

    body = _build_body(collect_growth_metrics(now), now)
    delivered = False
    for email in recipients:
        if send_email(email, "ARVision — your weekly growth report", body):
            delivered = True

    if delivered:
        set_setting(LAST_SENT_SETTING, week_key)
    return delivered
