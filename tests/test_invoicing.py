"""E-invoice adapter seam (growth F3.8): selection, unconfigured no-op, and the
never-raises contract."""

from decimal import Decimal
from types import SimpleNamespace

import config
from services import invoicing


def _payment():
    return SimpleNamespace(id=1, amount=Decimal("19.00"), currency="TRY")


def _user():
    return SimpleNamespace(id=1, email="b2b@corp.com")


def test_no_provider_active_by_default(client, monkeypatch):
    monkeypatch.setattr(config, "INVOICING_PROVIDER", "")
    assert invoicing.get_active_provider() is None
    result = invoicing.issue_invoice(_payment(), _user())
    assert result.issued is False


def test_parasut_selected_but_unconfigured_is_noop(client, monkeypatch):
    monkeypatch.setattr(config, "INVOICING_PROVIDER", "parasut")
    monkeypatch.setattr(config, "PARASUT_CLIENT_ID", "")
    provider = invoicing.get_active_provider()
    assert provider is not None
    assert provider.name == "parasut"
    assert provider.is_configured() is False
    result = invoicing.issue_invoice(_payment(), _user())
    assert result.issued is False
    assert "not configured" in (result.error or "")


def test_parasut_configured_returns_not_implemented(client, monkeypatch):
    monkeypatch.setattr(config, "INVOICING_PROVIDER", "parasut")
    monkeypatch.setattr(config, "PARASUT_CLIENT_ID", "id")
    monkeypatch.setattr(config, "PARASUT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(config, "PARASUT_COMPANY_ID", "999")
    provider = invoicing.get_active_provider()
    assert provider.is_configured() is True
    result = invoicing.issue_invoice(_payment(), _user())
    # Skeleton: configured but not wired to the live API yet.
    assert result.issued is False
    assert result.provider == "parasut"


def test_issue_invoice_never_raises(client, monkeypatch):
    monkeypatch.setattr(config, "INVOICING_PROVIDER", "parasut")
    monkeypatch.setattr(config, "PARASUT_CLIENT_ID", "id")
    monkeypatch.setattr(config, "PARASUT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(config, "PARASUT_COMPANY_ID", "999")

    def boom(self, payment, user):
        raise RuntimeError("provider exploded")
    monkeypatch.setattr(invoicing.ParasutProvider, "issue_invoice", boom)

    result = invoicing.issue_invoice(_payment(), _user())  # must not raise
    assert result.issued is False
    assert "exploded" in (result.error or "")
