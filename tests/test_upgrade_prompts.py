"""Standard `upgrade` hint on plan-limit / feature-gate rejections
(growth F1.5): the JSON contract the shared fetch wrapper's upgrade CTA
consumes (services/upgrade.py)."""

from models import User, UserModel, db


def _login_free_user(client, username="hint_free"):
    user = User(username=username, email=f"{username}@example.com")  # free plan
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": user.username, "password": "password"})
    return user


def _assert_upgrade(response, reason, status):
    assert response.status_code == status
    upgrade = response.get_json()["upgrade"]
    assert upgrade["reason"] == reason
    assert upgrade["url"] == f"/pricing?upgrade_reason={reason}"


def test_organization_gate_carries_upgrade_hint(client):
    _login_free_user(client, "hint_org")
    resp = client.post("/api/organizations", json={"name": "Startup"})
    _assert_upgrade(resp, "organizations", 403)


def test_webhook_gate_carries_upgrade_hint(client):
    _login_free_user(client, "hint_hook")
    resp = client.post("/api/webhooks", json={
        "url": "https://example.com/hook", "event_types": ["conversion.completed"],
    })
    _assert_upgrade(resp, "webhooks", 403)


def test_api_token_gate_carries_upgrade_hint(client):
    _login_free_user(client, "hint_token")
    resp = client.post("/api/tokens", json={"name": "ci"})
    _assert_upgrade(resp, "api_access", 403)


def test_password_share_gate_carries_upgrade_hint(client):
    user = _login_free_user(client, "hint_share")
    model = UserModel(
        id="2a2a2a2a-2a2a-2a2a-2a2a-2a2a2a2a2a2a",
        filename="unused.glb", user_id=user.id, visibility="private",
    )
    db.session.add(model)
    db.session.commit()
    resp = client.post(
        f"/api/models/{model.id}/share-links",
        json={"permission": "view", "password": "secret"},
    )
    _assert_upgrade(resp, "password_protected_shares", 403)


def test_ai_quota_rejection_carries_upgrade_hint(client, monkeypatch):
    import app as app_module
    from services import ai_jobs
    import ai_generator

    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    monkeypatch.setattr(ai_jobs, "_consume_ai_allowance", lambda user: (False, 5, 5))
    _login_free_user(client, "hint_ai")
    resp = client.post("/api/generate-3d", json={"mode": "text", "prompt": "a chair"})
    _assert_upgrade(resp, "ai_credits", 429)


def test_pricing_org_features_are_self_serve(client):
    html = client.get("/pricing").get_data(as_text=True)
    # Organizations / custom domains / white-label now have a Workspace UI, so
    # pricing must not describe them as set up by hand.
    assert "set up on request" not in html
    assert "Workspace" in html


def test_pro_plan_has_no_org_seats():
    from services.plans import PLAN_CONFIG
    pro = PLAN_CONFIG["pro"]
    assert pro["features"]["organizations"] is False
    assert not pro["limits"]["max_org_members"]
