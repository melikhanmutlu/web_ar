from models import ApiToken, ModelAnalyticsEvent, User, UserModel, db


def _token_owner():
    # API token minting is a paid feature (plan_allows api_access), so the
    # owner needs a plan that unlocks it.
    owner = User(username="apiowner", email="apiowner@example.com", plan="pro")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model = UserModel(
        id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        filename="unused.glb",
        display_name="API Chair",
        user_id=owner.id,
        visibility="private",
    )
    db.session.add(model)
    db.session.commit()
    return owner, model


def test_scoped_api_token_is_shown_once_and_authorizes_models(client):
    owner, model = _token_owner()
    client.post("/login", data={"username": owner.username, "password": "password"})
    created = client.post(
        "/api/tokens",
        json={"name": "Store integration", "scopes": ["models:read"], "expires_in_days": 30},
    )
    assert created.status_code == 201
    plaintext = created.get_json()["token"]
    token_id = created.get_json()["id"]
    stored = db.session.get(ApiToken, token_id)
    assert stored.token_digest != plaintext
    assert plaintext not in stored.token_digest

    response = client.get("/api/v1/models", headers={"Authorization": f"Bearer {plaintext}"})
    assert response.status_code == 200
    assert response.get_json()["data"][0]["name"] == "API Chair"
    assert stored.last_used_at is not None
    assert client.get(
        f"/api/v1/models/{model.id}/analytics",
        headers={"Authorization": f"Bearer {plaintext}"},
    ).status_code == 403

    listed = client.get("/api/tokens").get_json()["tokens"]
    assert "token" not in listed[0]
    assert client.delete(f"/api/tokens/{token_id}").status_code == 200
    assert client.get(
        "/api/v1/models", headers={"Authorization": f"Bearer {plaintext}"}
    ).status_code == 401


def test_analytics_scope_returns_only_owned_model_data(client):
    owner, model = _token_owner()
    db.session.add(ModelAnalyticsEvent(model_id=model.id, event_type="view", visitor_hash="x" * 64))
    db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    plaintext = client.post(
        "/api/tokens", json={"name": "Analytics", "scopes": ["analytics:read"]}
    ).get_json()["token"]
    response = client.get(
        f"/api/v1/models/{model.id}/analytics",
        headers={"Authorization": f"Bearer {plaintext}"},
    )
    assert response.status_code == 200
    assert response.get_json()["data"]["totals"] == {"view": 1}
    assert client.get(
        "/api/v1/models", headers={"Authorization": f"Bearer {plaintext}"}
    ).status_code == 403
