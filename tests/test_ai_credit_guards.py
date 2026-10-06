"""AI cost guards: generate-3d hands the credit back on every rejected request,
and generate-image needs a remaining allowance."""

import pytest

import ai_generator
import app as app_module
from services import ai_jobs
from models import User, db

TINY_PNG_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


@pytest.fixture
def user(client, monkeypatch):
    u = User(username="guard", email="guard@test.com", ai_credit_balance=3)
    u.set_password("testpassword")
    db.session.add(u)
    db.session.commit()
    client.post("/login", data={"username": "guard", "password": "testpassword"})
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    return u


@pytest.fixture
def quota_exhausted(monkeypatch):
    # Monthly quota used up, so each allowed request is paid from credits.
    monkeypatch.setattr(ai_jobs, "_ai_quota_state", lambda user_id: (True, 0, 0))


def _balance(u):
    db.session.expire_all()
    return db.session.get(User, u.id).ai_credit_balance


@pytest.mark.parametrize("payload, status", [
    ({"mode": "text", "prompt": ""}, 400),
    ({"mode": "image", "image": "https://example.com/x.png"}, 400),
    ({"mode": "text", "prompt": "chair", "parent_job_id": "missing"}, 404),
])
def test_rejected_generate_3d_refunds_credit(client, user, quota_exhausted, payload, status):
    resp = client.post("/api/generate-3d", json=payload)

    assert resp.status_code == status
    assert _balance(user) == 3


def test_meshy_failure_refunds_credit(client, user, quota_exhausted, monkeypatch):
    def boom(*a, **k):
        raise ai_generator.MeshyError("upstream down")
    monkeypatch.setattr(ai_generator, "start_text_to_3d", boom)

    resp = client.post("/api/generate-3d", json={"mode": "text", "prompt": "chair"})

    assert resp.status_code == 502
    assert _balance(user) == 3


def test_started_generation_spends_one_credit(client, user, quota_exhausted, monkeypatch):
    monkeypatch.setattr(ai_generator, "start_text_to_3d", lambda *a, **k: "task-1")

    resp = client.post("/api/generate-3d", json={"mode": "text", "prompt": "chair"})

    assert resp.status_code == 200
    assert _balance(user) == 2


def test_generate_image_blocked_without_allowance(client, user, quota_exhausted, monkeypatch):
    user.ai_credit_balance = 0
    db.session.commit()
    called = []
    monkeypatch.setattr(ai_generator, "start_text_to_image",
                        lambda *a, **k: called.append(1) or "t2i-1")

    resp = client.post("/api/generate-image", json={"mode": "text", "prompt": "chair"})

    assert resp.status_code == 429
    assert not called


def test_generate_image_allowed_with_credit_and_does_not_spend_it(client, user, quota_exhausted, monkeypatch):
    monkeypatch.setattr(ai_generator, "start_text_to_image", lambda *a, **k: "t2i-1")

    resp = client.post("/api/generate-image", json={"mode": "text", "prompt": "chair"})

    assert resp.status_code == 200
    assert _balance(user) == 3


def _fail_task(monkeypatch):
    monkeypatch.setattr(ai_generator, "get_task", lambda kind, tid: {
        "id": tid, "status": ai_generator.FAILED, "progress": 10, "task_error": "boom"})


def test_failed_job_refunds_credit_exactly_once(client, user, quota_exhausted, monkeypatch):
    monkeypatch.setattr(ai_generator, "start_text_to_3d", lambda *a, **k: "task-1")
    job_id = client.post("/api/generate-3d", json={"mode": "text", "prompt": "chair"}).get_json()["job_id"]
    assert _balance(user) == 2
    _fail_task(monkeypatch)

    resp = client.get(f"/api/generate-3d/{job_id}/status")
    assert resp.get_json()["status"] == "failed"
    assert _balance(user) == 3

    # Re-polling, or running the refund path again, must not refund twice.
    client.get(f"/api/generate-3d/{job_id}/status")
    job = db.session.get(app_module.AIGenerationJob, job_id)
    ai_jobs._refund_ai_job_credit(job)
    assert _balance(user) == 3


def test_failed_job_without_credit_spent_is_not_refunded(client, user, monkeypatch):
    # Within the monthly quota: no credit consumed, so nothing to give back.
    monkeypatch.setattr(ai_jobs, "_ai_quota_state", lambda user_id: (False, 0, 5))
    monkeypatch.setattr(ai_generator, "start_text_to_3d", lambda *a, **k: "task-1")
    job_id = client.post("/api/generate-3d", json={"mode": "text", "prompt": "chair"}).get_json()["job_id"]
    _fail_task(monkeypatch)

    client.get(f"/api/generate-3d/{job_id}/status")

    assert _balance(user) == 3


def test_failed_jobs_do_not_count_toward_monthly_quota(client, user):
    for i, status in enumerate(("failed", "ready", "generating")):
        db.session.add(app_module.AIGenerationJob(
            id=f"quota-{i}", user_id=user.id, kind="text", status=status))
    db.session.commit()

    _, count, _ = ai_jobs._ai_quota_state(user.id)

    assert count == 2


def test_admin_mark_failed_refunds_credit(client, user):
    user.is_admin = True
    db.session.add(app_module.AIGenerationJob(
        id="stuck-1", user_id=user.id, kind="text", status="generating", credit_spent=True))
    db.session.commit()
    before = _balance(user)

    resp = client.post("/admin/ai-jobs/stuck-1/mark-failed")

    assert resp.status_code == 200
    assert _balance(user) == before + 1
