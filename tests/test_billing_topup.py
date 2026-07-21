"""Credit top-up checkout (growth F1.2): /billing/topup/<pack> and the
'topup' branch of the payment callback. Reuses the PayTR hash helpers from
test_billing_paytr's pattern."""

import base64
import hashlib
import hmac

import config
from app import db
from models import Payment, User
from services.payments.base import CheckoutSession
from services.payments.paytr import PayTRProvider


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


def _user(username="topper", plan="pro", credits=0):
    user = User(username=username, email=f"{username}@example.com", plan=plan,
                ai_credit_balance=credits)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


def _pending_topup(user, oid, credits=50, amount=39):
    payment = Payment(
        user_id=user.id, plan="credits", kind="topup", credits=credits,
        amount=amount, currency="TRY", status="pending",
        provider="paytr", provider_ref=oid,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def test_topup_checkout_creates_pending_topup_payment(client, monkeypatch):
    _configure_paytr(monkeypatch)
    monkeypatch.setattr(
        PayTRProvider, "create_checkout",
        lambda self, payment, user, **kw: CheckoutSession(iframe_url="https://pay.example/x"),
    )
    user = _user("top_checkout")
    client.post("/login", data={"username": user.username, "password": "password"})

    resp = client.post("/billing/topup/medium")
    assert resp.status_code == 200
    payment = Payment.query.filter_by(user_id=user.id).one()
    assert payment.kind == "topup"
    assert payment.plan == "credits"
    assert payment.credits == 50
    assert payment.status == "pending"


def test_unknown_pack_is_rejected(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user("top_unknown")
    client.post("/login", data={"username": user.username, "password": "password"})

    resp = client.post("/billing/topup/enormous", follow_redirects=False)
    assert resp.status_code == 302
    assert Payment.query.filter_by(user_id=user.id).count() == 0


def test_topup_callback_grants_credits_without_touching_plan(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user("top_grant", plan="pro", credits=3)
    _pending_topup(user, "arvTOPUP0001", credits=50)

    resp = client.post("/billing/paytr/callback", data={
        "merchant_oid": "arvTOPUP0001", "status": "success", "total_amount": "3900",
        "hash": _callback_hash("arvTOPUP0001", "success", "3900"),
    })
    assert resp.get_data() == b"OK"
    refreshed = db.session.get(User, user.id)
    assert refreshed.ai_credit_balance == 53
    assert refreshed.plan == "pro"           # plan untouched
    assert refreshed.plan_expires_at is None  # no period granted
    assert Payment.query.filter_by(provider_ref="arvTOPUP0001").one().status == "paid"


def test_topup_callback_is_idempotent(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user("top_idemp", credits=0)
    _pending_topup(user, "arvTOPUP0002", credits=10)
    data = {
        "merchant_oid": "arvTOPUP0002", "status": "success", "total_amount": "900",
        "hash": _callback_hash("arvTOPUP0002", "success", "900"),
    }
    client.post("/billing/paytr/callback", data=data)
    client.post("/billing/paytr/callback", data=data)
    assert db.session.get(User, user.id).ai_credit_balance == 10  # granted once


def test_failed_topup_grants_nothing(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user("top_failed", credits=0)
    _pending_topup(user, "arvTOPUP0003", credits=200)

    client.post("/billing/paytr/callback", data={
        "merchant_oid": "arvTOPUP0003", "status": "failed", "total_amount": "13900",
        "hash": _callback_hash("arvTOPUP0003", "failed", "13900"),
    })
    assert db.session.get(User, user.id).ai_credit_balance == 0
    assert Payment.query.filter_by(provider_ref="arvTOPUP0003").one().status == "failed"


def test_billing_page_shows_credit_packs(client, monkeypatch):
    _configure_paytr(monkeypatch)
    user = _user("top_page", credits=7)
    client.post("/login", data={"username": user.username, "password": "password"})

    resp = client.get("/billing")
    body = resp.get_data(as_text=True)
    assert "AI credits" in body
    assert "50 credits" in body
    assert ">7</strong>" in body  # current balance rendered
