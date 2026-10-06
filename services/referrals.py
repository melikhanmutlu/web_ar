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
from services.email_verification import is_verified
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


def _canonical_mailbox(email):
    """Collapse the cheap aliasing tricks (+tag, gmail dots, googlemail) so
    'me+1@gmail.com' and 'm.e@googlemail.com' are recognised as one mailbox."""
    local, _, domain = (email or "").strip().lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def apply_referral(new_user, code, now=None):
    """Link `new_user` to the owner of `code`. No-op for an unknown code or a
    self-referral. Rewards need a verified email: granted immediately here if
    the new user already is, otherwise when they verify (grant_referral_rewards).
    The caller owns the surrounding transaction/commit.
    Returns the referrer User or None."""
    if not code:
        return None
    referrer = User.query.filter_by(referral_code=code).first()
    if referrer is None or referrer.id == new_user.id:
        return None
    # Self-referral through an alias of the referrer's own mailbox.
    if _canonical_mailbox(new_user.email) == _canonical_mailbox(referrer.email):
        return None

    new_user.referred_by_id = referrer.id
    if is_verified(new_user):
        grant_referral_rewards(new_user, now)
    return referrer


def grant_referral_rewards(new_user, now=None):
    """Grant both sides their credits for a referred, now-verified user. The
    referrer is rewarded only while under the monthly cap and only if their own
    email is verified; otherwise that side is skipped (no error). Caller commits."""
    if not new_user.referred_by_id:
        return
    referrer = db.session.get(User, new_user.referred_by_id)
    if referrer is None:
        return
    now = now or datetime.utcnow()
    # _rewards_this_month counts new_user too (already linked), so compare
    # against cap+1 - i.e. reward while the referrer is at/under the cap. Past
    # the cap NEITHER side is rewarded: capping only the referrer would still
    # let one referrer mint 3 free credits per throwaway account.
    if _rewards_this_month(referrer.id, now) > MONTHLY_REWARD_CAP:
        return
    grant_ai_credits(new_user, INVITEE_CREDITS)
    if is_verified(referrer):
        grant_ai_credits(referrer, REFERRER_CREDITS)
