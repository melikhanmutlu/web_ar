"""Fire-and-forget webhook delivery for conversion/AI generation completion
events. No retry queue: a subscriber's endpoint is expected to be reachable
promptly, and this must never block or fail the request that triggered it.
"""
import hashlib
import hmac
import json
import logging

import requests

from models import WebhookSubscription, db
from services.time_utils import datetime

logger = logging.getLogger(__name__)

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
