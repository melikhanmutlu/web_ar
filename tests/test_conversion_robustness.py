"""Robustness fixes for FBX OOM / empty-geometry conversions:
  - empty/degenerate GLB fails the conversion instead of publishing a phantom
  - the upload-job status endpoint fails a stalled (orphaned) job so the UI
    recovers instead of spinning at the last percent forever
  - viewer/dimension endpoints don't 500 on a geometry-less model
"""

import os
import uuid
from datetime import datetime, timedelta

import trimesh

import app as app_module
from app import app, UPLOAD_STALL_SECONDS
from models import ConversionJob, db


def _make_processing_job(started_secs_ago):
    job_id = uuid.uuid4().hex
    job = ConversionJob(
        id=job_id, job_type="upload", status="processing",
        payload={"progress": 58, "stage": "Converting geometry"},
        started_at=datetime.utcnow() - timedelta(seconds=started_secs_ago),
        created_at=datetime.utcnow() - timedelta(seconds=started_secs_ago),
    )
    db.session.add(job)
    db.session.commit()
    return job_id


def test_stalled_job_is_failed_by_status_endpoint(client):
    job_id = _make_processing_job(UPLOAD_STALL_SECONDS + 30)
    body = client.get(f"/api/upload-jobs/{job_id}").get_json()
    assert body["success"] and body["status"] == "failed"
    assert "stalled" in (body.get("error") or "").lower()


def test_fresh_processing_job_is_left_alone(client):
    job_id = _make_processing_job(10)  # just started
    body = client.get(f"/api/upload-jobs/{job_id}").get_json()
    assert body["status"] == "processing"


def test_glb_has_geometry_detects_empty(tmp_path):
    from converters.fbx_converter import FBXConverter

    conv = FBXConverter.__new__(FBXConverter)  # no __init__ needed for this check
    conv.log_operation = lambda *a, **k: None

    good = tmp_path / "good.glb"
    good.write_bytes(trimesh.Scene(trimesh.creation.box((0.1, 0.1, 0.1))).export(file_type="glb"))
    assert conv._glb_has_geometry(str(good)) is True

    # Degenerate geometry: all vertices coincident -> zero extents
    # (mirrors FBX2glTF's ~353-byte zero-geometry output).
    import numpy as np
    degen = trimesh.Trimesh(vertices=np.zeros((3, 3)), faces=np.array([[0, 1, 2]]),
                            process=False)
    empty = tmp_path / "empty.glb"
    empty.write_bytes(trimesh.Scene(degen).export(file_type="glb"))
    assert conv._glb_has_geometry(str(empty)) is False


def test_viewer_does_not_500_on_empty_model(client):
    """A geometry-less model must render (dimensions 0), not crash."""
    model_id = "empty-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    import numpy as np
    degen = trimesh.Trimesh(vertices=np.zeros((3, 3)), faces=np.array([[0, 1, 2]]),
                            process=False)
    glb = os.path.join(model_dir, "model.glb")
    with open(glb, "wb") as f:
        f.write(trimesh.Scene(degen).export(file_type="glb"))

    from models import UserModel
    db.session.add(UserModel(id=model_id, filename=f"{model_id}/model.glb",
                             file_type="glb", user_id=None))
    db.session.commit()
    try:
        resp = client.get(f"/get_model_dimensions/{model_id}")
        assert resp.status_code == 200  # no 500 on geometry-less model
        dims = resp.get_json()["dimensions"]
        assert dims["width"] == 0.0 and dims["height"] == 0.0 and dims["depth"] == 0.0
    finally:
        import shutil
        shutil.rmtree(model_dir, ignore_errors=True)
