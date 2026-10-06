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


# ---- Invoice outcome is stored on the Payment (ADM-20 follow-up) -----------

def _real_payment(kind="plan"):
    from models import Payment, User, db
    user = User(username=f"inv_{kind}", email=f"inv_{kind}@test.com")
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    payment = Payment(user_id=user.id, plan="credits" if kind == "topup" else "pro", kind=kind,
                      credits=5 if kind == "topup" else None, amount=Decimal("19.00"),
                      currency="TRY", status="paid")
    db.session.add(payment)
    db.session.commit()
    return payment, user


def _configure_parasut(monkeypatch):
    monkeypatch.setattr(config, "INVOICING_PROVIDER", "parasut")
    monkeypatch.setattr(config, "PARASUT_CLIENT_ID", "id")
    monkeypatch.setattr(config, "PARASUT_CLIENT_SECRET", "secret")
    monkeypatch.setattr(config, "PARASUT_COMPANY_ID", "999")


def test_parasut_stub_result_recorded_as_failed(client, monkeypatch):
    from models import db
    _configure_parasut(monkeypatch)
    payment, user = _real_payment()
    assert payment.invoice_status == "none"
    invoicing.issue_invoice(payment, user)
    db.session.refresh(payment)
    assert payment.invoice_status == "failed"
    assert "not implemented" in payment.invoice_error


def test_issued_invoice_stores_external_id(client, monkeypatch):
    from models import db
    monkeypatch.setattr(config, "INVOICING_PROVIDER", "parasut")
    monkeypatch.setattr(invoicing.ParasutProvider, "issue_invoice",
                        lambda self, p, u: invoicing.InvoiceResult(True, "parasut", "INV-42"))
    payment, user = _real_payment()
    invoicing.issue_invoice(payment, user)
    db.session.refresh(payment)
    assert (payment.invoice_status, payment.invoice_external_id, payment.invoice_error) == ("issued", "INV-42", None)


def test_no_provider_leaves_status_none(client, monkeypatch):
    from models import db
    monkeypatch.setattr(config, "INVOICING_PROVIDER", "")
    payment, user = _real_payment()
    invoicing.issue_invoice(payment, user)
    db.session.refresh(payment)
    assert payment.invoice_status == "none"


def test_topup_and_plan_payments_record_outcome(client, monkeypatch):
    from blueprints.billing import _apply_successful_payment
    from models import db
    _configure_parasut(monkeypatch)
    for kind in ("plan", "topup"):
        payment, _ = _real_payment(kind)
        payment.status = "pending"
        db.session.commit()
        _apply_successful_payment(payment)
        db.session.refresh(payment)
        assert payment.invoice_status == "failed", kind


def test_admin_billing_shows_invoice_status(client, monkeypatch):
    from models import User, db
    from tests.test_admin import login
    _configure_parasut(monkeypatch)
    payment, user = _real_payment()
    invoicing.issue_invoice(payment, user)
    admin = User(username="adminbill", email="adminbill@test.com", is_admin=True)
    admin.set_password("adminpassword")
    db.session.add(admin)
    db.session.commit()
    login(client, "adminbill", "adminpassword")
    html = client.get("/admin/billing").get_data(as_text=True)
    assert "Parasut adapter not implemented yet." in html
    assert "status-badge--failed" in html
