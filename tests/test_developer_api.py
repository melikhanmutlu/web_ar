"""Developer self-serve UI, the public docs page, webhook secret rotation,
and the OpenAPI spec."""
from models import User, WebhookSubscription, db


def _login(client, plan="business"):
    user = User(username="dev", email="dev@example.com", plan=plan)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": user.username, "password": "password"})
    return user


def test_developer_settings_requires_login(client):
    resp = client.get("/settings/developer")
    assert resp.status_code == 302  # bounced to login


def test_developer_settings_renders_for_user(client):
    _login(client)
    resp = client.get("/settings/developer")
    assert resp.status_code == 200
    assert b"API tokens" in resp.data
    assert b"Webhooks" in resp.data


def test_developers_docs_page_is_indexable(client):
    resp = client.get("/developers")
    assert resp.status_code == 200
    assert b"index, follow" in resp.data
    assert b"/api/v1" in resp.data
    # Listed in the sitemap.
    assert b"/developers" in client.get("/sitemap.xml").data


def test_openapi_spec_is_served(client):
    resp = client.get("/api/v1/openapi.json")
    assert resp.status_code == 200
    spec = resp.get_json()
    assert spec["openapi"].startswith("3.")
    assert "/models" in spec["paths"]
    assert "/jobs/{id}" in spec["paths"]


def test_webhook_secret_rotation(client):
    user = _login(client)
    created = client.post("/api/webhooks", json={
        "url": "https://example.com/hook", "event_types": ["conversion.completed"],
    })
    assert created.status_code == 201
    webhook_id = created.get_json()["webhook"]["id"]
    original_secret = db.session.get(WebhookSubscription, webhook_id).secret

    rotated = client.post(f"/api/webhooks/{webhook_id}/rotate-secret")
    assert rotated.status_code == 200
    new_secret = rotated.get_json()["secret"]
    assert new_secret and new_secret != original_secret
    assert db.session.get(WebhookSubscription, webhook_id).secret == new_secret
