"""Renewal-reminder and win-back lifecycle emails (worker-driven).

run_renewal_sweep() is called from the worker's hourly maintenance block,
right after expire_stale_plans():

- T-7 / T-1 reminders: a paid plan approaching plan_expires_at gets one
  "renew soon" email per window. The windows are disjoint ((now+1d, now+7d]
  and (now, now+1d]) so a single sweep never stacks both on the same user.
- T+3 win-back: a payer whose plan already lapsed back to Free (found via
  their latest paid Payment.period_end, since expire_stale_plans clears
  plan_expires_at) gets one "come back" email a few days later.

Idempotency lives in LifecycleEmail's (user_id, kind, dedupe_key) uniqueness:
the dedupe_key is the expiry instant (or period_end) being reminded about, so
a renewal moves the key forward and re-arms the same kind for the next period.
A row is only written when SMTP delivery actually succeeded — a transient
failure (or unconfigured SMTP) is retried by the next sweep instead of being
silently marked done.
"""

import logging
from datetime import timedelta

from sqlalchemy.exc import IntegrityError

from config import SITE_URL
from models import LifecycleEmail, Payment, User, db
from services import send_email
from services.plans import DEFAULT_PLAN, get_plan_config
from services.time_utils import datetime

logger = logging.getLogger(__name__)

# (kind, window_start_days, window_end_days): expiry in (now+start, now+end].
RENEWAL_REMINDERS = (
    ("renewal_t7", 1, 7),
    ("renewal_t1", 0, 1),
)
WINBACK_KIND = "winback_t3"
WINBACK_AFTER_DAYS = 3
# Don't win-back ancient churn (e.g. on the first deploy of this sweep).
WINBACK_MAX_AGE_DAYS = 30

_BILLING_URL = f"{SITE_URL}/billing"


def _send_once(user, kind, dedupe_key, subject, body):
    """Send one lifecycle email unless the same (kind, dedupe_key) already
    went out to this user. Returns True when an email was actually sent."""
    already = LifecycleEmail.query.filter_by(
        user_id=user.id, kind=kind, dedupe_key=dedupe_key
    ).first()
    if already is not None:
        return False
    if not send_email(user.email, subject, body):
        return False
    db.session.add(LifecycleEmail(user_id=user.id, kind=kind, dedupe_key=dedupe_key))
    try:
        db.session.commit()
    except IntegrityError:
        # Two sweeps racing (multiple workers): the other one won, fine.
        db.session.rollback()
    return True


def _remind_expiring_plans(now):
    sent = 0
    for kind, start_days, end_days in RENEWAL_REMINDERS:
        users = User.query.filter(
            User.plan != DEFAULT_PLAN,
            User.plan_expires_at.isnot(None),
            User.plan_expires_at > now + timedelta(days=start_days),
            User.plan_expires_at <= now + timedelta(days=end_days),
        ).all()
        for user in users:
            if not user.email:
                continue
            display = get_plan_config(user.plan).get("display_name", user.plan)
            expires_on = user.plan_expires_at.date().isoformat()
            if kind == "renewal_t1":
                when = "tomorrow"
            else:
                days_left = max(2, (user.plan_expires_at - now).days)
                when = f"in {days_left} days"
            if _send_once(
                user, kind, user.plan_expires_at.isoformat(),
                f"Your ARVision {display} plan expires {when}",
                f"Your {display} plan is active until {expires_on}. Renew from "
                f"your billing page to keep your paid features without "
                f"interruption:\n\n{_BILLING_URL}\n\n"
                f"If you let it lapse, your account simply drops back to the "
                f"Free plan — your models stay safe.",
            ):
                sent += 1
    return sent


def _winback_lapsed_payers(now):
    """Email payers whose plan lapsed WINBACK_AFTER_DAYS ago. Found through
    their latest paid Payment.period_end: expire_stale_plans() has already
    cleared plan_expires_at by the time this fires, so the payment row is the
    only durable record of when the paid period actually ended."""
    newest_end = (now - timedelta(days=WINBACK_AFTER_DAYS)).date()
    oldest_end = (now - timedelta(days=WINBACK_MAX_AGE_DAYS)).date()
    payments = Payment.query.filter(
        Payment.status == "paid",
        Payment.user_id.isnot(None),
        Payment.period_end.isnot(None),
        Payment.period_end <= newest_end,
        Payment.period_end > oldest_end,
    ).all()

    latest_by_user = {}
    for payment in payments:
        best = latest_by_user.get(payment.user_id)
        if best is None or payment.period_end > best.period_end:
            latest_by_user[payment.user_id] = payment

    sent = 0
    for user_id, payment in latest_by_user.items():
        user = db.session.get(User, user_id)
        # Skip anyone who renewed (back on a paid plan) or was re-granted.
        if (
            user is None
            or not user.email
            or user.plan != DEFAULT_PLAN
            or user.plan_expires_at is not None
        ):
            continue
        display = get_plan_config(payment.plan).get("display_name", payment.plan)
        if _send_once(
            user, WINBACK_KIND, payment.period_end.isoformat(),
            f"Your ARVision {display} features are one click away",
            f"Your {display} plan ended on {payment.period_end.isoformat()} and "
            f"your account is on the Free plan now. Everything you built is "
            f"still here — renew any time to pick up where you left off:"
            f"\n\n{_BILLING_URL}",
        ):
            sent += 1
    return sent


def run_renewal_sweep(now=None):
    """One pass of reminder + win-back emails. Safe to call as often as the
    worker likes; dedupe makes repeats free. Returns how many emails went out."""
    now = now or datetime.utcnow()
    sent = _remind_expiring_plans(now) + _winback_lapsed_payers(now)
    if sent:
        logger.info(f"Lifecycle sweep sent {sent} email(s)")
    return sent
