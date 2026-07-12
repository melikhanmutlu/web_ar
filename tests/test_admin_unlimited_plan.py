"""Admins are on an internal, fully-authorized 'unlimited' plan.

They bypass the AI monthly quota (the source of the 429 during admin testing)
and every plan limit/feature, and the plan is hidden from /pricing and can't be
assigned to anyone.
"""
import uuid

import app as app_module
from app import db
from models import AIGenerationJob, User
from services.plans import (
    PLANS, ADMIN_PLAN, plan_name, plan_limit, plan_allows,
    effective_ai_monthly_limit,
)


def _make_user(username, is_admin=False, plan="free"):
    u = User(username=username, email=f"{username}@test.com", is_admin=is_admin, plan=plan)
    u.set_password("pw12345678")
    db.session.add(u)
    db.session.commit()
    return u


def test_unlimited_plan_is_hidden_and_unassignable(client):
    # Never offered publicly...
    assert ADMIN_PLAN not in PLANS
    # ...and the admin set-plan endpoint rejects it (validates against PLANS).
    admin = _make_user("uadmin", is_admin=True)
    target = _make_user("utarget")
    client.post("/login", data={"username": "uadmin", "password": "pw12345678"})
    resp = client.post(f"/admin/users/{target.id}/set-plan", json={"plan": ADMIN_PLAN})
    assert resp.status_code == 400
    assert db.session.get(User, target.id).plan == "free"


def test_admin_resolves_to_unlimited_everywhere(client):
    admin = _make_user("uadmin2", is_admin=True, plan="free")  # stored plan irrelevant
    free = _make_user("ufree2")

    assert plan_name(admin) == ADMIN_PLAN
    assert plan_name(free) == "free"
    # Unlimited numeric limits + all features.
    assert plan_limit(admin, "max_models") is None            # unlimited
    assert effective_ai_monthly_limit(admin, 0) >= 1_000_000  # never hit
    assert plan_allows(admin, "webhooks") is True
    assert plan_allows(admin, "white_label") is True


def test_admin_bypasses_ai_monthly_quota(client):
    """The 429 the user hit: even with the global monthly limit at 0 (AI off for
    free users) and existing generations on record, an admin is never blocked."""
    admin = _make_user("uadmin3", is_admin=True)
    for _ in range(5):
        db.session.add(AIGenerationJob(
            id=str(uuid.uuid4()), user_id=admin.id, kind="image",
            stage="image", status="ready",
        ))
    db.session.commit()

    exceeded, count, limit = app_module._ai_quota_state(admin.id)
    assert exceeded is False
    allowed, _, _ = app_module._consume_ai_allowance(db.session.get(User, admin.id))
    assert allowed is True


def test_non_admin_free_still_limited(client):
    """Regression guard: the admin exemption must not leak to normal users --
    a free user keeps a real, finite plan limit far below the admin sentinel."""
    free = _make_user("ufree3")
    admin = _make_user("uadmin4", is_admin=True)
    _, _, free_limit = app_module._ai_quota_state(free.id)
    _, _, admin_limit = app_module._ai_quota_state(admin.id)
    assert free_limit < 1_000_000
    assert admin_limit >= 1_000_000
