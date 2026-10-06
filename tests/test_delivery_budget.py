"""P3D-14: surface the delivery budget to the owner and let them compress
the model for mobile (meshopt) through a background job."""

import os
import uuid

import pytest
import trimesh

import app as app_module
from services import upload_pipeline
from app import app, db
from services.upload_pipeline import run_conversion_job
from converters.glb_optimizer import _resolve_gltfpack, glb_needs_decompression
from models import ConversionJob, ModelVersion, User, UserModel
from services.time_utils import datetime

pytestmark = pytest.mark.skipif(
    _resolve_gltfpack() is None, reason="gltfpack unavailable"
)


def _user(username):
    user = User(username=username, email=f"{username}@test.com",
                email_verified_at=datetime.utcnow())
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, username):
    client.post("/login", data={"username": username, "password": "testpassword123"})


def _heavy_model(owner_id):
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.icosphere(subdivisions=4).export(glb_path)
    # Tiny budgets so the small fixture counts as "too heavy".
    report = app_module.AssetQualityService(
        warning_triangles=100, warning_bytes=1024
    ).inspect(glb_path)
    model = UserModel(id=model_id, filename=glb_path, file_type="glb",
                      file_size=os.path.getsize(glb_path), user_id=owner_id,
                      cumulative_scale=1.0, visibility="public",
                      validation_report=report)
    db.session.add(model)
    db.session.commit()
    return model_id, glb_path


def test_owner_sees_budget_warning_and_others_do_not(client):
    owner = _user("budget_owner")
    model_id, _ = _heavy_model(owner.id)
    _user("budget_other")

    _login(client, "budget_owner")
    body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert "Optimize for mobile" in body
    assert "it will load slowly on phones" in body
    client.post("/logout")

    _login(client, "budget_other")
    body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert "Optimize for mobile" not in body


def test_optimize_endpoint_rejects_non_owner(client, monkeypatch):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    owner = _user("opt_owner")
    model_id, glb_path = _heavy_model(owner.id)
    _user("opt_intruder")

    assert client.post(f"/api/models/{model_id}/optimize-mobile").status_code in (401, 403)
    _login(client, "opt_intruder")
    assert client.post(f"/api/models/{model_id}/optimize-mobile").status_code in (401, 403)
    assert ConversionJob.query.filter_by(job_type="optimize_mobile").count() == 0
    assert not glb_needs_decompression(glb_path)


def test_optimize_endpoint_compresses_bumps_version_and_snapshots(client, monkeypatch):
    # Queue mode: the endpoint only enqueues, we run the job ourselves.
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    owner = _user("opt_owner2")
    model_id, glb_path = _heavy_model(owner.id)
    size_before = os.path.getsize(glb_path)
    _login(client, "opt_owner2")

    resp = client.post(f"/api/models/{model_id}/optimize-mobile")
    assert resp.status_code == 202, resp.get_json()
    job = db.session.get(ConversionJob, resp.get_json()["job_id"])
    assert job.job_type == "optimize_mobile" and job.status == "pending"

    run_conversion_job(job, allow_retry=False)
    db.session.refresh(job)
    assert job.status == "completed", job.error

    db.session.expire_all()
    model = db.session.get(UserModel, model_id)
    assert glb_needs_decompression(glb_path)
    assert os.path.getsize(glb_path) < size_before
    assert model.asset_version >= 1
    assert model.file_size == os.path.getsize(glb_path)
    assert model.validation_report["triangles"] == 5120
    assert ModelVersion.query.filter_by(model_id=model_id, operation_type="optimize").count() == 1

    # Already compressed: no second job, and the viewer drops the button.
    assert client.post(f"/api/models/{model_id}/optimize-mobile").status_code == 409
    body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert "Optimize for mobile" not in body


def test_owner_banner_offers_simplify_with_budget_target(client):
    owner = _user("simp_banner_owner")
    model_id, _ = _heavy_model(owner.id)
    _login(client, "simp_banner_owner")
    body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert 'id="deliverySimplifyBtn"' in body
    assert 'data-target-triangles="100"' in body


def test_simplify_endpoint_validates_input_and_owner(client, monkeypatch):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    owner = _user("simp_val_owner")
    model_id, _ = _heavy_model(owner.id)
    _user("simp_val_other")
    url = f"/api/models/{model_id}/optimize-mobile"

    _login(client, "simp_val_other")
    assert client.post(url, json={"mode": "simplify", "target_triangles": 1000}).status_code in (401, 403)
    client.post("/logout")

    _login(client, "simp_val_owner")
    assert client.post(url, json={"mode": "bogus"}).status_code == 400
    assert client.post(url, json={"mode": "simplify", "target_triangles": "lots"}).status_code == 400
    assert client.post(url, json={"mode": "simplify", "target_triangles": 5120}).status_code == 400
    assert client.post(url, json={"mode": "simplify", "target_triangles": 5}).status_code == 400
    assert ConversionJob.query.filter_by(job_type="optimize_mobile").count() == 0


def test_simplify_job_reduces_triangles_keeps_original_and_invalidates_lods(client, monkeypatch):
    from models import ModelLOD
    from version_manager import version_path

    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    owner = _user("simp_owner")
    model_id, glb_path = _heavy_model(owner.id)
    lod_path = os.path.join(os.path.dirname(glb_path), "model_lod1.glb")
    with open(lod_path, "wb") as fh:
        fh.write(b"stale")
    db.session.add(ModelLOD(model_id=model_id, level=1, ratio=0.5, filename=lod_path, file_size=5))
    db.session.commit()
    _login(client, "simp_owner")

    resp = client.post(f"/api/models/{model_id}/optimize-mobile",
                       json={"mode": "simplify", "target_triangles": 1000})
    assert resp.status_code == 202, resp.get_json()
    job = db.session.get(ConversionJob, resp.get_json()["job_id"])
    assert job.payload["mode"] == "simplify" and job.payload["target_triangles"] == 1000
    run_conversion_job(job, allow_retry=False)
    db.session.refresh(job)
    assert job.status == "completed", job.error

    db.session.expire_all()
    model = db.session.get(UserModel, model_id)
    assert model.faces < 1500
    assert model.validation_report["triangles"] == model.faces
    assert model.asset_version >= 1
    assert ModelLOD.query.filter_by(model_id=model_id).count() == 0
    assert not os.path.exists(lod_path)
    versions = {v.operation_type: v for v in ModelVersion.query.filter_by(model_id=model_id)}
    assert set(versions) >= {"pre_simplify", "simplify"}
    assert versions["pre_simplify"].faces == 5120  # the original is recoverable
    assert os.path.isfile(version_path(versions["pre_simplify"]))
    assert versions["simplify"].faces == model.faces
