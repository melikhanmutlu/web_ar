"""AI image pre-processing (text-to-image / image-to-image) endpoint tests.

ai_generator is monkeypatched throughout — no real Meshy calls.
"""

import pytest

import ai_generator
from models import AIGenerationJob, User, db

TINY_PNG_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


@pytest.fixture
def logged_in(client):
    user = User(username="imgen", email="imgen@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "imgen", "password": "testpassword"},
                follow_redirects=True)
    return user


@pytest.fixture
def meshy_configured(monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)


def test_generate_image_requires_config(client, logged_in, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: False)
    resp = client.post("/api/generate-image", json={"mode": "text", "prompt": "a vase"})
    assert resp.status_code == 503


def test_generate_image_text_flow(client, logged_in, meshy_configured, monkeypatch):
    monkeypatch.setattr(ai_generator, "start_text_to_image",
                        lambda prompt, aspect_ratio="1:1": "t2i-task-1")
    resp = client.post("/api/generate-image", json={"mode": "text", "prompt": "a vase"})
    body = resp.get_json()
    assert resp.status_code == 200 and body["success"], body
    assert body == {"success": True, "task_id": "t2i-task-1", "kind": "t2i"}

    monkeypatch.setattr(ai_generator, "get_image_gen_task",
                        lambda kind, task_id: {"status": "SUCCEEDED", "progress": 100,
                                               "image_urls": ["https://assets.meshy.ai/x.png"],
                                               "task_error": None})
    status = client.get("/api/generate-image/t2i-task-1/status?kind=t2i").get_json()
    assert status["status"] == "ready"
    assert status["image_urls"] == ["https://assets.meshy.ai/x.png"]


def test_generate_image_image_mode_validation(client, logged_in, meshy_configured):
    # missing prompt
    resp = client.post("/api/generate-image",
                       json={"mode": "image", "image": TINY_PNG_URI})
    assert resp.status_code == 400
    # bad image payload
    resp = client.post("/api/generate-image",
                       json={"mode": "image", "image": "https://evil.example/x.png",
                             "prompt": "clean it"})
    assert resp.status_code == 400


def test_generate_image_status_rejects_bad_kind(client, logged_in, meshy_configured):
    resp = client.get("/api/generate-image/whatever/status?kind=nope")
    assert resp.status_code == 400


def test_generate_3d_from_image_task(client, logged_in, meshy_configured, monkeypatch):
    """image_task references are resolved server-side and fed to image-to-3D."""
    captured = {}

    monkeypatch.setattr(ai_generator, "get_image_gen_task",
                        lambda kind, task_id: {"status": "SUCCEEDED", "progress": 100,
                                               "image_urls": ["https://assets.meshy.ai/gen.png"],
                                               "task_error": None})
    monkeypatch.setattr(ai_generator, "fetch_image_as_data_uri",
                        lambda url, max_bytes=0: TINY_PNG_URI)

    def fake_start_image_to_3d(image_data_uri):
        captured["image"] = image_data_uri
        return "img3d-task-9"

    monkeypatch.setattr(ai_generator, "start_image_to_3d", fake_start_image_to_3d)

    resp = client.post("/api/generate-3d", json={
        "mode": "image",
        "image_task": {"kind": "t2i", "task_id": "t2i-task-1", "index": 0},
    })
    body = resp.get_json()
    assert resp.status_code == 200 and body["success"], body
    assert captured["image"] == TINY_PNG_URI

    job = db.session.get(AIGenerationJob, body["job_id"])
    assert job is not None and job.meshy_image_id == "img3d-task-9"


def test_generate_3d_image_task_not_ready(client, logged_in, meshy_configured, monkeypatch):
    monkeypatch.setattr(ai_generator, "get_image_gen_task",
                        lambda kind, task_id: {"status": "IN_PROGRESS", "progress": 40,
                                               "image_urls": [], "task_error": None})
    resp = client.post("/api/generate-3d", json={
        "mode": "image",
        "image_task": {"kind": "t2i", "task_id": "t2i-task-1", "index": 0},
    })
    assert resp.status_code == 502  # surfaced as MeshyError


def test_generate_3d_still_rejects_raw_urls(client, logged_in, meshy_configured):
    """Raw URLs must never be accepted for the image field (SSRF guard)."""
    resp = client.post("/api/generate-3d", json={
        "mode": "image",
        "image": "https://internal.host/secret.png",
    })
    assert resp.status_code == 400
