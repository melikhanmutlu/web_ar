"""B2B signal mining (F3.6): a daily sweep that turns product-usage patterns
into sales-ready leads.

Signals detected:
  - domain_cluster: 3+ users share a non-free email domain (a company signing
    up organically).
  - org_owner: someone created an organization (team intent).
  - high_ar_views: a single model crossed an AR-view threshold (real traction).

Each surfaced account becomes one SalesLead(source='signal:<kind>'), deduped by
a stable (email, source) pair so re-running the sweep never duplicates, and the
admins get one notification per genuinely new lead. Free/consumer email
domains are excluded from the domain-cluster signal.
"""

import logging
from collections import defaultdict

from sqlalchemy import func

from models import (
    ModelAnalyticsEvent, Organization, SalesLead, User, UserModel, db,
)
from services.time_utils import datetime

logger = logging.getLogger(__name__)

DOMAIN_CLUSTER_MIN = 3
HIGH_AR_VIEWS_MIN = 100

FREE_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "proton.me", "protonmail.com", "aol.com", "yandex.com", "gmx.com",
    "live.com", "msn.com", "mail.com", "hey.com", "me.com",
}


def _domain(email):
    return email.rsplit("@", 1)[-1].lower() if email and "@" in email else ""


def _lead_exists(email, source):
    return SalesLead.query.filter_by(email=email, source=source).first() is not None


def _create_lead(email, source, company=None, message=None, user_id=None):
    """Create a deduped signal lead. Returns the lead if newly created, else
    None. Caller commits."""
    if not email or _lead_exists(email, source):
        return None
    lead = SalesLead(
        email=email, company=company, message=message,
        source=source, user_id=user_id, status="new",
    )
    db.session.add(lead)
    return lead


def _domain_cluster_leads():
    rows = (
        db.session.query(
            func.lower(func.substr(User.email, func.instr(User.email, "@") + 1)),
            func.count(User.id),
        )
        .filter(User.email.isnot(None), User.is_admin.is_(False))
        .group_by(func.lower(func.substr(User.email, func.instr(User.email, "@") + 1)))
        .having(func.count(User.id) >= DOMAIN_CLUSTER_MIN)
        .all()
    )
    leads = []
    for domain, count in rows:
        if not domain or domain in FREE_EMAIL_DOMAINS:
            continue
        # Represent the cluster by its earliest-registered member.
        rep = (
            User.query.filter(func.lower(User.email).like(f"%@{domain}"))
            .order_by(User.created_at.asc())
            .first()
        )
        if rep is None:
            continue
        lead = _create_lead(
            rep.email, "signal:domain_cluster", company=domain,
            message=f"{count} users share the domain {domain}.", user_id=rep.id,
        )
        if lead:
            leads.append(lead)
    return leads


def _org_owner_leads():
    leads = []
    orgs = Organization.query.all()
    for org in orgs:
        owner = db.session.get(User, org.created_by)
        if owner is None or not owner.email or owner.is_admin:
            continue
        lead = _create_lead(
            owner.email, "signal:org_owner", company=org.name,
            message=f"Created organization '{org.name}'.", user_id=owner.id,
        )
        if lead:
            leads.append(lead)
    return leads


def _high_ar_view_leads():
    rows = (
        db.session.query(
            UserModel.user_id, func.count(ModelAnalyticsEvent.id)
        )
        .join(ModelAnalyticsEvent, ModelAnalyticsEvent.model_id == UserModel.id)
        .filter(
            ModelAnalyticsEvent.event_type == "ar_launch",
            UserModel.user_id.isnot(None),
        )
        .group_by(UserModel.id, UserModel.user_id)
        .having(func.count(ModelAnalyticsEvent.id) >= HIGH_AR_VIEWS_MIN)
        .all()
    )
    seen_users = set()
    leads = []
    for user_id, count in rows:
        if user_id in seen_users:
            continue
        seen_users.add(user_id)
        user = db.session.get(User, user_id)
        if user is None or not user.email or user.is_admin:
            continue
        lead = _create_lead(
            user.email, "signal:high_ar_views",
            message=f"A model reached {count}+ AR views.", user_id=user.id,
        )
        if lead:
            leads.append(lead)
    return leads


def run_signal_mining(now=None):
    """One sweep across all signals. Returns the number of new leads created.
    Idempotent via the (email, source) dedupe."""
    now = now or datetime.utcnow()
    new_leads = (
        _domain_cluster_leads() + _org_owner_leads() + _high_ar_view_leads()
    )
    if not new_leads:
        return 0
    db.session.commit()
    _notify_admins(new_leads)
    logger.info(f"Signal mining created {len(new_leads)} sales lead(s)")
    return len(new_leads)


def _notify_admins(leads):
    try:
        from services import send_email
        admins = [a.email for a in User.query.filter_by(is_admin=True).all() if a.email]
        if not admins:
            return
        body_lines = ["New sales signals to follow up:", ""]
        for lead in leads:
            body_lines.append(f"- [{lead.source}] {lead.email} — {lead.message or ''}")
        body = "\n".join(body_lines)
        for email in admins:
            send_email(email, f"{len(leads)} new sales signal(s)", body)
    except Exception:
        pass
