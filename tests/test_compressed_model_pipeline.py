"""A meshopt-compressed upload must still be measurable, sliceable, editable.

Root cause fixed here: the pipeline used to compress BEFORE its pygltflib
normalize/finalize steps, corrupting the meshopt buffer ("buffer too short"),
and trimesh can't decode meshopt at all -- so compressed models reported
0 x 0 x 0 dimensions, gave the slicer unmovable sliders, and refused every
edit. Now compression is the LAST pipeline step and edit/measure paths
decompress on demand.
"""
import io
import uuid

import pytest
import trimesh

import app as app_module
from app import app, db, run_conversion_job
from models import ConversionJob, UserModel
from converters.glb_optimizer import _resolve_gltfpack, glb_needs_decompression


pytestmark = pytest.mark.skipif(
    _resolve_gltfpack() is None,
    reason="gltfpack unavailable; compression pipeline can't be exercised",
)


def _upload_compressed(client, monkeypatch):
    # Queue mode so /upload_model doesn't spawn a background conversion thread.
    # monkeypatch (not direct assignment) so this never leaks into other tests.
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    # icosphere has enough geometry that meshopt compression actually engages
    mesh = trimesh.creation.icosphere(subdivisions=3)  # ~2 m diameter -> 200 cm
    resp = client.post(
        "/upload_model",
        data={
            "file": (io.BytesIO(mesh.export(file_type="stl")), "sphere.stl"),
            "compression": "meshopt",
            "sourceUnit": "m",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202, resp.get_json()
    body = resp.get_json()
    job = db.session.get(ConversionJob, body["job_id"])
    run_conversion_job(job, allow_retry=False)
    db.session.refresh(job)
    assert job.status == "completed", job.error
    return db.session.get(UserModel, body["job_id"]), body.get("edit_token")


def test_compressed_upload_is_valid_and_measured(client, monkeypatch):
    model, _ = _upload_compressed(client, monkeypatch)
    # It really is compressed (not silently left uncompressed)...
    assert glb_needs_decompression(model.glb_path)
    # ...yet dimensions are correct (200 cm sphere), not 0 x 0 x 0.
    import json
    bounds = json.loads(model.bounds)
    assert bounds["max"] == pytest.approx(200.0, rel=0.02), bounds


def test_compressed_model_reports_real_slicer_bounds(client, monkeypatch):
    model, _ = _upload_compressed(client, monkeypatch)
    from mesh_slicer import get_mesh_bounds

    gb = get_mesh_bounds(model.glb_path)
    assert gb is not None
    # Real extents, not a degenerate min==max (which would freeze the sliders).
    assert gb["min"]["x"] < gb["max"]["x"]
    assert gb["min"]["y"] < gb["max"]["y"]
    assert gb["min"]["z"] < gb["max"]["z"]


def test_compressed_model_can_be_sliced(client, monkeypatch):
    model, edit_token = _upload_compressed(client, monkeypatch)
    model_id = model.id

    resp = client.post("/slice_model", json={
        "model_id": model_id,
        "edit_token": edit_token,
        "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}],
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["success"] is True

    # Slicing an inherently-geometry-rewriting op leaves the model editable
    # (uncompressed) rather than a compressed dead end.
    db.session.refresh(model)
    assert not glb_needs_decompression(model.glb_path)
