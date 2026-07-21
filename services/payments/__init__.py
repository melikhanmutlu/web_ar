"""Payment provider registry. get_active_provider() returns the adapter named
by config.PAYMENT_PROVIDER (default "paytr"). Add a provider by registering its
adapter here -- nothing else in the billing flow needs to change."""

import config
from services.payments.base import CallbackResult, CheckoutSession, PaymentProvider
from services.payments.paytr import PayTRProvider

_PROVIDERS = {
    "paytr": PayTRProvider,
}


def get_active_provider():
    """The configured PaymentProvider instance, or None if the name is unknown."""
    provider_cls = _PROVIDERS.get((config.PAYMENT_PROVIDER or "").lower())
    return provider_cls() if provider_cls else None


__all__ = [
    "get_active_provider",
    "PaymentProvider",
    "CheckoutSession",
    "CallbackResult",
]
