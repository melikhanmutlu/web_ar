"""PayTR iFrame API adapter.

Flow (https://dev.paytr.com/iframe-api):
1. create_checkout() POSTs an order to PayTR's get-token endpoint with a
   paytr_token = base64(HMAC-SHA256(<concatenated order fields> + merchant_salt,
   merchant_key)). PayTR returns a token; the payment page is the iframe URL
   https://www.paytr.com/odeme/guest/<token>/ where the card form lives (card
   data never touches our server -- no PCI burden).
2. After payment PayTR POSTs a server-to-server callback with merchant_oid,
   status, total_amount and a hash = base64(HMAC-SHA256(merchant_oid +
   merchant_salt + status + total_amount, merchant_key)). verify_callback()
   recomputes and compares it; the caller must reply with the literal "OK".

Card data never touches our server. The HMAC construction mirrors the signing
pattern in services/webhooks.py.
"""

import base64
import hashlib
import hmac
import json

import requests

import config
from services.payments.base import CallbackResult, CheckoutSession, PaymentProvider

_GET_TOKEN_URL = "https://www.paytr.com/odeme/api/get-token"
_IFRAME_URL = "https://www.paytr.com/odeme/guest/{token}/"
_TIMEOUT_SECONDS = 20


def _b64_hmac(message):
    """base64(HMAC-SHA256(message, merchant_key)) — PayTR's signature scheme."""
    digest = hmac.new(
        config.PAYTR_MERCHANT_KEY.encode(), message.encode(), hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode()


class PayTRProvider(PaymentProvider):
    name = "paytr"

    def is_configured(self):
        return bool(
            config.PAYTR_MERCHANT_ID
            and config.PAYTR_MERCHANT_KEY
            and config.PAYTR_MERCHANT_SALT
        )

    def create_checkout(self, payment, user, *, ok_url, fail_url, client_ip,
                        email, item_name):
        if not self.is_configured():
            raise RuntimeError("PayTR is not configured.")
        merchant_oid = payment.provider_ref
        amount_kurus = int(round(float(payment.amount) * 100))
        basket = base64.b64encode(
            json.dumps([[item_name, str(payment.amount), 1]]).encode()
        ).decode()
        test_mode = "1" if str(config.PAYTR_TEST_MODE) == "1" else "0"
        no_installment = "0"
        max_installment = "0"
        currency = payment.currency or config.BILLING_CURRENCY

        # The token hash covers this exact field order (PayTR spec).
        token_str = (
            f"{config.PAYTR_MERCHANT_ID}{client_ip}{merchant_oid}{email}"
            f"{amount_kurus}{basket}{no_installment}{max_installment}"
            f"{currency}{test_mode}{config.PAYTR_MERCHANT_SALT}"
        )
        paytr_token = _b64_hmac(token_str)

        payload = {
            "merchant_id": config.PAYTR_MERCHANT_ID,
            "user_ip": client_ip,
            "merchant_oid": merchant_oid,
            "email": email,
            "payment_amount": amount_kurus,
            "paytr_token": paytr_token,
            "user_basket": basket,
            "debug_on": "1" if test_mode == "1" else "0",
            "no_installment": no_installment,
            "max_installment": max_installment,
            "user_name": (user.username or "customer")[:60],
            "user_address": "N/A",
            "user_phone": "0000000000",
            "merchant_ok_url": ok_url,
            "merchant_fail_url": fail_url,
            "timeout_limit": "30",
            "currency": currency,
            "test_mode": test_mode,
            "lang": "tr",
        }
        try:
            response = requests.post(_GET_TOKEN_URL, data=payload, timeout=_TIMEOUT_SECONDS)
            response.raise_for_status()
            body = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise RuntimeError(f"PayTR token request failed: {exc}") from exc
        if body.get("status") != "success":
            raise RuntimeError(f"PayTR rejected the order: {body.get('reason', 'unknown error')}")
        return CheckoutSession(iframe_url=_IFRAME_URL.format(token=body["token"]))

    def verify_callback(self, form):
        merchant_oid = form.get("merchant_oid", "")
        status = form.get("status", "")
        total_amount = form.get("total_amount", "")
        received_hash = form.get("hash", "")
        expected = _b64_hmac(
            f"{merchant_oid}{config.PAYTR_MERCHANT_SALT}{status}{total_amount}"
        )
        # Constant-time compare so a mismatched hash can't be timed out.
        if not received_hash or not hmac.compare_digest(received_hash, expected):
            return CallbackResult(valid=False, reference=merchant_oid or None)
        amount = None
        try:
            amount = int(total_amount)
        except (TypeError, ValueError):
            pass
        return CallbackResult(
            valid=True,
            reference=merchant_oid,
            paid=(status == "success"),
            amount=amount,
            raw_status=status,
        )
