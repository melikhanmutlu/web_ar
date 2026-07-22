"""Referral program (F3.2): share codes and double-sided AI-credit rewards.

A new user who signs up with a valid ?ref=<code> gets a small credit bonus,
and so does the referrer — up to a monthly cap per referrer (abuse guard).
Self-referral is impossible (the code belongs to an existing user; the new
user has none yet). Credits are granted through the same grant_ai_credits
seam everything else uses.
"""

import os
import secrets

from config import SITE_URL
from models import User, db
from services.credits import grant_ai_credits
from services.time_utils import datetime

REFERRER_CREDITS = int(os.getenv("REFERRAL_REFERRER_CREDITS", 5))
INVITEE_CREDITS = int(os.getenv("REFERRAL_INVITEE_CREDITS", 3))
MONTHLY_REWARD_CAP = int(os.getenv("REFERRAL_MONTHLY_CAP", 20))


def get_or_create_code(user):
    """Return the user's referral code, generating a unique one on first use."""
    if user.referral_code:
        return user.referral_code
    for _ in range(10):
        candidate = secrets.token_urlsafe(6)[:12]
        if not User.query.filter_by(referral_code=candidate).first():
            user.referral_code = candidate
            db.session.commit()
            return candidate
    # Extremely unlikely; fall back to an id-salted code.
    user.referral_code = f"u{user.id}{secrets.token_hex(2)}"
    db.session.commit()
    return user.referral_code


def referral_link(user):
    return f"{SITE_URL}/register?ref={get_or_create_code(user)}"


def referred_count(user):
    return User.query.filter_by(referred_by_id=user.id).count()


def _rewards_this_month(referrer_id, now):
    month_start = datetime(now.year, now.month, 1)
    return User.query.filter(
        User.referred_by_id == referrer_id,
        User.created_at >= month_start,
    ).count()


def apply_referral(new_user, code, now=None):
    """Link `new_user` to the owner of `code` and grant both sides credits
    (referrer only while under the monthly cap). No-op for an unknown code or
    a self-referral. The caller owns the surrounding transaction/commit.
    Returns the referrer User or None."""
    if not code:
        return None
    referrer = User.query.filter_by(referral_code=code).first()
    if referrer is None or referrer.id == new_user.id:
        return None

    now = now or datetime.utcnow()
    new_user.referred_by_id = referrer.id
    grant_ai_credits(new_user, INVITEE_CREDITS)
    # _rewards_this_month counts new_user too (already linked above), so compare
    # against cap+1 — i.e. reward the referrer while they're at/under the cap.
    if _rewards_this_month(referrer.id, now) <= MONTHLY_REWARD_CAP:
        grant_ai_credits(referrer, REFERRER_CREDITS)
    return referrer
