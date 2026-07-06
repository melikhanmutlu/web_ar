"""Phase D: Rigging + Animation (Meshy).

ai_generator's HTTP layer is monkeypatched throughout -- no real Meshy calls.
"""

import uuid
from datetime import datetime, timedelta

import pytest

import ai_generator
from app import app, db
from models import AIGenerationJob, RigAnimationJob, User, UserModel


@pytest.fixture
def owner(client):
    user = User(username="rigowner", email="rigowner@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def other_user(client):
    user = User(username="rigother", email="rigother@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def meshy_configured(monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=True)


def make_model(user_id=None, model_id=None, faces=None):
    model_id = model_id or str(uuid.uuid4())
    model = UserModel(id=model_id, filename=f"{model_id}/model.glb",
                      file_size=1234, file_type="glb", user_id=user_id, faces=faces)
    db.session.add(model)
    db.session.commit()
    return model


VALID_BODY = {"height_meters": 1.7, "animation_action_ids": [0, 1, 20]}


# --------------------------------------------------------------------------- #
#  Starting a rig job
# --------------------------------------------------------------------------- #

def test_rig_requires_login(client):
    model = make_model(faces=1000)
    resp = client.post(f"/api/models/{model.id}/rig", json=VALID_BODY)
    assert resp.status_code == 302


def test_rig_blocks_non_owner(client, owner, other_user, meshy_configured):
    model = make_model(user_id=owner.id, faces=1000)
    login(client, "rigother", "testpassword")
    resp = client.post(f"/api/models/{model.id}/rig", json=VALID_BODY)
    assert resp.status_code == 403


def test_rig_requires_meshy_configured(client, owner, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: False)
    model = make_model(user_id=owner.id, faces=1000)
    login(client, "rigowner", "testpassword")
    resp = client.post(f"/api/models/{model.id}/rig", json=VALID_BODY)
    assert resp.status_code == 503


def test_rig_validates_height(client, owner, meshy_configured):
    model = make_model(user_id=owner.id, faces=1000)
    login(client, "rigowner", "testpassword")
    resp = client.post(f"/api/models/{model.id}/rig",
                       json={"height_meters": 999, "animation_action_ids": [0]})
    assert resp.status_code == 400
    resp = client.post(f"/api/models/{model.id}/rig",
                       json={"animation_action_ids": [0]})
    assert resp.status_code == 400


def test_rig_requires_at_least_one_animation(client, owner, meshy_configured):
    model = make_model(user_id=owner.id, faces=1000)
    login(client, "rigowner", "testpassword")
    resp = client.post(f"/api/models/{model.id}/rig",
                       json={"height_meters": 1.7, "animation_action_ids": []})
    assert resp.status_code == 400


def test_rig_uploaded_model_uses_model_url(client, owner, meshy_configured, monkeypatch):
    model = make_model(user_id=owner.id, faces=1000)
    login(client, "rigowner", "testpassword")

    captured = {}

    def fake_start_rig(**kwargs):
        captured.update(kwargs)
        return "rig-task-1"

    monkeypatch.setattr(ai_generator, "start_rig", fake_start_rig)
    resp = client.post(f"/api/models/{model.id}/rig", json=VALID_BODY)
    body = resp.get_json()
    assert resp.status_code == 200, body

    assert captured.get("input_task_id") is None
    assert captured["model_url"].startswith("http")
    assert captured["height_meters"] == 1.7

    job = db.session.get(RigAnimationJob, body["job_id"])
    assert job.stage == "rigging"
    assert job.meshy_rig_id == "rig-task-1"
    assert job.animation_action_ids == [0, 1, 20]


def test_rig_ai_generated_model_uses_input_task_id(client, owner, meshy_configured, monkeypatch):
    model = make_model(user_id=owner.id, faces=1000)
    ai_job = AIGenerationJob(id=str(uuid.uuid4()), user_id=owner.id, kind="text",
                             prompt="a robot", stage="refine", meshy_preview_id="prev-1",
                             meshy_refine_id="refine-1", status="ready", model_id=model.id)
    db.session.add(ai_job)
    db.session.commit()
    login(client, "rigowner", "testpassword")

    captured = {}

    def fake_start_rig(**kwargs):
        captured.update(kwargs)
        return "rig-task-2"

    monkeypatch.setattr(ai_generator, "start_rig", fake_start_rig)
    resp = client.post(f"/api/models/{model.id}/rig", json=VALID_BODY)
    assert resp.status_code == 200, resp.get_json()
    assert captured["input_task_id"] == "refine-1"
    assert "model_url" not in captured or captured.get("model_url") is None


def test_rig_over_facelimit_upload_rejected(client, owner, meshy_configured):
    model = make_model(user_id=owner.id, faces=500000)
    login(client, "rigowner", "testpassword")
    resp = client.post(f"/api/models/{model.id}/rig", json=VALID_BODY)
    assert resp.status_code == 400
    assert "polygons" in resp.get_json()["error"].lower()


def test_rig_over_facelimit_ai_generated_triggers_remesh(client, owner, meshy_configured, monkeypatch):
    model = make_model(user_id=owner.id, faces=500000)
    ai_job = AIGenerationJob(id=str(uuid.uuid4()), user_id=owner.id, kind="text",
                             prompt="a robot", stage="refine", meshy_preview_id="prev-1",
                             meshy_refine_id="refine-1", status="ready", model_id=model.id)
    db.session.add(ai_job)
    db.session.commit()
    login(client, "rigowner", "testpassword")

    monkeypatch.setattr(ai_generator, "start_remesh", lambda task_id, **kw: "remesh-1")
    resp = client.post(f"/api/models/{model.id}/rig", json=VALID_BODY)
    body = resp.get_json()
    assert resp.status_code == 200, body

    job = db.session.get(RigAnimationJob, body["job_id"])
    assert job.stage == "remeshing"
    assert job.meshy_remesh_id == "remesh-1"


# --------------------------------------------------------------------------- #
#  Stage progression / finalize
# --------------------------------------------------------------------------- #

def _make_rig_job(user, model_id, stage="rigging", **kw):
    job = RigAnimationJob(id=str(uuid.uuid4()), model_id=model_id, user_id=user.id,
                          height_meters=1.7, animation_action_ids=[0, 1], stage=stage,
                          status="generating", progress=20, **kw)
    db.session.add(job)
    db.session.commit()
    return job


def test_full_progression_remesh_to_finalize(client, owner, meshy_configured, monkeypatch, tmp_path):
    from flask import current_app
    monkeypatch.setitem(current_app.config, "TEMP_FOLDER", str(tmp_path))

    model = make_model(user_id=owner.id, faces=1000)
    job = _make_rig_job(owner, model.id, stage="remeshing", meshy_remesh_id="remesh-1")
    login(client, "rigowner", "testpassword")

    monkeypatch.setattr(ai_generator, "get_remesh_task",
                        lambda tid: {"status": "SUCCEEDED", "progress": 100,
                                    "model_urls": {"glb": "https://assets.meshy.ai/remeshed.glb"},
                                    "task_error": None})
    monkeypatch.setattr(ai_generator, "start_rig", lambda **kw: "rig-1")
    resp = client.get(f"/api/rig-jobs/{job.id}/status")
    assert resp.status_code == 200, resp.get_json()
    db.session.refresh(job)
    assert job.stage == "rigging"
    assert job.meshy_rig_id == "rig-1"

    monkeypatch.setattr(ai_generator, "get_rig_task",
                        lambda tid: {"status": "SUCCEEDED", "progress": 100,
                                    "model_urls": {}, "task_error": None})
    monkeypatch.setattr(ai_generator, "start_animate", lambda rig_id, ids: "animate-1")
    resp = client.get(f"/api/rig-jobs/{job.id}/status")
    assert resp.status_code == 200, resp.get_json()
    db.session.refresh(job)
    assert job.stage == "animating"
    assert job.meshy_animate_id == "animate-1"

    def fake_download(url, dest):
        with open(dest, "wb") as f:
            f.write(b"fake-glb-bytes")
        return True

    monkeypatch.setattr(ai_generator, "download", fake_download)
    monkeypatch.setattr(ai_generator, "get_animate_task",
                        lambda tid: {"status": "SUCCEEDED", "progress": 100,
                                    "model_urls": {"glb": "https://assets.meshy.ai/animated.glb"},
                                    "task_error": None})

    import app as app_module

    def fake_register(glb_path, **kwargs):
        m = UserModel(id=str(uuid.uuid4()), filename=glb_path, file_size=10,
                     file_type="glb", user_id=kwargs.get("user_id"))
        db.session.add(m)
        db.session.commit()
        return m

    monkeypatch.setattr(app_module, "register_glb_as_model", fake_register)

    resp = client.get(f"/api/rig-jobs/{job.id}/status")
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["status"] == "ready"
    assert "viewer_url" in body

    db.session.refresh(job)
    assert job.status == "ready"
    assert job.result_model_id is not None
    assert job.result_model_id != model.id  # source model untouched, new model created

    # source model itself was never mutated
    db.session.refresh(model)
    assert model.filename == f"{model.id}/model.glb"


def test_rig_job_status_requires_ownership(client, owner, other_user, meshy_configured):
    model = make_model(user_id=owner.id, faces=1000)
    job = _make_rig_job(owner, model.id)
    login(client, "rigother", "testpassword")
    resp = client.get(f"/api/rig-jobs/{job.id}/status")
    assert resp.status_code == 403


def test_rig_claim_is_atomic(client, owner):
    model = make_model(user_id=owner.id, faces=1000)
    job = _make_rig_job(owner, model.id, stage="rigging", meshy_rig_id="rig-1")
    from app import _claim_rig_stage
    assert _claim_rig_stage(job.id, "rigging", "animating") is True
    assert _claim_rig_stage(job.id, "rigging", "animating") is False


# --------------------------------------------------------------------------- #
#  Reconciliation sweep
# --------------------------------------------------------------------------- #

def test_reconcile_advances_stale_rig_job(client, owner, monkeypatch):
    import worker

    model = make_model(user_id=owner.id, faces=1000)
    job = _make_rig_job(owner, model.id, stage="rigging", meshy_rig_id="rig-1")
    stale_cutoff = datetime.utcnow() - timedelta(minutes=worker.AI_RECONCILE_MINUTES + 1)
    RigAnimationJob.query.filter_by(id=job.id).update({"updated_at": stale_cutoff})
    db.session.commit()

    monkeypatch.setattr(ai_generator, "get_rig_task",
                        lambda tid: {"status": "SUCCEEDED", "progress": 100,
                                    "model_urls": {}, "task_error": None})
    monkeypatch.setattr(ai_generator, "start_animate", lambda rig_id, ids: "animate-9")

    with app.app_context():
        worker.reconcile_stale_rig_jobs()

    db.session.refresh(job)
    assert job.stage == "animating"
    assert job.meshy_animate_id == "animate-9"
