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
