"""Additional format exports (Faz 4: "Ek format dışa aktarımları")."""

import os
import uuid

import trimesh

from app import app, db
from models import User, UserModel


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_model(user_id=None, visibility="unlisted"):
    model_id = "exp-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    box = trimesh.creation.box(extents=(0.1, 0.2, 0.3))
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(box).export(file_type="glb"))
    model = UserModel(id=model_id, filename=glb_path, file_type="glb",
                      file_size=os.path.getsize(glb_path), user_id=user_id,
                      cumulative_scale=1.0, visibility=visibility)
    db.session.add(model)
    db.session.commit()
    return model_id


def test_export_rejects_unsupported_format(client):
    model_id = make_model(user_id=None)
    resp = client.get(f"/api/models/{model_id}/export/fbx")
    assert resp.status_code == 400


def test_export_stl_succeeds_for_viewable_model(client):
    model_id = make_model(user_id=None)  # anonymous model, viewable by anyone
    resp = client.get(f"/api/models/{model_id}/export/stl")
    assert resp.status_code == 200
    assert len(resp.data) > 0
    # Round-trip through trimesh to confirm it's a real STL, not garbage.
    import io
    reloaded = trimesh.load(io.BytesIO(resp.data), file_type="stl")
    assert reloaded.vertices.shape[0] > 0


def test_export_obj_and_ply_succeed(client):
    model_id = make_model(user_id=None)
    for fmt in ("obj", "ply"):
        resp = client.get(f"/api/models/{model_id}/export/{fmt}")
        assert resp.status_code == 200, (fmt, resp.get_json())
        assert len(resp.data) > 0


def test_export_respects_view_permission(client):
    owner = User(username="exp-owner", email="exp-owner@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()

    model_id = make_model(user_id=owner.id, visibility="private")
    resp = client.get(f"/api/models/{model_id}/export/stl")
    assert resp.status_code == 403


def test_export_missing_model_404s(client):
    resp = client.get("/api/models/does-not-exist/export/stl")
    assert resp.status_code == 404


def test_export_denies_non_owner_even_of_a_viewable_unlisted_model(client):
    """STL/OBJ/PLY export is owner-tier, not view-tier: an unlisted model is
    viewable by anyone with the link, but only its owner may download the
    non-GLB re-export (GLB itself stays open to any viewer, served by a
    separate route that still uses the weaker view-permission check)."""
    owner = User(username="exp-owner2", email="exp-owner2@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()
    model_id = make_model(user_id=owner.id, visibility="unlisted")

    intruder = User(username="exp-intruder", email="exp-intruder@test.com")
    intruder.set_password("testpassword123")
    db.session.add(intruder)
    db.session.commit()
    login(client, "exp-intruder", "testpassword123")

    resp = client.get(f"/api/models/{model_id}/export/stl")
    assert resp.status_code == 403


def test_export_succeeds_for_the_owner_of_an_unlisted_model(client):
    owner = User(username="exp-owner3", email="exp-owner3@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()
    model_id = make_model(user_id=owner.id, visibility="unlisted")
    login(client, "exp-owner3", "testpassword123")

    resp = client.get(f"/api/models/{model_id}/export/stl")
    assert resp.status_code == 200
