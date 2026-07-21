"""Plan feature gates: free/unentitled users are blocked from paid actions,
while existing rows keep working (only creation/customization is gated)."""
from models import User, UserModel, db


def _login_free_user(client):
    user = User(username="freebie", email="free@example.com")  # no plan -> free
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": user.username, "password": "password"})
    return user


def test_free_user_cannot_create_organization(client):
    _login_free_user(client)
    response = client.post("/api/organizations", json={"name": "Startup"})
    assert response.status_code == 403
    assert "Business" in response.get_json()["error"]


def test_free_user_cannot_create_webhook(client):
    _login_free_user(client)
    response = client.post("/api/webhooks", json={
        "url": "https://example.com/hook", "event_types": ["conversion.completed"],
    })
    assert response.status_code == 403


def test_free_user_cannot_password_protect_share(client):
    user = _login_free_user(client)
    model = UserModel(
        id="0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f",
        filename="unused.glb", user_id=user.id, visibility="private",
    )
    db.session.add(model)
    db.session.commit()
    # A plain (no-password) share link is still allowed on the free plan.
    assert client.post(
        f"/api/models/{model.id}/share-links", json={"permission": "view"}
    ).status_code == 201
    # But adding a password requires a paid plan.
    gated = client.post(
        f"/api/models/{model.id}/share-links",
        json={"permission": "view", "password": "secret"},
    )
    assert gated.status_code == 403


def test_free_user_cannot_set_white_label_branding(client):
    user = _login_free_user(client)
    model = UserModel(
        id="1f1f1f1f-1f1f-1f1f-1f1f-1f1f1f1f1f1f",
        filename="unused.glb", user_id=user.id, visibility="unlisted",
    )
    db.session.add(model)
    db.session.commit()
    # Non-branding viewer settings are still editable on the free plan.
    assert client.patch(
        f"/api/models/{model.id}/viewer-settings", json={"auto_rotate": True}
    ).status_code == 200
    # Branding customization is gated.
    gated = client.patch(
        f"/api/models/{model.id}/viewer-settings",
        json={"branding": {"hide_powered_by": True}},
    )
    assert gated.status_code == 403
