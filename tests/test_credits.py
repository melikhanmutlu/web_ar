"""Prepaid AI overage credits: grant seam, consumption past the monthly plan
quota, and the admin grant endpoint."""

import uuid

from app import _consume_ai_allowance, db
from models import AIGenerationJob, User
from services.credits import grant_ai_credits


def _make_user(username, plan="free", credits=0):
    u = User(username=username, email=f"{username}@test.com", plan=plan,
             ai_credit_balance=credits)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def _seed_ai_jobs(user_id, n):
    for _ in range(n):
        db.session.add(AIGenerationJob(
            id=str(uuid.uuid4()), user_id=user_id, kind="text",
            prompt="x", stage="preview", status="ready",
        ))
    db.session.commit()


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


# --- grant seam ---

def test_grant_ai_credits_adds_deducts_and_clamps(client):
    u = _make_user("credit_grant")
    assert grant_ai_credits(u, 10) == 10
    assert grant_ai_credits(u, -3) == 7
    assert grant_ai_credits(u, -100) == 0  # never below zero
    assert u.ai_credit_balance == 0


# --- consumption logic ---

def test_within_quota_does_not_touch_credits(client):
    u = _make_user("credit_within", plan="pro", credits=5)  # pro limit 20
    allowed, count, limit = _consume_ai_allowance(u)
    assert allowed is True
    assert limit == 20
    assert u.ai_credit_balance == 5  # untouched while under the plan quota


def test_credit_consumed_past_monthly_quota(client):
    u = _make_user("credit_over", plan="pro", credits=2)
    _seed_ai_jobs(u.id, 20)  # exhaust the pro monthly quota
    allowed, count, limit = _consume_ai_allowance(u)
    assert allowed is True
    assert u.ai_credit_balance == 1  # one overage credit spent


def test_blocked_when_quota_exhausted_and_no_credits(client):
    u = _make_user("credit_none", plan="pro", credits=0)
    _seed_ai_jobs(u.id, 20)
    allowed, count, limit = _consume_ai_allowance(u)
    assert allowed is False
    assert u.ai_credit_balance == 0


# --- admin grant endpoint ---

def test_admin_can_grant_and_clamp_credits(client):
    admin = _make_user("credit_admin")
    admin.is_admin = True
    db.session.commit()
    target = _make_user("credit_target", credits=5)
    login(client, "credit_admin", "testpassword123")

    resp = client.post(f"/admin/users/{target.id}/adjust-credits", json={"amount": 10})
    assert resp.status_code == 200
    assert resp.get_json()["ai_credit_balance"] == 15
    assert db.session.get(User, target.id).ai_credit_balance == 15

    resp = client.post(f"/admin/users/{target.id}/adjust-credits", json={"amount": -1000})
    assert resp.status_code == 200
    assert resp.get_json()["ai_credit_balance"] == 0

    resp = client.post(f"/admin/users/{target.id}/adjust-credits", json={"amount": "nope"})
    assert resp.status_code == 400


def test_non_admin_cannot_adjust_credits(client, init_database):
    login(client, "testuser", "testpassword")
    resp = client.post(f"/admin/users/{init_database.id}/adjust-credits", json={"amount": 10})
    assert resp.status_code == 404
