"""Webhook subscriptions (CRUD) and delivery (services/webhooks.py)."""
import hashlib
import hmac
import io
import json

import pytest
import trimesh

import app as app_module
import services.webhooks as webhooks_service
from models import ConversionJob, User, WebhookSubscription, db
from services.webhooks import dispatch_webhook_event


@pytest.fixture
def logged_in(client):
    user = User(username="hooker", email="hooker@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "hooker", "password": "testpassword"},
                follow_redirects=True)
    return user


def test_create_webhook_requires_https(client, logged_in):
    response = client.post("/api/webhooks", json={
        "url": "http://example.com/hook", "event_types": ["conversion.completed"],
    })
    assert response.status_code == 400


def test_create_webhook_rejects_invalid_event_type(client, logged_in):
    response = client.post("/api/webhooks", json={
        "url": "https://example.com/hook", "event_types": ["not.a.real.event"],
    })
    assert response.status_code == 400


def test_create_list_and_delete_webhook(client, logged_in):
    create = client.post("/api/webhooks", json={
        "url": "https://example.com/hook",
        "event_types": ["conversion.completed", "conversion.failed"],
    })
    assert create.status_code == 201
    body = create.get_json()
    assert body["success"] is True
    webhook_id = body["webhook"]["id"]
    assert "secret" in body["webhook"]  # only exposed at creation

    listing = client.get("/api/webhooks").get_json()
    assert len(listing["webhooks"]) == 1
    assert "secret" not in listing["webhooks"][0]  # never re-exposed

    deletion = client.delete(f"/api/webhooks/{webhook_id}")
    assert deletion.status_code == 200
    assert WebhookSubscription.query.count() == 0


def test_other_users_webhooks_are_not_visible_or_deletable(client, logged_in):
    other = User(username="other-hooker", email="other-hooker@test.com")
    other.set_password("pw")
    db.session.add(other)
    db.session.commit()
    subscription = WebhookSubscription(
        user_id=other.id, url="https://example.com/x", secret="s",
        event_types="conversion.completed",
    )
    db.session.add(subscription)
    db.session.commit()

    assert client.get("/api/webhooks").get_json()["webhooks"] == []
    assert client.delete(f"/api/webhooks/{subscription.id}").status_code == 404


def test_dispatch_signs_payload_and_only_notifies_matching_active_subscriptions(client, logged_in, monkeypatch):
    matching = WebhookSubscription(
        user_id=logged_in.id, url="https://example.com/matching", secret="topsecret",
        event_types="conversion.completed,conversion.failed",
    )
    wrong_event = WebhookSubscription(
        user_id=logged_in.id, url="https://example.com/wrong-event", secret="s2",
        event_types="ai_generation.completed",
    )
    inactive = WebhookSubscription(
        user_id=logged_in.id, url="https://example.com/inactive", secret="s3",
        event_types="conversion.completed", is_active=False,
    )
    db.session.add_all([matching, wrong_event, inactive])
    db.session.commit()

    calls = []

    class FakeResponse:
        status_code = 200

    def fake_post(url, data=None, headers=None, timeout=None):
        calls.append((url, data, headers))
        return FakeResponse()

    monkeypatch.setattr(webhooks_service.requests, "post", fake_post)

    dispatch_webhook_event("conversion.completed", logged_in.id, {"model_id": "abc"})

    assert len(calls) == 1
    url, data, headers = calls[0]
    assert url == "https://example.com/matching"
    payload = json.loads(data)
    assert payload == {"event": "conversion.completed", "data": {"model_id": "abc"}}
    expected_sig = hmac.new(b"topsecret", data, hashlib.sha256).hexdigest()
    assert headers["X-ARVision-Signature"] == f"sha256={expected_sig}"
    assert headers["X-ARVision-Event"] == "conversion.completed"

    db.session.refresh(matching)
    assert matching.last_status_code == 200
    assert matching.last_triggered_at is not None


def test_dispatch_swallows_delivery_errors(client, logged_in, monkeypatch):
    subscription = WebhookSubscription(
        user_id=logged_in.id, url="https://example.com/down", secret="s",
        event_types="conversion.failed",
    )
    db.session.add(subscription)
    db.session.commit()

    import requests

    def fake_post(*a, **k):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(webhooks_service.requests, "post", fake_post)

    # Must not raise.
    dispatch_webhook_event("conversion.failed", logged_in.id, {"error": "oops"})

    db.session.refresh(subscription)
    assert subscription.last_status_code is None
    assert subscription.last_triggered_at is not None


def test_dispatch_noop_for_unknown_event_or_missing_user(client, logged_in, monkeypatch):
    calls = []
    monkeypatch.setattr(webhooks_service.requests, "post", lambda *a, **k: calls.append(1))
    dispatch_webhook_event("not.a.real.event", logged_in.id, {})
    dispatch_webhook_event("conversion.completed", None, {})
    assert calls == []


def test_conversion_pipeline_fires_completed_webhook(client, logged_in, monkeypatch):
    fired = []
    monkeypatch.setattr(app_module, "dispatch_webhook_event", lambda *a: fired.append(a))
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    source = trimesh.creation.box(extents=(0.1, 0.2, 0.3)).export(file_type="glb")
    response = client.post(
        "/upload_model",
        data={"file": (io.BytesIO(source), "box.glb"), "compression": "none"},
        content_type="multipart/form-data",
    )
    job = db.session.get(ConversionJob, response.get_json()["job_id"])

    app_module.run_conversion_job(job, allow_retry=False)

    assert len(fired) == 1
    event_type, user_id, payload = fired[0]
    assert event_type == "conversion.completed"
    assert user_id == logged_in.id
    assert payload["model_id"] == job.model_id
    import shutil
    shutil.rmtree(app_module.CONVERTED_FOLDER + "/" + job.model_id, ignore_errors=True)


def test_conversion_pipeline_fires_failed_webhook(client, logged_in, monkeypatch):
    fired = []
    monkeypatch.setattr(app_module, "dispatch_webhook_event", lambda *a: fired.append(a))

    def _boom(payload, progress_callback=None):
        raise RuntimeError("conversion exploded")
    monkeypatch.setattr(app_module, "_run_upload_pipeline", _boom)

    job = ConversionJob(
        id="webhook-fail-job", job_type="upload", status="pending",
        payload={}, user_id=logged_in.id,
    )
    db.session.add(job)
    db.session.commit()

    app_module.run_conversion_job(job, allow_retry=False)

    assert len(fired) == 1
    event_type, user_id, payload = fired[0]
    assert event_type == "conversion.failed"
    assert user_id == logged_in.id
    assert "conversion exploded" in payload["error"]
