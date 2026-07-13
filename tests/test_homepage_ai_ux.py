"""Phase E: homepage "Generate with AI" UX -- live quota context, inline
result preview fields, UserModel.source tagging, admin origin filter/badge.
"""

import uuid

import pytest

import ai_generator
from app import db
from models import AIGenerationJob, User, UserModel


@pytest.fixture
def logged_in(client):
    user = User(username="uxuser", email="uxuser@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "uxuser", "password": "testpassword"},
                follow_redirects=True)
    return user


@pytest.fixture
def admin_user(client):
    user = User(username="uxadmin", email="uxadmin@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=False)


TINY_PNG_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


# --------------------------------------------------------------------------- #
#  Live quota on the homepage
# --------------------------------------------------------------------------- #

def test_homepage_shows_quota_for_logged_in_user(client, logged_in):
    resp = client.get("/app")
    assert resp.status_code == 200
    assert b"generations left today" in resp.data


def test_homepage_quota_reflects_existing_jobs_today(client, logged_in, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "setting_int", lambda key, default: 10)
    for _ in range(3):
        db.session.add(AIGenerationJob(id=str(uuid.uuid4()), user_id=logged_in.id,
                                       kind="text", prompt="x", stage="preview",
                                       status="generating"))
    db.session.commit()
    resp = client.get("/app")
    assert b'id="genQuotaRemaining">7<' in resp.data


def test_homepage_no_quota_banner_for_anonymous(client):
    resp = client.get("/app")
    assert resp.status_code == 200
    assert b"generations left today" not in resp.data


# --------------------------------------------------------------------------- #
#  Inline preview: status response includes a direct GLB URL
# --------------------------------------------------------------------------- #

def test_status_ready_includes_glb_url(client, logged_in, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)

    job_id = str(uuid.uuid4())
    from models import AIGenerationJob as Job
    job = Job(id=job_id, user_id=logged_in.id, kind="text", prompt="vase",
             stage="refine", meshy_refine_id="refine-1", status="generating", progress=90)
    db.session.add(job)
    db.session.commit()

    def fake_download(url, dest):
        with open(dest, "wb") as f:
            f.write(b"fake-glb")
        return True

    monkeypatch.setattr(ai_generator, "download", fake_download)
    monkeypatch.setattr(ai_generator, "get_task",
                        lambda kind, task_id: {"status": "SUCCEEDED", "progress": 100,
                                               "model_urls": {"glb": "https://assets.meshy.ai/m.glb"},
                                               "thumbnail_url": None, "task_error": None})

    resp = client.get(f"/api/generate-3d/{job_id}/status")
    body = resp.get_json()
    assert resp.status_code == 200, body
    assert body["status"] == "ready"
    assert "model_glb_url" in body
    assert body["model_id"] in body["model_glb_url"]


# --------------------------------------------------------------------------- #
#  UserModel.source tagging
# --------------------------------------------------------------------------- #

def test_register_glb_as_model_sets_source(client, logged_in, monkeypatch, tmp_path):
    from flask import current_app
    monkeypatch.setitem(current_app.config, "CONVERTED_FOLDER", str(tmp_path))
    monkeypatch.setitem(current_app.config, "TEMP_FOLDER", str(tmp_path))

    import trimesh
    glb_path = tmp_path / "src.glb"
    trimesh.creation.box().export(str(glb_path))

    from app import register_glb_as_model
    model = register_glb_as_model(str(glb_path), user_id=logged_in.id,
                                  source="ai-text", prompt="a box")
    assert model.source == "ai-text"

    db.session.refresh(model)
    assert model.source == "ai-text"


def test_plain_upload_has_no_source(client, logged_in):
    model = UserModel(id=str(uuid.uuid4()), filename="x/model.glb", file_size=10,
                      file_type="glb", user_id=logged_in.id)
    db.session.add(model)
    db.session.commit()
    assert model.source is None


# --------------------------------------------------------------------------- #
#  Admin: origin filter + badge
# --------------------------------------------------------------------------- #

def test_admin_models_origin_filter(client, admin_user):
    owner = User(username="uxowner1", email="uxowner1@test.com")
    owner.set_password("testpassword")
    db.session.add(owner)
    db.session.commit()
    ai_model = UserModel(id=str(uuid.uuid4()), filename="a/model.glb", file_size=10,
                         file_type="glb", user_id=owner.id, source="ai-text")
    upload_model = UserModel(id=str(uuid.uuid4()), filename="b/model.glb", file_size=10,
                             file_type="glb", user_id=owner.id, source=None)
    db.session.add_all([ai_model, upload_model])
    db.session.commit()

    login(client, "uxadmin", "adminpassword")

    resp = client.get("/admin/models?origin=ai")
    assert ai_model.id.encode() in resp.data
    assert upload_model.id.encode() not in resp.data

    resp = client.get("/admin/models?origin=upload")
    assert upload_model.id.encode() in resp.data
    assert ai_model.id.encode() not in resp.data

    resp = client.get("/admin/models")
    assert ai_model.id.encode() in resp.data
    assert upload_model.id.encode() in resp.data


def test_admin_models_shows_ai_badge(client, admin_user):
    owner = User(username="uxowner2", email="uxowner2@test.com")
    owner.set_password("testpassword")
    db.session.add(owner)
    db.session.commit()
    ai_model = UserModel(id=str(uuid.uuid4()), filename="a/model.glb", file_size=10,
                         file_type="glb", user_id=owner.id, source="ai-text")
    db.session.add(ai_model)
    db.session.commit()
    login(client, "uxadmin", "adminpassword")
    resp = client.get("/admin/models")
    assert b"ai-generated" in resp.data
