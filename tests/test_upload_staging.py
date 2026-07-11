import io
import shutil
import zipfile
from pathlib import Path

import pytest
from werkzeug.datastructures import FileStorage

import app as app_module
from models import ConversionJob
from services import UploadStagingError, UploadStagingService


def _zip_file(name, entries):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    buffer.seek(0)
    return FileStorage(stream=buffer, filename=name)


def test_zip_obj_bundle_is_safely_staged():
    root = Path(".test-upload-staging").resolve()
    service = UploadStagingService(root, max_uncompressed_bytes=1024 * 1024)
    upload = _zip_file("chair.zip", {
        "chair/chair.obj": "mtllib chair.mtl\nv 0 0 0\n",
        "chair/chair.mtl": "newmtl material\nmap_Kd texture.png\n",
        "chair/texture.png": b"PNG",
    })
    result = service.stage("zip-job", upload)
    assert result["file_extension"] == ".obj"
    assert result["mtl_path"].endswith("chair.mtl")
    assert len(result["texture_paths"]) == 1
    shutil.rmtree(root)


def test_zip_path_traversal_is_rejected():
    root = Path(".test-upload-traversal").resolve()
    service = UploadStagingService(root, max_uncompressed_bytes=1024 * 1024)
    upload = _zip_file("unsafe.zip", {"../escape.obj": "v 0 0 0"})
    with pytest.raises(UploadStagingError, match="Unsafe path"):
        service.stage("bad-job", upload)
    shutil.rmtree(root, ignore_errors=True)


def test_batch_upload_creates_independent_trackable_jobs(client, monkeypatch):
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    response = client.post(
        "/api/uploads/batch",
        data={
            "files": [
                (io.BytesIO(b"solid x endsolid x"), "one.stl"),
                (io.BytesIO(b"solid y endsolid y"), "two.stl"),
            ]
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    payload = response.get_json()
    assert len(payload["jobs"]) == 2
    assert ConversionJob.query.count() == 2
    for job in payload["jobs"]:
        assert job["status_token"]
        shutil.rmtree(Path(app_module.app.config["TEMP_FOLDER"]) / job["job_id"], ignore_errors=True)


def test_batch_upload_applies_shared_color_and_dimension_to_every_job(client, monkeypatch):
    """The batch endpoint used to hardcode use_color=False/max_dimension=None
    for every file regardless of the form -- these options are visible in the
    same upload form, so silently ignoring them for multi-file batches would
    be a footgun (user sets a color/size limit, uploads 3 files, none of them
    get it)."""
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    response = client.post(
        "/api/uploads/batch",
        data={
            "files": [
                (io.BytesIO(b"solid x endsolid x"), "one.stl"),
                (io.BytesIO(b"solid y endsolid y"), "two.stl"),
            ],
            "useColor": "true",
            "color": "#123456",
            "useMaxDimension": "true",
            "maxDimension": "25",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    payload = response.get_json()
    assert len(payload["jobs"]) == 2
    for job_summary in payload["jobs"]:
        job = ConversionJob.query.get(job_summary["job_id"])
        assert job.payload["use_color"] is True
        assert job.payload["color"] == "#123456"
        assert job.payload["max_dimension"] == pytest.approx(0.25)
        shutil.rmtree(Path(app_module.app.config["TEMP_FOLDER"]) / job.id, ignore_errors=True)


def test_batch_upload_rejects_invalid_max_dimension(client):
    response = client.post(
        "/api/uploads/batch",
        data={
            "files": [(io.BytesIO(b"solid x endsolid x"), "one.stl")],
            "useMaxDimension": "true",
            "maxDimension": "not-a-number",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 400
    assert ConversionJob.query.count() == 0
