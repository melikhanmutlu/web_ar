"""Email verification (SEC-04): signed, time-limited tokens + the "is this
user verified" policy used by the abuse-sensitive perks (free AI trials, the
Business trial, referral rewards)."""
import logging

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from services.email import send_email
from services.time_utils import datetime

logger = logging.getLogger(__name__)

SALT = "arvision-email-verify"
MAX_AGE_SECONDS = 48 * 3600

VERIFY_REQUIRED_MESSAGE = (
    "Please verify your email address first - check your inbox, or resend "
    "the link from your profile."
)


def is_verified(user):
    """Admins count as verified; everyone else needs email_verified_at."""
    if user is None:
        return False
    return bool(getattr(user, "is_admin", False) or user.email_verified_at is not None)


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def make_token(user, email):
    return _serializer().dumps({"uid": user.id, "email": email})


def read_token(token, max_age=None):
    """Return (payload, error) where error is None, "expired" or "invalid"."""
    try:
        return _serializer().loads(token, max_age=MAX_AGE_SECONDS if max_age is None else max_age), None
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"


def send_verification(user, email=None):
    """Email a verification link for `email` (default: the user's address).
    Never raises. With SMTP unconfigured the link is logged at INFO so ops can
    verify by hand. Returns True if an email was actually sent."""
    email = email or user.email
    link = url_for("auth.verify_email", token=make_token(user, email), _external=True)
    sent = send_email(
        email,
        "Verify your ARVision email",
        "Confirm this email address for your ARVision account by opening the link below "
        f"(valid for 48 hours):\n\n{link}\n\nIf you didn't request this, ignore this email.",
    )
    if not sent:
        logger.info("[email-verify] email not delivered; verification link for %s: %s", email, link)
    return sent


def mark_verified(user):
    """Set email_verified_at and release first-time referral rewards.
    Caller commits."""
    first_time = user.email_verified_at is None
    user.email_verified_at = datetime.utcnow()
    if first_time:
        from services.referrals import grant_referral_rewards
        grant_referral_rewards(user)
