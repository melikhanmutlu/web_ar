"""Best-effort email notifications (services/email.py) and their three hook
points: conversion completed, share link created, org member added."""
import io

import pytest
import trimesh

import app as app_module
import services.email as email_service
from models import ConversionJob, Organization, OrganizationMember, User, db
from services.email import send_email


class _FakeSMTP:
    sent = []
    fail = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        if _FakeSMTP.fail:
            raise OSError("smtp down")
        _FakeSMTP.sent.append(message)


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSMTP.sent = []
    _FakeSMTP.fail = False
    yield


@pytest.fixture
def email_enabled(client, monkeypatch):
    app = client.application
    app.config.update(
        EMAIL_NOTIFICATIONS_ENABLED=True, SMTP_HOST="smtp.test", SMTP_PORT=587,
        SMTP_USERNAME="", SMTP_PASSWORD="", SMTP_USE_TLS=True,
        SMTP_FROM_EMAIL="noreply@arvision.test",
    )
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    yield app


@pytest.fixture
def logged_in(client):
    user = User(username="mailuser", email="mailuser@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "mailuser", "password": "testpassword"},
                follow_redirects=True)
    return user


def test_send_email_noop_when_notifications_disabled(client):
    assert send_email("someone@test.com", "subj", "body") is False
    assert _FakeSMTP.sent == []


def test_send_email_noop_for_empty_recipient(email_enabled):
    assert send_email("", "subj", "body") is False


def test_send_email_delivers_via_smtp(email_enabled):
    assert send_email("someone@test.com", "Hello", "World") is True
    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]["To"] == "someone@test.com"
    assert _FakeSMTP.sent[0]["Subject"] == "Hello"


def test_send_email_swallows_smtp_errors(email_enabled):
    _FakeSMTP.fail = True
    assert send_email("someone@test.com", "Hello", "World") is False


def test_conversion_pipeline_emails_owner_on_completion(client, logged_in, email_enabled, monkeypatch):
    # Otherwise /upload_model's own inline background thread races this
    # test's explicit run_conversion_job call against the same job row.
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    source = trimesh.creation.box(extents=(0.1, 0.2, 0.3)).export(file_type="glb")
    response = client.post(
        "/upload_model",
        data={"file": (io.BytesIO(source), "box.glb"), "compression": "none"},
        content_type="multipart/form-data",
    )
    job = db.session.get(ConversionJob, response.get_json()["job_id"])

    app_module.run_conversion_job(job, allow_retry=False)

    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]["To"] == "mailuser@test.com"
    assert _FakeSMTP.sent[0]["Subject"] == "Your model is ready"
    import shutil
    shutil.rmtree(app_module.CONVERTED_FOLDER + "/" + job.model_id, ignore_errors=True)


def test_share_link_creation_emails_owner(client, logged_in, email_enabled):
    from models import UserModel
    model = UserModel(id="mail-share-model", filename="m.glb", user_id=logged_in.id)
    db.session.add(model)
    db.session.commit()

    response = client.post(f"/api/models/{model.id}/share-links", json={"permission": "view"})
    assert response.status_code == 201
    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]["To"] == "mailuser@test.com"
    assert _FakeSMTP.sent[0]["Subject"] == "Share link created"


def test_org_member_invite_emails_the_invited_user(client, logged_in, email_enabled):
    # Managing a team (adding members with seats) requires a Business plan.
    logged_in.plan = "business"
    org = Organization(name="Acme", slug="acme-mail", created_by=logged_in.id)
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=logged_in.id, role="owner"))
    invitee = User(username="invitee", email="invitee@test.com")
    invitee.set_password("pw")
    db.session.add(invitee)
    db.session.commit()

    response = client.post(
        f"/api/organizations/{org.id}/members",
        json={"email": "invitee@test.com", "role": "editor"},
    )
    assert response.status_code == 201
    assert len(_FakeSMTP.sent) == 1
    assert _FakeSMTP.sent[0]["To"] == "invitee@test.com"

    # Updating the role of an existing member does not re-send the invite email.
    client.post(
        f"/api/organizations/{org.id}/members",
        json={"email": "invitee@test.com", "role": "viewer"},
    )
    assert len(_FakeSMTP.sent) == 1
