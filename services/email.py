"""Best-effort email notifications (conversion completed, share link
created, org invite). Mirrors services/webhooks.py's philosophy: delivery
failures are logged and swallowed, never raised, so a broken/unconfigured
SMTP setup can't break the flow that triggers a notification."""
import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

logger = logging.getLogger(__name__)


def send_email(to_email, subject, body_text):
    """Send a plain-text email. No-op (returns False) when
    EMAIL_NOTIFICATIONS_ENABLED is false (e.g. SMTP_HOST unset, the
    dev/test default) or `to_email` is empty."""
    if not to_email or not current_app.config.get("EMAIL_NOTIFICATIONS_ENABLED"):
        return False
    try:
        # Build inside the try: a CR/LF-bearing subject/recipient makes
        # EmailMessage raise, and the "never raises, just returns False"
        # contract must hold for that too.
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = current_app.config["SMTP_FROM_EMAIL"]
        message["To"] = to_email
        message.set_content(body_text)
        with smtplib.SMTP(
            current_app.config["SMTP_HOST"], current_app.config["SMTP_PORT"], timeout=10
        ) as smtp:
            if current_app.config.get("SMTP_USE_TLS"):
                smtp.starttls()
            if current_app.config.get("SMTP_USERNAME"):
                smtp.login(current_app.config["SMTP_USERNAME"], current_app.config["SMTP_PASSWORD"])
            smtp.send_message(message)
        return True
    except Exception as e:
        logger.warning(f"[email] delivery to {to_email} failed: {e}")
        return False
