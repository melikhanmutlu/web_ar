"""Self-service password reset (UIP-02): signed, time-limited, single-use tokens.

The token embeds the user's current ``session_version``. ``User.set_password``
bumps it, so a link dies the moment the password changes by any route (the reset
itself, the profile form, an admin reset) and can't be replayed. A separate salt
keeps these tokens from being accepted as email-verification tokens."""
import logging

from flask import current_app, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from services.email import send_email

logger = logging.getLogger(__name__)

SALT = "arvision-password-reset"
MAX_AGE_SECONDS = 3600


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=SALT)


def make_token(user):
    return _serializer().dumps({"uid": user.id, "sv": user.session_version or 0})


def read_token(token):
    """Return (payload, error); error is None, "expired" or "invalid"."""
    try:
        return _serializer().loads(token, max_age=MAX_AGE_SECONDS), None
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"


def user_for_token(token):
    """Return (user, error). The user is only returned while the token's
    session_version still matches (i.e. the password hasn't changed since)."""
    from models import db, User

    payload, error = read_token(token)
    if error:
        return None, error
    user = db.session.get(User, payload.get("uid")) if isinstance(payload, dict) else None
    if user is None or not user.is_active or payload.get("sv") != (user.session_version or 0):
        return None, "invalid"
    return user, None


def send_reset_link(user):
    """Email a reset link. Never raises; with SMTP unconfigured the link is
    logged at INFO so ops can hand it over. Returns True if an email was sent."""
    link = url_for("auth.reset_password", token=make_token(user), _external=True)
    sent = send_email(
        user.email,
        "Reset your ARVision password",
        "We received a request to reset the password for your ARVision account. "
        f"Open the link below to choose a new one (valid for 1 hour):\n\n{link}\n\n"
        "If you didn't ask for this, you can ignore this email - your password won't change.",
    )
    if not sent:
        logger.info("[password-reset] email not delivered; reset link for %s: %s", user.email, link)
    return sent
