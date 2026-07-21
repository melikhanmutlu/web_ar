from models import User, UserModel, db


def _viewer_owner(client):
    # White-label branding is a Business-plan feature.
    owner = User(username="viewerowner", email="viewer-settings@example.com", plan="business")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model = UserModel(
        id="cccccccc-cccc-cccc-cccc-cccccccccccc",
        filename="unused.glb",
        user_id=owner.id,
        visibility="unlisted",
    )
    db.session.add(model)
    db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    return model


def test_viewer_white_label_and_section_settings(client):
    model = _viewer_owner(client)
    response = client.patch(f"/api/models/{model.id}/viewer-settings", json={
        "environment": "legacy",
        "background_color": "#112233",
        "exposure": 1.25,
        "shadow_intensity": 1.8,
        "auto_rotate": True,
        "auto_rotate_delay": 1500,
        "show_dimensions": True,
        "branding": {
            "name": "Acme 3D",
            "logo_url": "https://cdn.example/logo.svg",
            "primary_color": "#ffcc00",
            "hide_powered_by": True,
        },
        "section_presets": [
            {"name": "Half X", "axis": "x", "value": 0, "side": "positive"}
        ],
    })
    assert response.status_code == 200
    settings = response.get_json()["settings"]
    assert settings["branding"]["name"] == "Acme 3D"
    assert settings["section_presets"][0]["axis"] == "x"
    assert client.get(f"/api/models/{model.id}/viewer-settings").get_json()["settings"]["auto_rotate"] is True

    snippets = client.get(f"/api/models/{model.id}/integration-snippets")
    assert snippets.status_code == 200
    payload = snippets.get_json()
    assert "iframe" in payload["shopify_liquid"]
    assert "arvision_model" in payload["woocommerce_shortcode"]


def test_viewer_settings_validate_untrusted_branding_and_presets(client):
    model = _viewer_owner(client)
    assert client.patch(
        f"/api/models/{model.id}/viewer-settings",
        json={"branding": {"logo_url": "javascript:alert(1)"}},
    ).status_code == 400
    assert client.patch(
        f"/api/models/{model.id}/viewer-settings",
        json={"section_presets": [{"axis": "x", "value": "not-a-number"}]},
    ).status_code == 400
    response = client.patch(
        f"/api/models/{model.id}/viewer-settings",
        json={"show_ar": "false"},
    )
    assert response.status_code == 400
    assert "boolean" in response.get_json()["error"]
    assert client.patch(
        f"/api/models/{model.id}/viewer-settings",
        json={"ar_placement": "table"},
    ).status_code == 400


def test_ar_placement_defaults_to_floor_and_is_settable(client):
    model = _viewer_owner(client)
    assert client.get(
        f"/api/models/{model.id}/viewer-settings"
    ).get_json()["settings"]["ar_placement"] == "floor"

    response = client.patch(
        f"/api/models/{model.id}/viewer-settings", json={"ar_placement": "wall"}
    )
    assert response.status_code == 200
    assert response.get_json()["settings"]["ar_placement"] == "wall"
    assert client.get(
        f"/api/models/{model.id}/viewer-settings"
    ).get_json()["settings"]["ar_placement"] == "wall"
