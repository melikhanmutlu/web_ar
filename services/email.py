"""Best-effort email notifications (conversion completed, share link
created, org invite). Mirrors services/webhooks.py's philosophy: delivery
failures are logged and swallowed, never raised, so a broken/unconfigured
SMTP setup can't break the flow that triggers a notification."""
import logging
import re
import smtplib
from email.message import EmailMessage

from flask import current_app, render_template
from markupsafe import Markup, escape

from config import SITE_URL

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"']+")


def _linkify(line):
    """HTML-escape one line of text and turn bare URLs into links."""
    out, last = [], 0
    for m in _URL_RE.finditer(line):
        url = m.group(0).rstrip(".,;:)")
        out.append(escape(line[last:m.start()]))
        out.append(Markup('<a href="{0}">{0}</a>').format(url))
        last = m.start() + len(url)
    out.append(escape(line[last:]))
    return Markup("").join(out)


def _paragraphs(body_text):
    """Plain text -> list of Markup paragraphs (blank-line separated, single
    newlines kept as <br>). Wording is untouched; this only adds markup."""
    paragraphs = []
    for block in re.split(r"\n\s*\n", body_text.strip()):
        lines = [_linkify(line) for line in block.split("\n")]
        paragraphs.append(Markup("<br>").join(lines))
    return paragraphs


def render_html(subject, body_text, unsubscribe_url=None):
    """HTML alternative for a plain-text email (templates/email/message.html)."""
    return render_template(
        "email/message.html", subject=subject, paragraphs=_paragraphs(body_text),
        unsubscribe_url=unsubscribe_url, site_url=SITE_URL,
    )


def send_email(to_email, subject, body_text, unsubscribe_url=None):
    """Send a multipart (plain text + HTML) email. No-op (returns False) when
    EMAIL_NOTIFICATIONS_ENABLED is false (e.g. SMTP_HOST unset, the
    dev/test default) or `to_email` is empty.

    Non-transactional mail passes `unsubscribe_url` (services/email_preferences):
    it is added to the footer, and as RFC 2369 / 8058 List-Unsubscribe headers
    so mail clients can offer one-click unsubscribe."""
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
        text = body_text
        if unsubscribe_url:
            text = f"{body_text}\n\n--\nUnsubscribe from emails like this: {unsubscribe_url}"
            message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        message.set_content(text)
        try:
            message.add_alternative(render_html(subject, body_text, unsubscribe_url), subtype="html")
        except Exception as e:  # a template problem must not lose the email
            logger.warning(f"[email] HTML rendering failed, sending plain text only: {e}")
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
