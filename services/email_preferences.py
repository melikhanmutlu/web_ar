"""Per-user opt-outs for non-transactional email, plus the signed one-click
unsubscribe link every such email carries.

Transactional mail (email verification, password reset, payment receipts,
account/security notices) is never gated by these flags.
"""
from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

from config import SITE_URL

SALT = "arvision-email-unsubscribe"

# category -> (User column, label shown in the profile / unsubscribe page)
CATEGORIES = {
    "onboarding": ("email_onboarding", "Onboarding tips"),
    "renewal": ("email_renewal", "Renewal reminders and plan offers"),
    "weekly_report": ("email_weekly_report", "Weekly growth report (admins only)"),
}


def wants(user, category):
    """True unless the user switched this category off."""
    column = CATEGORIES[category][0]
    return getattr(user, column, True) is not False


def set_pref(user, category, enabled):
    setattr(user, CATEGORIES[category][0], bool(enabled))


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def unsubscribe_url(user, category):
    """Absolute, signed, non-expiring link that switches `category` off."""
    token = _serializer().dumps({"uid": user.id, "cat": category})
    return f"{SITE_URL}/unsubscribe/{token}"


def read_unsubscribe_token(token):
    """Return (user_id, category) for a valid token, else None."""
    try:
        payload = _serializer().loads(token)
    except BadSignature:
        return None
    if not isinstance(payload, dict) or payload.get("cat") not in CATEGORIES:
        return None
    uid = payload.get("uid")
    return (uid, payload["cat"]) if isinstance(uid, int) else None
