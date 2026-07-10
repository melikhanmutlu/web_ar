"""Phase C: webhook receiver + worker.py reconciliation sweep for stuck
AIGenerationJob rows (the "closed browser tab" problem).
"""

import uuid
from datetime import datetime, timedelta

import pytest

import ai_generator
from app import app, db
from models import AIGenerationJob, User

TINY_PNG_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


@pytest.fixture
def logged_in(client):
    user = User(username="reconcile", email="reconcile@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "reconcile", "password": "testpassword"},
                follow_redirects=True)
    return user


def _make_text_job(user, stage="preview", updated_at=None, preview_id="prev-1"):
    job = AIGenerationJob(id=str(uuid.uuid4()), user_id=user.id, kind="text",
                          prompt="vase", stage=stage,
                          meshy_preview_id=preview_id, status="generating", progress=49)
    db.session.add(job)
    db.session.commit()
    if updated_at is not None:
        AIGenerationJob.query.filter_by(id=job.id).update({"updated_at": updated_at})
        db.session.commit()
        db.session.refresh(job)
    return job


# --------------------------------------------------------------------------- #
#  Webhook receiver
# --------------------------------------------------------------------------- #

def test_webhook_advances_job_matching_task_id(client, logged_in, monkeypatch):
    job = _make_text_job(logged_in)
    monkeypatch.setattr(ai_generator, "get_task",
                        lambda kind, task_id: {"status": "SUCCEEDED", "progress": 100,
                                               "model_urls": {}, "thumbnail_url": None,
                                               "task_error": None})
    monkeypatch.setattr(ai_generator, "start_refine", lambda preview_id, **kw: "refine-1")

    # Meshy's own payload fields (status/model_urls) must never be trusted --
    # only task_id is read; job state always comes from a fresh get_task call.
    resp = client.post("/api/webhooks/meshy", json={
        "id": "prev-1", "status": "FAILED", "model_urls": {"glb": "https://evil/x.glb"},
    })
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}

    db.session.refresh(job)
    assert job.stage == "refine"
    assert job.meshy_refine_id == "refine-1"
    assert job.status == "generating"  # NOT "failed" -- payload's status was ignored


def test_webhook_returns_200_for_unknown_task_id(client):
    resp = client.post("/api/webhooks/meshy", json={"id": "no-such-task"})
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_webhook_returns_200_for_already_finished_job(client, logged_in):
    job = _make_text_job(logged_in)
    job.status = "ready"
    db.session.commit()
    resp = client.post("/api/webhooks/meshy", json={"id": "prev-1"})
    assert resp.status_code == 200


def test_webhook_returns_200_for_malformed_body(client):
    resp = client.post("/api/webhooks/meshy", data=b"not json",
                       content_type="application/json")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}


def test_webhook_does_not_require_csrf_token(client):
    """Meshy has no session/CSRF token; the route must be csrf-exempt."""
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = client.post("/api/webhooks/meshy", json={"id": "whatever"})
        assert resp.status_code == 200
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_webhook_survives_advance_exception(client, logged_in, monkeypatch):
    job = _make_text_job(logged_in)

    def boom(kind, task_id):
        raise ai_generator.MeshyError("upstream blew up")

    monkeypatch.setattr(ai_generator, "get_task", boom)
    resp = client.post("/api/webhooks/meshy", json={"id": "prev-1"})
    assert resp.status_code == 200  # error logged, not surfaced to Meshy


# --------------------------------------------------------------------------- #
#  worker.py reconciliation sweep
# --------------------------------------------------------------------------- #

def test_reconcile_advances_stale_job(client, logged_in, monkeypatch):
    import worker

    stale_cutoff = datetime.utcnow() - timedelta(minutes=worker.AI_RECONCILE_MINUTES + 1)
    job = _make_text_job(logged_in, updated_at=stale_cutoff)

    monkeypatch.setattr(ai_generator, "get_task",
                        lambda kind, task_id: {"status": "SUCCEEDED", "progress": 100,
                                               "model_urls": {}, "thumbnail_url": None,
                                               "task_error": None})
    monkeypatch.setattr(ai_generator, "start_refine", lambda preview_id, **kw: "refine-1")

    with app.app_context():
        worker.reconcile_stale_ai_jobs()

    db.session.refresh(job)
    assert job.stage == "refine"
    assert job.meshy_refine_id == "refine-1"


def test_reconcile_leaves_fresh_jobs_alone(client, logged_in, monkeypatch):
    import worker

    job = _make_text_job(logged_in)  # updated_at just set -- not stale

    calls = {"n": 0}

    def fake_get_task(kind, task_id):
        calls["n"] += 1
        return {"status": "IN_PROGRESS", "progress": 10, "model_urls": {},
                "thumbnail_url": None, "task_error": None}

    monkeypatch.setattr(ai_generator, "get_task", fake_get_task)

    with app.app_context():
        worker.reconcile_stale_ai_jobs()

    assert calls["n"] == 0
    db.session.refresh(job)
    assert job.stage == "preview"


def test_reconcile_continues_past_one_failing_job(client, logged_in, monkeypatch):
    import worker

    stale_cutoff = datetime.utcnow() - timedelta(minutes=worker.AI_RECONCILE_MINUTES + 1)
    job1 = _make_text_job(logged_in, updated_at=stale_cutoff, preview_id="prev-1")
    job2 = _make_text_job(logged_in, updated_at=stale_cutoff, preview_id="prev-2")

    def flaky_get_task(kind, task_id):
        if task_id == job1.meshy_preview_id:
            raise ai_generator.MeshyError("boom")
        return {"status": "SUCCEEDED", "progress": 100, "model_urls": {},
                "thumbnail_url": None, "task_error": None}

    monkeypatch.setattr(ai_generator, "get_task", flaky_get_task)
    monkeypatch.setattr(ai_generator, "start_refine", lambda preview_id, **kw: "refine-x")

    with app.app_context():
        worker.reconcile_stale_ai_jobs()  # must not raise

    db.session.refresh(job2)
    assert job2.stage == "refine"  # second job still got processed
