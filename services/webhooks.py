"""Fire-and-forget webhook delivery for conversion/AI generation completion
events. No retry queue: a subscriber's endpoint is expected to be reachable
promptly, and this must never block or fail the request that triggered it.
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
from urllib.parse import urlsplit

import requests

from models import WebhookSubscription, db
from services.time_utils import datetime

logger = logging.getLogger(__name__)


def is_safe_webhook_url(url):
    """Reject anything that isn't an https URL resolving to a public IP.

    Guards against SSRF: a user could otherwise point a webhook at an internal
    host (169.254.169.254 metadata, 10.x/192.168.x services, 127.0.0.1) and use
    our server as a request-forgery proxy. Resolved at delivery time too, so a
    hostname that later rebinds to a private IP is still blocked.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    if not infos:
        return False
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return False
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            return False
    return True

WEBHOOK_EVENT_TYPES = {
    "conversion.completed",
    "conversion.failed",
    "ai_generation.completed",
    "ai_generation.failed",
}

_REQUEST_TIMEOUT_SECONDS = 5


def dispatch_webhook_event(event_type, user_id, payload):
    """Best-effort POST to every active subscription of `user_id` that
    subscribes to `event_type`. Never raises -- delivery failures are logged
    and otherwise swallowed so a broken subscriber endpoint can't break the
    conversion/generation flow that triggers this."""
    if not user_id or event_type not in WEBHOOK_EVENT_TYPES:
        return
    subscriptions = WebhookSubscription.query.filter_by(
        user_id=user_id, is_active=True
    ).all()
    for subscription in subscriptions:
        if not subscription.subscribes_to(event_type):
            continue
        # Re-check at delivery time: a hostname that passed at registration
        # could since have rebound to an internal address.
        if not is_safe_webhook_url(subscription.url):
            logger.warning(f"[webhook] skipping delivery to unsafe/private URL: {subscription.url}")
            continue
        body = json.dumps({"event": event_type, "data": payload}).encode()
        signature = hmac.new(subscription.secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            response = requests.post(
                subscription.url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-ARVision-Event": event_type,
                    "X-ARVision-Signature": f"sha256={signature}",
                },
                timeout=_REQUEST_TIMEOUT_SECONDS,
            )
            subscription.last_status_code = response.status_code
        except requests.RequestException as e:
            logger.warning(f"[webhook] delivery to {subscription.url} failed: {e}")
            subscription.last_status_code = None
        subscription.last_triggered_at = datetime.utcnow()
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
