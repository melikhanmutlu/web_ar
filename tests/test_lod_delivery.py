"""Phones get the lighter LOD on the read-only viewer and the embed page;
desktops, editors, stale/missing LODs and ?lod=full keep the full model."""

import os
import re
import uuid

import trimesh

from app import app, db
from models import ModelLOD, User, UserModel
from services import lod_delivery
from services.time_utils import datetime

MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
DESKTOP_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


def _owner(name="lod_owner"):
    user = User(username=name, email=f"{name}@test.com", email_verified_at=datetime.utcnow())
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def _model(owner_id, lods=((1, 0.5), (2, 0.25)), asset_version=3):
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.icosphere(subdivisions=4).export(glb_path)
    model = UserModel(id=model_id, filename=glb_path, file_type="glb",
                      file_size=os.path.getsize(glb_path), user_id=owner_id,
                      cumulative_scale=1.0, visibility="public", asset_version=asset_version)
    db.session.add(model)
    for level, ratio in lods:
        path = os.path.join(model_dir, f"model_lod{level}.glb")
        trimesh.creation.icosphere(subdivisions=max(1, 3 - level)).export(path)
        db.session.add(ModelLOD(model_id=model_id, level=level, ratio=ratio,
                                filename=path, file_size=os.path.getsize(path)))
    db.session.commit()
    return model_id, model_dir


def _viewer_src(html, tag_id):
    return re.search(rf'id="{tag_id}"[^>]*?\ssrc="([^"]+)"', html, re.S).group(1)


def test_mobile_viewer_gets_best_lod_at_or_below_half_with_cache_bust(client):
    model_id, _ = _model(_owner().id)
    html = client.get(f"/view/{model_id}", headers={"User-Agent": MOBILE_UA}).get_data(as_text=True)
    assert f"/converted_files/{model_id}/model_lod1.glb?v=3" in _viewer_src(html, "modelViewer")
    assert f'data-full-src="/converted_files/{model_id}/model.glb?v=3"' in html
    assert "js/viewer/lod-swap.js" in html


def test_desktop_viewer_keeps_full_model(client):
    model_id, _ = _model(_owner().id)
    html = client.get(f"/view/{model_id}", headers={"User-Agent": DESKTOP_UA}).get_data(as_text=True)
    assert f"/converted_files/{model_id}/model.glb?v=3" in _viewer_src(html, "modelViewer")
    assert "data-full-src" not in html and "lod-swap.js" not in html


def test_lod_query_override_forces_full_model(client):
    model_id, _ = _model(_owner().id)
    html = client.get(f"/view/{model_id}?lod=full", headers={"User-Agent": MOBILE_UA}).get_data(as_text=True)
    assert "model_lod" not in _viewer_src(html, "modelViewer")


def test_owner_on_mobile_gets_full_model_for_editing(client):
    owner = _owner()
    model_id, _ = _model(owner.id)
    client.post("/login", data={"username": "lod_owner", "password": "testpassword123"})
    html = client.get(f"/view/{model_id}", headers={"User-Agent": MOBILE_UA}).get_data(as_text=True)
    assert "model_lod" not in _viewer_src(html, "modelViewer")
    assert "lod-swap.js" not in html


def test_no_lod_stale_lod_or_missing_file_fall_back_to_full(client):
    owner = _owner()
    # No LOD rows at all.
    bare_id, _ = _model(owner.id, lods=())
    html = client.get(f"/view/{bare_id}", headers={"User-Agent": MOBILE_UA}).get_data(as_text=True)
    assert "model_lod" not in _viewer_src(html, "modelViewer")

    # LOD older than model.glb (model rewritten after the LOD was made).
    stale_id, stale_dir = _model(owner.id)
    glb = os.path.join(stale_dir, "model.glb")
    for name in ("model_lod1.glb", "model_lod2.glb"):
        old = os.path.getmtime(glb) - 3600
        os.utime(os.path.join(stale_dir, name), (old, old))
    html = client.get(f"/view/{stale_id}", headers={"User-Agent": MOBILE_UA}).get_data(as_text=True)
    assert "model_lod" not in _viewer_src(html, "modelViewer")

    # Row exists but the file is gone.
    gone_id, gone_dir = _model(owner.id)
    for name in ("model_lod1.glb", "model_lod2.glb"):
        os.remove(os.path.join(gone_dir, name))
    html = client.get(f"/view/{gone_id}", headers={"User-Agent": MOBILE_UA}).get_data(as_text=True)
    assert "model_lod" not in _viewer_src(html, "modelViewer")


def test_embed_serves_lod_to_mobile_only_and_varies_on_user_agent(client):
    model_id, _ = _model(_owner().id)
    mobile = client.get(f"/embed/{model_id}", headers={"User-Agent": MOBILE_UA})
    assert "model_lod1.glb?v=3" in _viewer_src(mobile.get_data(as_text=True), "viewer")
    assert "User-Agent" in mobile.headers.get("Vary", "")
    desktop = client.get(f"/embed/{model_id}", headers={"User-Agent": DESKTOP_UA})
    assert "model_lod" not in _viewer_src(desktop.get_data(as_text=True), "viewer")


def test_pick_lod_prefers_highest_ratio_not_above_half_else_lightest(client):
    model_id, _ = _model(_owner().id, lods=((1, 0.7), (2, 0.4), (3, 0.2)))
    model = db.session.get(UserModel, model_id)
    assert lod_delivery.pick_lod(model, MOBILE_UA).level == 2
    ModelLOD.query.filter_by(model_id=model_id, level=2).delete()
    ModelLOD.query.filter_by(model_id=model_id, level=3).delete()
    db.session.commit()
    assert lod_delivery.pick_lod(model, MOBILE_UA).level == 1
    assert lod_delivery.pick_lod(model, DESKTOP_UA) is None
    assert lod_delivery.pick_lod(model, None) is None
