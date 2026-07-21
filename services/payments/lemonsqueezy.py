"""Lemon Squeezy adapter (Merchant of Record — global cards, tax handled by
LS, real recurring subscriptions).

Flow (https://docs.lemonsqueezy.com/api):
1. create_checkout() POSTs a JSON:API checkout to /v1/checkouts with the
   store + variant relationship and our Payment.provider_ref stashed in
   checkout_data.custom.payment_ref. LS returns a hosted-checkout URL the
   buyer is redirected to (card data never touches our server).
2. LS webhooks POST JSON with an X-Signature header =
   HMAC-SHA256-hexdigest(raw body, signing secret). verify_webhook()
   recomputes and compares it. custom.payment_ref survives into every
   subscription event, which is how a renewal finds its original Payment.

Which plan/pack maps to which LS variant is config (LEMONSQUEEZY_VARIANTS
JSON): plans by slug ("pro"), credit packs by "topup:<credits>" ("topup:50").
"""

import hashlib
import hmac
import json

import requests

import config
from services.payments.base import CallbackResult, CheckoutSession, PaymentProvider

_CHECKOUTS_URL = "https://api.lemonsqueezy.com/v1/checkouts"
_TIMEOUT_SECONDS = 20


def _variant_id(payment):
    """LS variant for what this Payment sells, or None if unmapped."""
    try:
        variants = json.loads(config.LEMONSQUEEZY_VARIANTS or "{}")
    except ValueError:
        return None
    key = f"topup:{payment.credits}" if payment.kind == "topup" else payment.plan
    return variants.get(key)


class LemonSqueezyProvider(PaymentProvider):
    name = "lemonsqueezy"

    def is_configured(self):
        return bool(
            config.LEMONSQUEEZY_API_KEY
            and config.LEMONSQUEEZY_STORE_ID
            and config.LEMONSQUEEZY_SIGNING_SECRET
        )

    def create_checkout(self, payment, user, *, ok_url, fail_url, client_ip,
                        email, item_name):
        if not self.is_configured():
            raise RuntimeError("Lemon Squeezy is not configured.")
        variant = _variant_id(payment)
        if variant is None:
            raise RuntimeError(
                "No Lemon Squeezy variant mapped for this product "
                "(LEMONSQUEEZY_VARIANTS)."
            )
        body = {
            "data": {
                "type": "checkouts",
                "attributes": {
                    "product_options": {"redirect_url": ok_url},
                    "checkout_data": {
                        "email": email or "",
                        # Custom values must be strings (LS requirement).
                        "custom": {"payment_ref": str(payment.provider_ref)},
                    },
                },
                "relationships": {
                    "store": {"data": {"type": "stores",
                                        "id": str(config.LEMONSQUEEZY_STORE_ID)}},
                    "variant": {"data": {"type": "variants", "id": str(variant)}},
                },
            }
        }
        headers = {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
            "Authorization": f"Bearer {config.LEMONSQUEEZY_API_KEY}",
        }
        try:
            response = requests.post(
                _CHECKOUTS_URL, json=body, headers=headers, timeout=_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"Lemon Squeezy checkout failed: {exc}") from exc
        url = (payload.get("data", {}).get("attributes", {}) or {}).get("url")
        if not url:
            raise RuntimeError("Lemon Squeezy returned no checkout URL.")
        return CheckoutSession(redirect_url=url)

    def verify_webhook(self, raw_body, signature):
        """True when `signature` (X-Signature header) matches the HMAC of the
        raw request body under the signing secret."""
        if not signature or not config.LEMONSQUEEZY_SIGNING_SECRET:
            return False
        expected = hmac.new(
            config.LEMONSQUEEZY_SIGNING_SECRET.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def verify_callback(self, form):
        # LS uses the JSON webhook above, not a form callback; anything posted
        # to the form-callback route while LS is active is rejected.
        return CallbackResult(valid=False)
