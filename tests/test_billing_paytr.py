"""PayTR provider-agnostic subscription billing: callback verification, plan
grant + expiry, idempotency, and the worker expiry sweep."""
import base64
import hashlib
import hmac
from datetime import timedelta

import pytest

import config
from services.time_utils import datetime
from models import Payment, User, db


def _configure_paytr(monkeypatch):
    monkeypatch.setattr(config, "PAYTR_MERCHANT_ID", "123456")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_KEY", "test-key")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_SALT", "test-salt")
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "paytr")


def _callback_hash(merchant_oid, status, total_amount):
    msg = f"{merchant_oid}test-salt{status}{total_amount}"
    return base64.b64encode(
        hmac.new(b"test-key", msg.encode(), hashlib.sha256).digest()
    ).decode()


def _pending_payment(user, oid, plan="business", amount=99):
    payment = Payment(
        user_id=user.id, plan=plan, amount=amount, currency="TRY",
        status="pending", provider="paytr", provider_ref=oid,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def _user(username="payer", plan="free"):
    user = User(username=username, email=f"{username}@example.com", plan=plan)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


def test_successful_callback_grants_plan_and_expiry(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user()
    _pending_payment(user, "arvSUCCESS01")
    resp = client.post("/billing/paytr/callback", data={
        "merchant_oid": "arvSUCCESS01", "status": "success", "total_amount": "9900",
        "hash": _callback_hash("arvSUCCESS01", "success", "9900"),
    })
    assert resp.status_code == 200
    assert resp.get_data() == b"OK"
    refreshed = db.session.get(User, user.id)
    assert refreshed.plan == "business"
    assert refreshed.plan_expires_at is not None
    assert refreshed.plan_expires_at > datetime.utcnow()
    assert Payment.query.filter_by(provider_ref="arvSUCCESS01").first().status == "paid"


def test_callback_with_bad_hash_is_rejected(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user()
    _pending_payment(user, "arvBADHASH01")
    resp = client.post("/billing/paytr/callback", data={
        "merchant_oid": "arvBADHASH01", "status": "success", "total_amount": "9900",
        "hash": "not-the-real-hash",
    })
    assert resp.status_code == 400
    assert db.session.get(User, user.id).plan == "free"
    assert Payment.query.filter_by(provider_ref="arvBADHASH01").first().status == "pending"


def test_callback_is_idempotent(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user()
    _pending_payment(user, "arvIDEMP0001")
    data = {
        "merchant_oid": "arvIDEMP0001", "status": "success", "total_amount": "9900",
        "hash": _callback_hash("arvIDEMP0001", "success", "9900"),
    }
    first = client.post("/billing/paytr/callback", data=data)
    expiry_after_first = db.session.get(User, user.id).plan_expires_at
    second = client.post("/billing/paytr/callback", data=data)
    assert first.get_data() == second.get_data() == b"OK"
    # A replay doesn't extend the plan a second time.
    assert db.session.get(User, user.id).plan_expires_at == expiry_after_first
    assert Payment.query.filter_by(provider_ref="arvIDEMP0001").count() == 1


def test_failed_callback_marks_payment_failed_without_granting(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user()
    _pending_payment(user, "arvFAILED001")
    resp = client.post("/billing/paytr/callback", data={
        "merchant_oid": "arvFAILED001", "status": "failed", "total_amount": "9900",
        "hash": _callback_hash("arvFAILED001", "failed", "9900"),
    })
    assert resp.get_data() == b"OK"
    assert db.session.get(User, user.id).plan == "free"
    assert Payment.query.filter_by(provider_ref="arvFAILED001").first().status == "failed"


def test_checkout_disabled_when_provider_unconfigured(client, monkeypatch):
    monkeypatch.setattr(config, "PAYTR_MERCHANT_ID", "")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_KEY", "")
    monkeypatch.setattr(config, "PAYTR_MERCHANT_SALT", "")
    user = _user()
    client.post("/login", data={"username": user.username, "password": "password"})
    resp = client.post("/billing/checkout/business", follow_redirects=False)
    assert resp.status_code == 302  # bounced back to /billing with a flash


def test_provider_verify_callback_unit(monkeypatch):
    _configure_paytr(monkeypatch)
    from services.payments import get_active_provider
    provider = get_active_provider()
    good = provider.verify_callback({
        "merchant_oid": "x1", "status": "success", "total_amount": "100",
        "hash": _callback_hash("x1", "success", "100"),
    })
    assert good.valid and good.paid and good.reference == "x1"
    bad = provider.verify_callback({
        "merchant_oid": "x1", "status": "success", "total_amount": "100", "hash": "nope",
    })
    assert not bad.valid


def test_expire_stale_plans_downgrades_and_notifies(client, monkeypatch):
    import worker
    expired = _user("expired", plan="business")
    expired.plan_expires_at = datetime.utcnow() - timedelta(days=1)
    active = _user("active", plan="pro")
    active.plan_expires_at = datetime.utcnow() + timedelta(days=5)
    db.session.commit()

    worker.expire_stale_plans()

    assert db.session.get(User, expired.id).plan == "free"
    assert db.session.get(User, expired.id).plan_expires_at is None
    # An unexpired paid plan is left alone.
    assert db.session.get(User, active.id).plan == "pro"
