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
from services import upload_pipeline
from app import app, db
from services.upload_pipeline import run_conversion_job
from models import ConversionJob, UserModel
from converters.glb_optimizer import _resolve_gltfpack, glb_needs_decompression


pytestmark = pytest.mark.skipif(
    _resolve_gltfpack() is None,
    reason="gltfpack unavailable; compression pipeline can't be exercised",
)


def _upload_compressed(client, monkeypatch):
    # Queue mode so /upload_model doesn't spawn a background conversion thread.
    # monkeypatch (not direct assignment) so this never leaks into other tests.
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
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

    # The edit decompresses to work, then re-applies the compression the
    # model was uploaded with (it must not silently stay bloated).
    db.session.refresh(model)
    assert glb_needs_decompression(model.glb_path)


def _upload(client, monkeypatch, compression):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    mesh = trimesh.creation.icosphere(subdivisions=3)
    resp = client.post(
        "/upload_model",
        data={"file": (io.BytesIO(mesh.export(file_type="stl")), "sphere.stl"),
              "compression": compression, "sourceUnit": "m"},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    job = db.session.get(ConversionJob, body["job_id"])
    run_conversion_job(job, allow_retry=False)
    return db.session.get(UserModel, body["job_id"]), body.get("edit_token")


def test_draco_model_can_be_sliced(client, monkeypatch):
    """The npm gltfpack can't decode Draco; gltf-transform must take over
    instead of the slice running on an unreadable file."""
    model, edit_token = _upload(client, monkeypatch, "draco")
    if not glb_needs_decompression(model.glb_path):
        pytest.skip("draco compression unavailable in this environment")

    resp = client.post("/slice_model", json={
        "model_id": model.id, "edit_token": edit_token,
        "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}],
    })

    assert resp.status_code == 200, resp.get_json()
    from converters.glb_optimizer import readable_glb
    with readable_glb(model.glb_path) as readable_path:
        extents = trimesh.load(readable_path, force="mesh").extents
    assert extents.min() > 0.5  # a real half-sphere, not a collapsed point


def test_edit_refused_when_compressed_file_cannot_be_decoded(client, monkeypatch):
    model, edit_token = _upload(client, monkeypatch, "meshopt")
    import converters.glb_optimizer as opt
    monkeypatch.setattr(opt, "_decompress_glb_to_temp", lambda path, timeout=120: None)
    before = open(model.glb_path, "rb").read()

    resp = client.post("/slice_model", json={
        "model_id": model.id, "edit_token": edit_token,
        "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}],
    })

    assert resp.status_code == 422
    assert open(model.glb_path, "rb").read() == before


def test_slice_that_flattens_the_model_is_not_saved(client, monkeypatch):
    model, edit_token = _upload(client, monkeypatch, "none")
    import mesh_slicer

    def flattening_slice(input_path, output_path, planes):
        trimesh.creation.box(extents=(0.0, 1, 1)).export(output_path)
        return {"success": True, "degenerate": True, "extents": [0.0, 1.0, 1.0]}

    monkeypatch.setattr(mesh_slicer, "slice_mesh_multi", flattening_slice)
    before = open(model.glb_path, "rb").read()

    resp = client.post("/slice_model", json={
        "model_id": model.id, "edit_token": edit_token,
        "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}],
    })

    assert resp.status_code == 422
    assert open(model.glb_path, "rb").read() == before


# ---- compressed models: dimensions, versions, thumbnails, recompression ----

def test_compressed_model_dimensions_endpoint_and_first_version(client, monkeypatch):
    """/get_model_dimensions used to 500 and the initial upload version was
    never created for a meshopt model (trimesh can't read it directly)."""
    from models import ModelVersion

    model, _ = _upload_compressed(client, monkeypatch)
    assert glb_needs_decompression(model.glb_path)

    resp = client.get(f"/get_model_dimensions/{model.id}")
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json()["dimensions"]["width"] == pytest.approx(200.0, rel=0.02)

    first = ModelVersion.query.filter_by(model_id=model.id, version_number=1).first()
    assert first is not None and first.operation_type == "upload"
    assert first.dimensions["max"] == pytest.approx(200.0, rel=0.02)


def test_compressed_model_thumbnail_renders(client, monkeypatch, tmp_path):
    from converters.thumbnail_render import render_thumbnail

    model, _ = _upload_compressed(client, monkeypatch)
    png = tmp_path / "t.png"
    assert render_thumbnail(model.glb_path, str(png)) is True
    assert png.stat().st_size > 0


def test_edit_reapplies_meshopt_compression(client, monkeypatch):
    """First edit used to strip compression for good (1.3 MB -> 6.9 MB)."""
    import os
    model, edit_token = _upload_compressed(client, monkeypatch)
    size_before = os.path.getsize(model.glb_path)

    resp = client.post("/save_modifications", json={
        "model_id": model.id, "edit_token": edit_token,
        "modifications": {"transform": {"scale": 2.0, "rotation": {"x": 0, "y": 0, "z": 0}}},
    })
    assert resp.status_code == 200, resp.get_json()
    db.session.refresh(model)

    assert glb_needs_decompression(model.glb_path), "compression must be re-applied after the edit"
    assert os.path.getsize(model.glb_path) < size_before * 2
    from converters.glb_optimizer import glb_compression_mode
    assert glb_compression_mode(model.glb_path) == "meshopt"
    # ...and the stored dimensions reflect the edit (readable via the endpoint).
    dims = client.get(f"/get_model_dimensions/{model.id}").get_json()["dimensions"]
    assert dims["width"] == pytest.approx(400.0, rel=0.02)


def test_failed_create_version_removes_copied_file(client, monkeypatch):
    import os
    from tests.test_viewer_page import make_two_material_model
    from version_manager import create_version

    model_id, glb_path = make_two_material_model(user_id=None)
    version_file = os.path.join(os.path.dirname(glb_path), "version_1.glb")

    def boom(*args, **kwargs):
        raise RuntimeError("cannot read")

    monkeypatch.setattr(trimesh, "load", boom)
    assert create_version(model_id, "upload") is None
    assert not os.path.exists(version_file), "orphaned version file must be cleaned up"
