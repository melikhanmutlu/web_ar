"""Per-model visibility select on the my_models library card, and the
single-model sharing PATCH endpoint it calls (blueprints/model_metadata.py)."""

from models import User, UserModel, db


def _logged_in(client):
    user = User(username="visowner", email="visowner@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "visowner", "password": "testpassword"},
                follow_redirects=True)
    return user


def test_my_models_renders_per_model_visibility_control(client):
    user = _logged_in(client)
    model = UserModel(id="vis-model-1", filename="m.glb", user_id=user.id, visibility="unlisted")
    db.session.add(model)
    db.session.commit()

    page = client.get("/my_models").get_data(as_text=True)
    assert 'data-model-id="vis-model-1"' in page
    # Visibility is shown as a read-only pill and changed via the card's "..."
    # menu; a hidden <select> remains the value source wired to the sharing
    # endpoint (see updateModelVisibility / setModelVisibility in my_models.js).
    assert 'visibility-pill unlisted' in page
    assert 'visibility-select' in page
    assert '<option value="unlisted" selected>' in page
    assert "setModelVisibility('vis-model-1', 'public')" in page


def test_updating_visibility_via_sharing_endpoint_reflects_on_discover(client):
    user = _logged_in(client)
    model = UserModel(id="vis-model-2", filename="m.glb", user_id=user.id, visibility="unlisted")
    db.session.add(model)
    db.session.commit()

    assert "vis-model-2" not in client.get("/discover").get_data(as_text=True)

    resp = client.patch("/api/models/vis-model-2/sharing", json={"visibility": "public"})
    assert resp.status_code == 200
    assert resp.get_json()["visibility"] == "public"

    assert "vis-model-2" in client.get("/discover").get_data(as_text=True)


def test_sharing_endpoint_rejects_non_owner(client):
    owner = _logged_in(client)
    model = UserModel(id="vis-model-3", filename="m.glb", user_id=owner.id, visibility="private")
    db.session.add(model)
    db.session.commit()
    client.post("/logout")

    intruder = User(username="visintruder", email="visintruder@test.com")
    intruder.set_password("testpassword")
    db.session.add(intruder)
    db.session.commit()
    client.post("/login", data={"username": "visintruder", "password": "testpassword"})

    resp = client.patch("/api/models/vis-model-3/sharing", json={"visibility": "public"})
    assert resp.status_code == 403
