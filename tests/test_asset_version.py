"""asset_version: the ?v= cache-buster for GLB/USDZ/thumbnail URLs, bumped on
every rewrite of model.glb, and visibility-aware Cache-Control."""

import os
import re
import uuid

import trimesh

from app import app, db
from models import UserModel


def _make_model(visibility="public"):
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(glb_path)
    with open(os.path.join(model_dir, "thumbnail.png"), "wb") as f:
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGB", (4, 4)).save(buf, "PNG")
        f.write(buf.getvalue())
    model = UserModel(id=model_id, filename=glb_path, file_type="glb", file_size=1000,
                      user_id=None, cumulative_scale=1.0, visibility=visibility)
    db.session.add(model)
    db.session.commit()
    return model_id, glb_path


def _view_src_version(client, model_id):
    body = client.get(f"/view/{model_id}").get_data(as_text=True)
    m = re.search(r"/converted_files/[^\"']*model\.glb\?v=(\d+)", body)
    assert m, "viewer GLB url must carry ?v=<asset_version>"
    return int(m.group(1))


def test_asset_version_defaults_to_zero_and_bumps_on_save_and_slice(client):
    model_id, _ = _make_model()
    assert _view_src_version(client, model_id) == 0

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"transform": {"scale": 2.0, "rotation": {"x": 0, "y": 0, "z": 0}}},
    })
    assert resp.get_json()["success"] is True
    db.session.expire_all()
    after_save = _view_src_version(client, model_id)
    assert after_save >= 1

    resp = client.post("/slice_model", json={
        "model_id": model_id,
        "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0], "keep_side": "positive"}],
    })
    assert resp.get_json()["success"] is True, resp.get_json()
    db.session.expire_all()
    assert _view_src_version(client, model_id) > after_save


def test_non_public_models_are_not_publicly_cacheable(client):
    private_id, _ = _make_model(visibility="unlisted")
    public_id, _ = _make_model(visibility="public")

    r = client.get(f"/converted_files/{private_id}/model.glb")
    assert r.status_code == 200
    assert "private" in r.headers["Cache-Control"]
    assert "public" not in r.headers["Cache-Control"]
    r = client.get(f"/thumbnail/{private_id}")
    assert r.status_code == 200
    assert "private" in r.headers["Cache-Control"]
    assert "public" not in r.headers["Cache-Control"]

    r = client.get(f"/converted_files/{public_id}/model.glb")
    assert "public" in r.headers["Cache-Control"]
    r = client.get(f"/thumbnail/{public_id}")
    assert "public" in r.headers["Cache-Control"]
