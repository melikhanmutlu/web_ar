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
import threading
from contextlib import contextmanager
from urllib.parse import urlsplit

import requests

from models import WebhookSubscription, db
from services.time_utils import datetime

logger = logging.getLogger(__name__)

# Serializes the pinned-DNS window below across threads (webhook delivery is
# already best-effort/short-timeout, so briefly serializing it process-wide
# is an acceptable trade for correctness -- a per-call monkeypatch of
# socket.getaddrinfo is not safe to run concurrently from multiple threads).
_pin_lock = threading.Lock()


def _resolve_safe_ips(url):
    """Return the resolved IP list if `url` is https and every address is
    public, else None.

    Guards against SSRF: a user could otherwise point a webhook at an internal
    host (169.254.169.254 metadata, 10.x/192.168.x services, 127.0.0.1) and use
    our server as a request-forgery proxy.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError, ValueError):
        return None
    if not infos:
        return None
    addrs = []
    for info in infos:
        addr = info[4][0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return None
        if (
            ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_multicast or ip.is_reserved or ip.is_unspecified
        ):
            return None
        addrs.append(addr)
    return addrs


def is_safe_webhook_url(url):
    """True if `url` is https and resolves only to public addresses."""
    return _resolve_safe_ips(url) is not None


@contextmanager
def _pinned_dns(hostname, ips):
    """Force socket.getaddrinfo() to return exactly the given (pre-validated)
    IPs for `hostname` for the duration of the block.

    Without this, the safety check and the actual request each perform their
    own independent DNS lookup -- a low-TTL or stateful DNS record could
    return a public IP for the check and a private one moments later for the
    real connection (classic SSRF-via-DNS-rebinding), silently defeating the
    check despite validating it "at delivery time".
    """
    real_getaddrinfo = socket.getaddrinfo

    def pinned(host, port, *args, **kwargs):
        if host == hostname:
            return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port))
                    for ip in ips]
        return real_getaddrinfo(host, port, *args, **kwargs)

    with _pin_lock:
        socket.getaddrinfo = pinned
        try:
            yield
        finally:
            socket.getaddrinfo = real_getaddrinfo

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
        # could since have rebound to an internal address. Pin the actual
        # request to these exact validated IPs (see _pinned_dns) so the
        # request itself can't re-resolve to something different a moment
        # later -- otherwise the check and the real connection are two
        # independent DNS lookups, and a low-TTL/stateful record can pass the
        # check with a public IP and serve a private one to the real request.
        hostname = urlsplit(subscription.url).hostname
        safe_ips = _resolve_safe_ips(subscription.url)
        if not safe_ips:
            logger.warning(f"[webhook] skipping delivery to unsafe/private URL: {subscription.url}")
            continue
        body = json.dumps({"event": event_type, "data": payload}).encode()
        signature = hmac.new(subscription.secret.encode(), body, hashlib.sha256).hexdigest()
        try:
            with _pinned_dns(hostname, safe_ips):
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
