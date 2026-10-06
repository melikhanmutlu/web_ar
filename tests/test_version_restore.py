"""Version restore integrity: history labels match content, the upload version
survives pruning, original_dimensions is untouched, and DB metadata + the
thumbnail follow the restored file."""

import os

import pytest

from app import app, db
from models import ModelVersion, UserModel
from tests.test_viewer_page import make_two_material_model
from version_manager import cleanup_old_versions, create_version


def _scaled_model(client):
    model_id, glb_path = make_two_material_model(user_id=None)
    model = db.session.get(UserModel, model_id)
    model.original_dimensions = {"x": 40.0, "y": 10.0, "z": 10.0, "max": 40.0}
    model.vertices, model.faces = 111, 222
    db.session.commit()
    assert create_version(model_id, "upload", None, "Initial upload") is not None  # v1
    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"transform": {"scale": 2.0, "rotation": {"x": 0, "y": 0, "z": 0}}},
    })
    assert resp.get_json()["success"] is True  # v2 = scaled
    return model_id, glb_path


def test_restore_records_backup_then_restored_version_with_correct_content(client):
    model_id, glb_path = _scaled_model(client)
    v1 = ModelVersion.query.filter_by(model_id=model_id, version_number=1).first()
    v2 = ModelVersion.query.filter_by(model_id=model_id, version_number=2).first()
    assert v2.dimensions["max"] == pytest.approx(v1.dimensions["max"] * 2, rel=1e-2)

    resp = client.post(f"/api/versions/{model_id}/restore/1")
    assert resp.status_code == 200, resp.get_json()

    db.session.expire_all()
    backup = ModelVersion.query.filter_by(model_id=model_id, version_number=3).first()
    restored = ModelVersion.query.filter_by(model_id=model_id, version_number=4).first()
    assert "Auto-backup before restoring version 1" in backup.comment
    # the backup holds the PRE-restore (scaled) state...
    assert backup.dimensions["max"] == pytest.approx(v2.dimensions["max"], rel=1e-2)
    # ...and "Restored from version 1" holds the restored content.
    assert restored.comment == "Restored from version 1"
    assert restored.dimensions["max"] == pytest.approx(v1.dimensions["max"], rel=1e-2)
    assert os.path.getsize(restored.filename) == os.path.getsize(glb_path)
    assert restored.operation_details["cumulative_scale_after"] == pytest.approx(1.0)


def test_restore_keeps_original_dimensions_and_updates_stats(client):
    model_id, glb_path = _scaled_model(client)
    model = db.session.get(UserModel, model_id)
    before_version = model.asset_version
    thumb = os.path.join(os.path.dirname(glb_path), "thumbnail.png")
    with open(thumb, "wb") as f:
        f.write(b"stale")

    assert client.post(f"/api/versions/{model_id}/restore/1").status_code == 200

    db.session.expire_all()
    model = db.session.get(UserModel, model_id)
    assert model.original_dimensions == {"x": 40.0, "y": 10.0, "z": 10.0, "max": 40.0}
    v1 = ModelVersion.query.filter_by(model_id=model_id, version_number=1).first()
    assert model.vertices == v1.vertices and model.faces == v1.faces
    assert model.file_size == os.path.getsize(glb_path)
    assert model.asset_version > before_version
    assert not os.path.exists(thumb) or open(thumb, "rb").read() != b"stale"


def test_cleanup_never_prunes_the_first_version(client):
    model_id, _ = make_two_material_model(user_id=None)
    for i in range(15):
        assert create_version(model_id, "transform", comment=f"edit {i}") is not None
    numbers = sorted(v.version_number for v in ModelVersion.query.filter_by(model_id=model_id))
    assert numbers[0] == 1 and len(numbers) == 10
    cleanup_old_versions(model_id, keep_last_n=3)
    numbers = sorted(v.version_number for v in ModelVersion.query.filter_by(model_id=model_id))
    assert numbers == [1, 14, 15]
