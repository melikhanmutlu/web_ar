"""Surviving a storage-root move between deploys.

UserModel.filename / usdz_filename and ModelVersion.filename store ABSOLUTE
paths captured at creation time. When the storage root changes between
deploys (a Railway volume gets attached, its mount path changes, or
STORAGE_ROOT is introduced), every old row points at a path that no longer
exists — even though the file is still sitting at the current
CONVERTED_FOLDER/<id>/. That made every pre-move model bounce off /view
with "Converted model file not found" while still listed in My Models.

Readers must resolve through UserModel.glb_path / usdz_path and
version_manager.version_path, which prefer the live layout.
"""

import os
import uuid

import pytest
import trimesh

from app import app, db
from models import UserModel, ModelVersion


def make_model_with_stale_path(user_id=None):
    """File lives at the CURRENT converted folder, but the DB row stores an
    absolute path from a previous deploy's storage root."""
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.Scene(trimesh.creation.box(extents=(0.2, 0.2, 0.2))).export(glb_path)

    usdz_path = os.path.join(model_dir, "model.usdz")
    with open(usdz_path, "wb") as f:
        f.write(b"fake-usdz")

    stale_root = "/data-old-mount-point/converted"
    model = UserModel(
        id=model_id,
        filename=os.path.join(stale_root, model_id, "model.glb"),
        usdz_filename=os.path.join(stale_root, model_id, "model.usdz"),
        file_type="glb", file_size=1000, user_id=user_id, cumulative_scale=1.0,
    )
    db.session.add(model)
    db.session.commit()
    return model


def test_glb_path_prefers_live_layout(client):
    model = make_model_with_stale_path()
    live = os.path.join(app.config["CONVERTED_FOLDER"], model.id, "model.glb")
    assert model.glb_path == live
    assert model.usdz_path == os.path.join(
        app.config["CONVERTED_FOLDER"], model.id, "model.usdz")


def test_glb_path_falls_back_to_stored_path(client):
    """A row whose file genuinely isn't in the live layout keeps returning
    the stored path (so exists-checks fail loudly instead of pointing at a
    directory that was never created)."""
    model_id = str(uuid.uuid4())
    model = UserModel(id=model_id, filename="/somewhere/else/model.glb",
                      file_type="glb", user_id=None)
    db.session.add(model)
    db.session.commit()
    assert model.glb_path == "/somewhere/else/model.glb"


def test_view_page_survives_storage_root_move(client):
    """The exact reported bug: model listed in My Models but /view/<id>
    redirected home with 'Converted model file not found' after a deploy."""
    model = make_model_with_stale_path()
    resp = client.get(f"/view/{model.id}")
    assert resp.status_code == 200, "viewer bounced a model whose file exists in the live layout"
    body = resp.get_data(as_text=True)
    assert "model-viewer" in body


def test_embed_and_vr_survive_storage_root_move(client):
    model = make_model_with_stale_path()
    assert client.get(f"/embed/{model.id}").status_code == 200
    assert client.get(f"/vr/{model.id}").status_code == 200


def test_usdz_status_survives_storage_root_move(client):
    model = make_model_with_stale_path()
    resp = client.get(f"/api/models/{model.id}/usdz_status")
    data = resp.get_json()
    assert data["success"] is True
    assert data["usdz_ready"] is True


def test_version_restore_survives_storage_root_move(client):
    """Version snapshots also store absolute paths — restore must resolve
    them against the current root."""
    from version_manager import create_version, restore_version

    model = make_model_with_stale_path()
    with app.app_context():
        v = create_version(model.id, "upload", comment="initial")
        assert v is not None
        # Simulate the row having been written under the old mount.
        version = ModelVersion.query.filter_by(model_id=model.id).first()
        version.filename = os.path.join(
            "/data-old-mount-point/converted", model.id,
            os.path.basename(version.filename))
        db.session.commit()

        assert restore_version(model.id, version.version_number) is True
