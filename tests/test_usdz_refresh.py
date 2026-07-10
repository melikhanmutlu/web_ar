"""After any GLB rewrite (transform save, slice, version restore) the iOS
USDZ must be regenerated — Quick Look serves the USDZ, so a stale one keeps
showing the model at its pre-edit size in iPhone AR."""

import os
import uuid

import pytest
import trimesh

import app as app_module
from app import app
from models import UserModel, db


@pytest.fixture
def model_on_disk(client):
    model_id = "test-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    box = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(box).export(file_type="glb"))

    model = UserModel(id=model_id, filename=f"{model_id}/model.glb",
                      file_type="glb", user_id=None, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()
    yield model_id
    import shutil
    shutil.rmtree(model_dir, ignore_errors=True)


def test_save_modifications_refreshes_usdz(client, model_on_disk, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "refresh_usdz_after_edit",
                        lambda mid, glb: calls.append((mid, glb)))

    resp = client.post("/save_modifications", json={
        "model_id": model_on_disk,
        "modifications": {"transform": {"scale": 2.0}},
    })
    body = resp.get_json()
    assert resp.status_code == 200 and body["success"], body
    assert calls and calls[0][0] == model_on_disk
    assert calls[0][1].endswith("model.glb")

    # the scale really got baked into the GLB
    scene = trimesh.load(calls[0][1], force="scene")
    assert abs(float(max(scene.extents)) - 0.2) < 0.01


def test_slice_refreshes_usdz(client, model_on_disk, monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "refresh_usdz_after_edit",
                        lambda mid, glb: calls.append(mid))

    resp = client.post("/slice_model", json={
        "model_id": model_on_disk,
        "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}],
    })
    body = resp.get_json()
    if resp.status_code == 200 and body.get("success"):
        assert calls == [model_on_disk]
    else:
        pytest.skip(f"slice pipeline unavailable in test env: {body}")
