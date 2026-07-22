"""E-invoice / e-arşiv adapter seam (growth F3.8).

Turkish B2B sales require issuing a formal invoice (e-Arşiv/e-Fatura) for each
payment. This module is the provider-agnostic seam for that, mirroring
services/payments/: a thin interface plus one skeleton adapter (Parasut). No
provider is active until INVOICING_PROVIDER + credentials are configured, so
the billing flow runs unchanged without it.

Wiring the actual Parasut HTTP calls (OAuth token, contact upsert, sales
invoice create) needs a live account and is intentionally left as the one
TODO — the interface, config, selection and no-op-when-unconfigured behavior
are here and tested so the rest of the app can call issue_invoice() today.
"""

import logging
from dataclasses import dataclass

import config

logger = logging.getLogger(__name__)


@dataclass
class InvoiceResult:
    """Outcome of an issue_invoice call."""
    issued: bool
    provider: str | None = None
    external_id: str | None = None
    error: str | None = None


class InvoicingProvider:
    """Interface every e-invoice adapter implements."""

    name = "base"

    def is_configured(self):
        raise NotImplementedError

    def issue_invoice(self, payment, user):
        """Issue an invoice for a paid Payment. Returns an InvoiceResult;
        never raises (a failure is reported, not thrown, so it can't break the
        payment-confirmation path)."""
        raise NotImplementedError


class ParasutProvider(InvoicingProvider):
    """Parasut (paraşüt) e-Arşiv/e-Fatura adapter — skeleton.

    Configured via PARASUT_CLIENT_ID / PARASUT_CLIENT_SECRET /
    PARASUT_USERNAME / PARASUT_PASSWORD / PARASUT_COMPANY_ID.
    """

    name = "parasut"

    def is_configured(self):
        return bool(
            getattr(config, "PARASUT_CLIENT_ID", "")
            and getattr(config, "PARASUT_CLIENT_SECRET", "")
            and getattr(config, "PARASUT_COMPANY_ID", "")
        )

    def issue_invoice(self, payment, user):
        if not self.is_configured():
            return InvoiceResult(issued=False, provider=self.name,
                                 error="Parasut is not configured.")
        # TODO(F3.8+): OAuth password-grant token -> upsert contact for `user`
        # -> POST sales_invoices with payment.amount/currency/description ->
        # mark it e-Arşiv. Left unimplemented pending a live account.
        logger.info(
            "Parasut invoice requested for payment %s (%.2f %s) — adapter not "
            "yet wired to the live API.",
            getattr(payment, "id", "?"), float(payment.amount), payment.currency,
        )
        return InvoiceResult(issued=False, provider=self.name,
                             error="Parasut adapter not implemented yet.")


_PROVIDERS = {
    "parasut": ParasutProvider,
}


def get_active_provider():
    """The configured InvoicingProvider instance, or None when invoicing is
    off (INVOICING_PROVIDER unset/unknown)."""
    name = (getattr(config, "INVOICING_PROVIDER", "") or "").lower()
    provider_cls = _PROVIDERS.get(name)
    return provider_cls() if provider_cls else None


def issue_invoice(payment, user):
    """Issue an invoice for a payment if a provider is active and configured.
    A no-op (issued=False) otherwise. Safe to call from the payment-success
    path — never raises."""
    provider = get_active_provider()
    if provider is None:
        return InvoiceResult(issued=False, error="No invoicing provider active.")
    try:
        return provider.issue_invoice(payment, user)
    except Exception as exc:  # defensive: invoicing must never break billing
        logger.warning("Invoice issue failed: %s", exc)
        return InvoiceResult(issued=False, provider=provider.name, error=str(exc))
