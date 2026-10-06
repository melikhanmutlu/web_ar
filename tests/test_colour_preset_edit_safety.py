"""Colour change and material preset rewrite model.glb, so they must take the
per-model edit lock, cope with compressed files and bump asset_version."""

import functools
import os
import uuid

import pytest
import trimesh

import app as app_module
from app import app, db
from blueprints import model_editing
from converters.glb_optimizer import glb_compression_mode, optimize_glb, _resolve_gltfpack
from models import User, UserModel
from services.model_lock import ModelEditLock

needs_gltfpack = pytest.mark.skipif(_resolve_gltfpack() is None, reason="gltfpack unavailable")

ENDPOINTS = {
    "colour": lambda model_id, preset_id: ("/api/update-model-color", {"model_id": model_id, "color": "#3355ff"}),
    "preset": lambda model_id, preset_id: (f"/api/models/{model_id}/material-preset", {"preset_id": "system:steel"}),
}


def _owner_model(client, compress=False):
    user = User(username="edituser" + uuid.uuid4().hex[:6], email=f"{uuid.uuid4().hex[:8]}@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": user.username, "password": "testpassword"})
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.icosphere(subdivisions=4).export(glb_path)
    if compress:
        assert optimize_glb(glb_path, enabled=True, mode="meshopt")
    db.session.add(UserModel(id=model_id, filename=glb_path, file_type="glb",
                             file_size=os.path.getsize(glb_path), user_id=user.id,
                             cumulative_scale=1.0))
    db.session.commit()
    return model_id, glb_path


@pytest.mark.parametrize("kind", ["colour", "preset"])
def test_edit_is_refused_while_another_edit_holds_the_lock(client, monkeypatch, kind):
    model_id, glb_path = _owner_model(client)
    monkeypatch.setattr(model_editing, "ModelEditLock", functools.partial(ModelEditLock, timeout=0.2))
    before = open(glb_path, "rb").read()
    url, body = ENDPOINTS[kind](model_id, None)
    with ModelEditLock(os.path.dirname(glb_path)):
        resp = client.post(url, json=body)
    assert resp.status_code == 409, resp.get_json()
    assert open(glb_path, "rb").read() == before
    # Lock released afterwards: the same request now succeeds.
    assert client.post(url, json=body).status_code == 200


@needs_gltfpack
@pytest.mark.parametrize("kind", ["colour", "preset"])
def test_compressed_model_is_edited_and_stays_compressed(client, kind):
    model_id, glb_path = _owner_model(client, compress=True)
    assert glb_compression_mode(glb_path) == "meshopt"
    url, body = ENDPOINTS[kind](model_id, None)

    resp = client.post(url, json=body)

    assert resp.status_code == 200, resp.get_json()
    assert glb_compression_mode(glb_path) == "meshopt", "compression must be re-applied"
    db.session.expire_all()
    model = db.session.get(UserModel, model_id)
    assert model.asset_version >= 1
    assert model.validation_report["triangles"] == 5120
    assert model.file_size == os.path.getsize(glb_path)
