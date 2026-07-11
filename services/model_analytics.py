"""Privacy-safe product analytics event recording for models."""

import hashlib
import secrets
from urllib.parse import urlparse

from flask import current_app, request, session

from models import ModelAnalyticsEvent, db

ANALYTICS_EVENT_TYPES = {"view", "embed_view", "ar_launch", "download", "share", "qr_open"}


def record_model_event(model_id, event_type, metadata=None):
    """Record coarse product analytics without storing an IP address."""
    if event_type not in ANALYTICS_EVENT_TYPES:
        raise ValueError("Unsupported analytics event")
    analytics_id = session.get("_analytics_id")
    if not analytics_id:
        analytics_id = secrets.token_urlsafe(18)
        session["_analytics_id"] = analytics_id
    salt = current_app.config["SECRET_KEY"] or "analytics"
    visitor_hash = hashlib.sha256(f"{salt}:{analytics_id}".encode()).hexdigest()
    referrer = request.headers.get("Referer", "")
    domain = (urlparse(referrer).hostname or "")[:255] or None
    user_agent = request.headers.get("User-Agent", "").lower()
    device = "mobile" if any(marker in user_agent for marker in ("mobile", "android", "iphone")) else "desktop"
    clean_metadata = {}
    for key, value in (metadata or {}).items():
        if len(clean_metadata) >= 10:
            break
        if isinstance(value, (str, int, float, bool)):
            clean_metadata[str(key)[:50]] = str(value)[:250] if isinstance(value, str) else value
    db.session.add(ModelAnalyticsEvent(
        model_id=model_id,
        event_type=event_type,
        visitor_hash=visitor_hash,
        referrer_domain=domain,
        device_type=device,
        event_metadata=clean_metadata or None,
    ))
    db.session.commit()
