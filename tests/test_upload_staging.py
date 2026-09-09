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


@pytest.mark.parametrize("extension", ["step", "stp", "STEP", "STP"])
@pytest.mark.parametrize("packaged", [False, True])
def test_step_formats_are_staged(tmp_path, extension, packaged):
    service = UploadStagingService(tmp_path, max_uncompressed_bytes=1024 * 1024)
    content = Path("tests/fixtures/featuretype.step").read_bytes()
    name = f"part.{extension}"
    upload = (_zip_file("part.zip", {name: content}) if packaged else
              FileStorage(stream=io.BytesIO(content), filename=name))
    result = service.stage("step-job", upload)
    assert result["file_extension"] == f".{extension.lower()}"
    assert Path(result["temp_file_path"]).read_bytes() == content
    from services.conversion import ConversionService
    from converters import STEPConverter
    assert isinstance(ConversionService._converter(result), STEPConverter)


def test_step_batch_archive_is_staged(tmp_path):
    service = UploadStagingService(tmp_path, max_uncompressed_bytes=1024 * 1024)
    content = Path("tests/fixtures/featuretype.step").read_bytes()
    ids = iter(["step-job", "stp-job"])
    results = service.stage_archive_models(
        _zip_file("parts.zip", {"one.step": content, "two.stp": content}),
        lambda: next(ids),
    )
    assert {data["file_extension"] for _, data in results} == {".step", ".stp"}


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


def test_stage_archive_models_fans_out_each_model(tmp_path):
    service = UploadStagingService(tmp_path, max_uncompressed_bytes=1024 * 1024)
    upload = _zip_file("bundle.zip", {
        "a.obj": "mtllib a.mtl\nv 0 0 0\n",
        "a.mtl": "newmtl m\nmap_Kd a.png\n",
        "a.png": b"PNG",
        "b.stl": "solid\nendsolid\n",
        "sub/c.glb": b"glTF-ish",
    })
    counter = {"n": 0}

    def make_id():
        counter["n"] += 1
        return f"job-{counter['n']}"

    staged = service.stage_archive_models(upload, make_id)
    by_name = {s["client_filename"]: s for _, s in staged}
    assert set(by_name) == {"a.obj", "b.stl", "c.glb"}
    # The OBJ picked up its sibling .mtl + texture; the others didn't.
    assert by_name["a.obj"]["mtl_path"] and by_name["a.obj"]["mtl_path"].endswith("a.mtl")
    assert len(by_name["a.obj"]["texture_paths"]) == 1
    assert by_name["b.stl"]["mtl_path"] is None
    # Each model lands in its own independent job dir.
    dirs = {s["temp_dir"] for _, s in staged}
    assert len(dirs) == 3


def test_upload_multi_model_zip_returns_batch_response(client, monkeypatch):
    import trimesh
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("cube.stl", trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(file_type="stl"))
        archive.writestr("sphere.glb", trimesh.creation.icosphere(subdivisions=1).export(file_type="glb"))
    buffer.seek(0)

    resp = client.post(
        "/upload_model",
        data={"file": (buffer, "models.zip"), "compression": "none", "sourceUnit": "m"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202, resp.get_json()
    data = resp.get_json()
    assert data.get("multi") is True
    assert len(data["jobs"]) == 2
    names = sorted(j["filename"] for j in data["jobs"])
    assert names == ["cube.stl", "sphere.glb"]
    # Distinct, real, trackable jobs.
    for job in data["jobs"]:
        assert ConversionJob.query.get(job["job_id"]) is not None


def test_upload_single_model_zip_still_returns_one_job(client, monkeypatch):
    import trimesh
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("only.stl", trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(file_type="stl"))
    buffer.seek(0)

    resp = client.post(
        "/upload_model",
        data={"file": (buffer, "one.zip"), "compression": "none", "sourceUnit": "m"},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202, resp.get_json()
    data = resp.get_json()
    assert not data.get("multi")
    assert data.get("job_id")  # single-job (viewer-redirect) shape preserved


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
