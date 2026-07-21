"""Lemon Squeezy MoR adapter + webhook (growth F1.3): signature check,
one-time top-ups via order_created, first subscription payment, renewals,
and idempotent replays."""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal

import config
from app import db
from models import Payment, User
from services.time_utils import datetime


def _configure_ls(monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "lemonsqueezy")
    monkeypatch.setattr(config, "LEMONSQUEEZY_API_KEY", "ls-key")
    monkeypatch.setattr(config, "LEMONSQUEEZY_STORE_ID", "777")
    monkeypatch.setattr(config, "LEMONSQUEEZY_SIGNING_SECRET", "ls-secret")
    monkeypatch.setattr(
        config, "LEMONSQUEEZY_VARIANTS",
        json.dumps({"pro": 111, "business": 222, "topup:50": 333}),
    )


def _sign(body):
    return hmac.new(b"ls-secret", body, hashlib.sha256).hexdigest()


def _post_webhook(client, event, sig=None):
    body = json.dumps(event).encode()
    return client.post(
        "/billing/lemonsqueezy/webhook", data=body,
        content_type="application/json",
        headers={"X-Signature": _sign(body) if sig is None else sig},
    )


def _user(username, plan="free"):
    user = User(username=username, email=f"{username}@example.com", plan=plan)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


def _pending(user, oid, *, plan="pro", kind="plan", credits=None, amount=19):
    payment = Payment(
        user_id=user.id, plan=plan, kind=kind, credits=credits,
        amount=Decimal(str(amount)), currency="USD", status="pending",
        provider="lemonsqueezy", provider_ref=oid,
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def _event(name, ref, data_id="1", status="paid", total=1900):
    return {
        "meta": {"event_name": name, "custom_data": {"payment_ref": ref}},
        "data": {"id": data_id, "attributes": {
            "status": status, "total": total, "currency": "USD",
        }},
    }


def test_bad_signature_is_rejected(client, monkeypatch):
    _configure_ls(monkeypatch)
    user = _user("ls_bad")
    _pending(user, "arvLS0001")
    resp = _post_webhook(client, _event("order_created", "arvLS0001"), sig="wrong")
    assert resp.status_code == 400
    assert db.session.get(User, user.id).plan == "free"


def test_order_created_grants_topup_once(client, monkeypatch):
    _configure_ls(monkeypatch)
    user = _user("ls_topup")
    _pending(user, "arvLS0002", plan="credits", kind="topup", credits=50, amount=25)
    event = _event("order_created", "arvLS0002", total=2500)

    assert _post_webhook(client, event).status_code == 200
    assert _post_webhook(client, event).status_code == 200  # replay
    refreshed = db.session.get(User, user.id)
    assert refreshed.ai_credit_balance == 50  # granted exactly once
    assert refreshed.plan == "free"
    assert Payment.query.filter_by(provider_ref="arvLS0002").one().status == "paid"


def test_order_created_never_grants_a_plan(client, monkeypatch):
    # Plans are subscriptions: subscription_payment_success grants them, so the
    # accompanying order_created must be a no-op (double-grant protection).
    _configure_ls(monkeypatch)
    user = _user("ls_planorder")
    _pending(user, "arvLS0003", plan="pro")
    _post_webhook(client, _event("order_created", "arvLS0003"))
    assert db.session.get(User, user.id).plan == "free"
    assert Payment.query.filter_by(provider_ref="arvLS0003").one().status == "pending"


def test_first_subscription_payment_applies_pending_plan(client, monkeypatch):
    _configure_ls(monkeypatch)
    user = _user("ls_first")
    _pending(user, "arvLS0004", plan="pro")
    _post_webhook(client, _event("subscription_payment_success", "arvLS0004"))
    refreshed = db.session.get(User, user.id)
    assert refreshed.plan == "pro"
    assert refreshed.plan_expires_at > datetime.utcnow() + timedelta(days=25)


def test_renewal_invoice_extends_plan_idempotently(client, monkeypatch):
    _configure_ls(monkeypatch)
    user = _user("ls_renew")
    _pending(user, "arvLS0005", plan="pro")
    _post_webhook(client, _event("subscription_payment_success", "arvLS0005"))
    first_expiry = db.session.get(User, user.id).plan_expires_at

    renewal = _event("subscription_payment_success", "arvLS0005", data_id="999")
    _post_webhook(client, renewal)
    second_expiry = db.session.get(User, user.id).plan_expires_at
    assert second_expiry > first_expiry + timedelta(days=25)

    _post_webhook(client, renewal)  # replayed invoice -> no third period
    assert db.session.get(User, user.id).plan_expires_at == second_expiry
    invoice = Payment.query.filter_by(provider_ref="lsinv-999").one()
    assert invoice.status == "paid"
    assert invoice.amount == Decimal("19")


def test_unknown_ref_is_acknowledged_without_side_effects(client, monkeypatch):
    _configure_ls(monkeypatch)
    resp = _post_webhook(client, _event("order_created", "arvNOPE"))
    assert resp.status_code == 200
    assert Payment.query.count() == 0


def test_webhook_is_404_when_ls_not_active(client, monkeypatch):
    monkeypatch.setattr(config, "PAYMENT_PROVIDER", "paytr")
    resp = client.post("/billing/lemonsqueezy/webhook", data=b"{}",
                       content_type="application/json")
    assert resp.status_code == 404


def test_create_checkout_builds_jsonapi_request(client, monkeypatch):
    _configure_ls(monkeypatch)
    from services.payments import get_active_provider
    import services.payments.lemonsqueezy as ls

    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return {"data": {"attributes": {"url": "https://ls.example/checkout"}}}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return _Resp()

    monkeypatch.setattr(ls.requests, "post", fake_post)
    user = _user("ls_checkout")
    payment = _pending(user, "arvLS0006", plan="pro")

    session = get_active_provider().create_checkout(
        payment, user, ok_url="https://ok", fail_url="https://fail",
        client_ip="1.2.3.4", email=user.email, item_name="ARVision Pro plan",
    )
    assert session.redirect_url == "https://ls.example/checkout"
    data = captured["json"]["data"]
    assert data["relationships"]["variant"]["data"]["id"] == "111"
    assert data["relationships"]["store"]["data"]["id"] == "777"
    assert data["attributes"]["checkout_data"]["custom"]["payment_ref"] == "arvLS0006"
    assert captured["headers"]["Authorization"] == "Bearer ls-key"


def test_verify_webhook_unit(monkeypatch):
    _configure_ls(monkeypatch)
    from services.payments.lemonsqueezy import LemonSqueezyProvider
    provider = LemonSqueezyProvider()
    body = b'{"x": 1}'
    assert provider.verify_webhook(body, _sign(body))
    assert not provider.verify_webhook(body, "nope")
    assert not provider.verify_webhook(body, "")
