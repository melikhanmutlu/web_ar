"""Payment-provider abstraction.

A provider adapter turns a pending Payment into a hosted-checkout session and
verifies the gateway's server-to-server callback. Keeping this behind a small
interface means a second gateway (iyzico, Paddle, Stripe for a global launch)
is just another adapter -- the billing blueprint, Payment model, and the plan
enforcement layer never change. See paytr.py for the reference implementation.
"""

from dataclasses import dataclass


@dataclass
class CheckoutSession:
    """What a provider returns to start a hosted payment. `iframe_url` is set
    for iFrame-style gateways (PayTR); `redirect_url` for redirect-style ones.
    At least one is present on success."""
    iframe_url: str | None = None
    redirect_url: str | None = None


@dataclass
class CallbackResult:
    """Outcome of verifying a provider's server-to-server callback."""
    valid: bool                 # signature/hash checked out
    reference: str | None = None  # provider order id (Payment.provider_ref)
    paid: bool = False          # the payment succeeded
    amount: int | None = None   # minor units the gateway reports (kuruş/cents)
    raw_status: str | None = None


class PaymentProvider:
    """Interface every gateway adapter implements."""

    name = "base"

    def is_configured(self):
        """True when the provider has the credentials it needs to run."""
        raise NotImplementedError

    def create_checkout(self, payment, user, *, ok_url, fail_url, client_ip,
                         email, item_name):
        """Start a hosted-checkout session for `payment`. Returns a
        CheckoutSession, or raises RuntimeError if the gateway rejects it."""
        raise NotImplementedError

    def verify_callback(self, form):
        """Verify a gateway callback (form dict) and return a CallbackResult.
        Never trusts the payload until the signature/hash is confirmed."""
        raise NotImplementedError

    def callback_ack(self):
        """The exact body the gateway expects back on a handled callback."""
        return "OK"
