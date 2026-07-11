"""Multi-model scene builder (Faz 4: "Çoklu model sahne modu")."""

import os
import uuid

import trimesh

from app import app, db
from models import User, UserModel


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_model(user_id, extents=(0.1, 0.1, 0.1)):
    model_id = "scn-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    box = trimesh.creation.box(extents=extents)
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(box).export(file_type="glb"))
    model = UserModel(id=model_id, filename=glb_path, file_type="glb",
                      file_size=os.path.getsize(glb_path), user_id=user_id, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()
    return model_id


def test_build_scene_requires_login(client):
    resp = client.post("/api/scenes/build", json={"name": "x", "items": []})
    assert resp.status_code == 302


def test_build_scene_requires_at_least_two_items(client):
    owner = User(username="scnowner1", email="scnowner1@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()
    login(client, "scnowner1", "testpassword123")

    m1 = make_model(owner.id)
    resp = client.post("/api/scenes/build", json={
        "name": "Just one", "items": [{"model_id": m1}]})
    assert resp.status_code == 400


def test_build_scene_combines_two_models(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "_enqueue_internal_job", lambda *a, **k: None)

    owner = User(username="scnowner2", email="scnowner2@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()
    login(client, "scnowner2", "testpassword123")

    m1 = make_model(owner.id)
    m2 = make_model(owner.id)

    resp = client.post("/api/scenes/build", json={
        "name": "Living Room",
        "items": [
            {"model_id": m1, "position": {"x": 0, "y": 0, "z": 0}},
            {"model_id": m2, "position": {"x": 1, "y": 0, "z": 0}, "rotation_y": 90, "scale": 2},
        ],
    })
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["success"] is True
    new_model = db.session.get(UserModel, body["model_id"])
    assert new_model is not None
    assert new_model.user_id == owner.id
    assert os.path.exists(new_model.glb_path)

    combined = trimesh.load(new_model.glb_path, force="scene")
    assert len(combined.geometry) == 2


def test_build_scene_rejects_models_not_owned(client):
    owner = User(username="scnowner3", email="scnowner3@test.com")
    owner.set_password("testpassword123")
    other = User(username="scnother3", email="scnother3@test.com")
    other.set_password("testpassword123")
    db.session.add_all([owner, other])
    db.session.commit()

    m1 = make_model(owner.id)
    m2 = make_model(other.id)

    login(client, "scnowner3", "testpassword123")
    resp = client.post("/api/scenes/build", json={
        "name": "x", "items": [{"model_id": m1}, {"model_id": m2}]})
    assert resp.status_code == 404


def test_build_scene_rejects_invalid_scale(client):
    owner = User(username="scnowner4", email="scnowner4@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()
    login(client, "scnowner4", "testpassword123")

    m1 = make_model(owner.id)
    m2 = make_model(owner.id)
    resp = client.post("/api/scenes/build", json={
        "name": "x", "items": [{"model_id": m1}, {"model_id": m2, "scale": 999}]})
    assert resp.status_code == 400


def test_scene_builder_page_requires_login(client):
    resp = client.get("/scenes/new")
    assert resp.status_code == 302
