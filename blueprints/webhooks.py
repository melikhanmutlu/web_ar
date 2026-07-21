"""User-managed webhook subscriptions for conversion/AI generation
completion events. See services/webhooks.py for delivery."""
import secrets
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models import WebhookSubscription, db
from services import WEBHOOK_EVENT_TYPES
from services.plans import plan_allows
from services.webhooks import is_safe_webhook_url

webhooks_bp = Blueprint("webhooks", __name__)


@webhooks_bp.route("/api/webhooks", methods=["GET", "POST"])
@login_required
def webhooks():
    if request.method == "GET":
        subscriptions = WebhookSubscription.query.filter_by(user_id=current_user.id).all()
        return jsonify({"success": True, "webhooks": [s.to_dict() for s in subscriptions]})

    if not plan_allows(current_user, "webhooks"):
        return jsonify({
            "success": False,
            "error": "Webhooks require a Business plan.",
        }), 403
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return jsonify({"success": False, "error": "url must be an https:// URL"}), 400
    if not is_safe_webhook_url(url):
        return jsonify({
            "success": False,
            "error": "url must resolve to a public host (private/internal addresses are not allowed)",
        }), 400
    event_types = data.get("event_types")
    if not isinstance(event_types, list) or not event_types:
        return jsonify({"success": False, "error": "event_types must be a non-empty list"}), 400
    invalid = set(event_types) - WEBHOOK_EVENT_TYPES
    if invalid:
        return jsonify({"success": False, "error": f"Invalid event_types: {sorted(invalid)}"}), 400

    subscription = WebhookSubscription(
        user_id=current_user.id,
        url=url[:500],
        secret=secrets.token_urlsafe(32),
        event_types=",".join(sorted(set(event_types))),
    )
    db.session.add(subscription)
    db.session.commit()
    body = subscription.to_dict()
    body["secret"] = subscription.secret  # only ever shown once, at creation
    return jsonify({"success": True, "webhook": body}), 201


@webhooks_bp.route("/api/webhooks/<int:webhook_id>", methods=["DELETE"])
@login_required
def delete_webhook(webhook_id):
    subscription = WebhookSubscription.query.filter_by(
        id=webhook_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(subscription)
    db.session.commit()
    return jsonify({"success": True})
