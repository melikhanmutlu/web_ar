"""Manually-recorded payments (Faz 5 billing foundation): no payment provider
is integrated -- an admin logs what a user paid for which plan and when.
Covers admin.record_payment, admin.set_payment_status, and /admin/billing."""

from decimal import Decimal

from app import app, db
from models import Payment, User


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def _make_user(username, plan="free", is_admin=False):
    u = User(username=username, email=f"{username}@test.com", plan=plan, is_admin=is_admin)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def test_admin_can_record_a_payment_and_sync_plan(client):
    admin = _make_user("bill_admin", is_admin=True)
    target = _make_user("bill_target", plan="free")
    login(client, "bill_admin", "testpassword123")

    resp = client.post(f"/admin/users/{target.id}/record-payment", data={
        "plan": "pro", "amount": "19.00", "currency": "USD", "method": "manual",
        "period_start": "2026-07-01", "period_end": "2026-08-01",
        "update_plan": "on",
    }, follow_redirects=True)
    assert resp.status_code == 200

    payment = Payment.query.filter_by(user_id=target.id).first()
    assert payment is not None
    assert payment.plan == "pro"
    assert payment.amount == Decimal("19.00")
    assert payment.status == "paid"
    assert payment.recorded_by_id == admin.id
    assert db.session.get(User, target.id).plan == "pro"


def test_record_payment_without_checkbox_leaves_plan_unchanged(client):
    _make_user("bill_admin2", is_admin=True)
    target = _make_user("bill_target2", plan="free")
    login(client, "bill_admin2", "testpassword123")

    client.post(f"/admin/users/{target.id}/record-payment", data={
        "plan": "pro", "amount": "19.00",
        # no "update_plan" field -> plan stays as-is
    })
    assert db.session.get(User, target.id).plan == "free"
    assert Payment.query.filter_by(user_id=target.id).count() == 1


def test_record_payment_rejects_invalid_amount(client):
    _make_user("bill_admin3", is_admin=True)
    target = _make_user("bill_target3")
    login(client, "bill_admin3", "testpassword123")

    resp = client.post(f"/admin/users/{target.id}/record-payment", data={
        "plan": "pro", "amount": "-5",
    })
    assert resp.status_code == 302
    assert Payment.query.filter_by(user_id=target.id).count() == 0


def test_record_payment_rejects_non_self_serve_plan(client):
    _make_user("bill_admin4", is_admin=True)
    target = _make_user("bill_target4")
    login(client, "bill_admin4", "testpassword123")

    resp = client.post(f"/admin/users/{target.id}/record-payment", data={
        "plan": "unlimited", "amount": "19.00",
    })
    assert resp.status_code == 302
    assert Payment.query.filter_by(user_id=target.id).count() == 0


def test_non_admin_cannot_record_payment(client, init_database):
    login(client, "testuser", "testpassword")
    resp = client.post(f"/admin/users/{init_database.id}/record-payment", data={
        "plan": "pro", "amount": "19.00",
    })
    assert resp.status_code == 404


def test_admin_can_change_payment_status(client):
    admin = _make_user("bill_admin5", is_admin=True)
    target = _make_user("bill_target5", plan="pro")
    payment = Payment(user_id=target.id, plan="pro", amount=Decimal("19.00"), recorded_by_id=admin.id)
    db.session.add(payment)
    db.session.commit()
    login(client, "bill_admin5", "testpassword123")

    resp = client.post(f"/admin/payments/{payment.id}/set-status", json={"status": "refunded"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "refunded"
    assert db.session.get(Payment, payment.id).status == "refunded"

    resp2 = client.post(f"/admin/payments/{payment.id}/set-status", json={"status": "bogus"})
    assert resp2.status_code == 400


def test_non_admin_cannot_change_payment_status(client, init_database):
    admin = _make_user("bill_admin6", is_admin=True)
    payment = Payment(user_id=init_database.id, plan="free", amount=Decimal("0"), recorded_by_id=admin.id)
    db.session.add(payment)
    db.session.commit()

    login(client, "testuser", "testpassword")
    resp = client.post(f"/admin/payments/{payment.id}/set-status", json={"status": "void"})
    assert resp.status_code == 404


def test_billing_page_renders_with_payments(client):
    admin = _make_user("bill_admin7", is_admin=True)
    target = _make_user("bill_target7", plan="pro")
    db.session.add(Payment(user_id=target.id, plan="pro", amount=Decimal("19.00"), recorded_by_id=admin.id))
    db.session.commit()
    login(client, "bill_admin7", "testpassword123")

    resp = client.get("/admin/billing")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "bill_target7" in body
    assert "19.00" in body


def test_billing_csv_export(client):
    _make_user("bill_admin8", is_admin=True)
    login(client, "bill_admin8", "testpassword123")
    resp = client.get("/admin/billing/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"


def test_non_admin_cannot_view_billing(client, init_database):
    login(client, "testuser", "testpassword")
    assert client.get("/admin/billing").status_code == 404
