"""In-product onboarding checklist (growth F3.4)."""

import uuid

from app import db
from models import (
    AIGenerationJob, ModelAnalyticsEvent, ModelShareLink, User, UserModel,
)
from services.onboarding import checklist_state


def _user(username):
    user = User(username=username, email=f"{username}@test.com")
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def _model(user, **kw):
    model = UserModel(id=str(uuid.uuid4()), filename="m/model.glb", user_id=user.id, **kw)
    db.session.add(model)
    db.session.commit()
    return model


def test_fresh_user_has_all_steps_incomplete(client):
    user = _user("ck_fresh")
    steps = checklist_state(user.id)
    assert steps is not None
    assert {s["key"] for s in steps} == {"upload", "ar", "share", "ai"}
    assert all(not s["done"] for s in steps)


def test_upload_marks_first_step_done(client):
    user = _user("ck_upl")
    _model(user)
    steps = {s["key"]: s["done"] for s in checklist_state(user.id)}
    assert steps["upload"] is True
    assert steps["ar"] is False


def test_ar_launch_event_marks_ar_step(client):
    user = _user("ck_ar")
    model = _model(user)
    db.session.add(ModelAnalyticsEvent(model_id=model.id, event_type="ar_launch"))
    db.session.commit()
    steps = {s["key"]: s["done"] for s in checklist_state(user.id)}
    assert steps["ar"] is True


def test_share_and_ai_steps(client):
    user = _user("ck_share")
    _model(user, share_count=2)                      # shared
    _model(user, source="ai-text")                   # AI-generated
    steps = {s["key"]: s["done"] for s in checklist_state(user.id)}
    assert steps["share"] is True
    assert steps["ai"] is True


def test_ai_job_alone_marks_ai_step(client):
    user = _user("ck_aijob")
    db.session.add(AIGenerationJob(id=str(uuid.uuid4()), user_id=user.id, kind="text"))
    db.session.commit()
    steps = {s["key"]: s["done"] for s in checklist_state(user.id)}
    assert steps["ai"] is True


def test_checklist_hidden_when_all_done(client):
    user = _user("ck_done")
    model = _model(user, share_count=1, source="ai-image")
    db.session.add(ModelAnalyticsEvent(model_id=model.id, event_type="ar_launch"))
    db.session.commit()
    assert checklist_state(user.id) is None


def test_checklist_renders_on_library_page(client):
    user = _user("ck_page")
    _model(user)
    client.post("/login", data={"username": "ck_page", "password": "testpassword123"})
    body = client.get("/my_models").get_data(as_text=True)
    assert "Get started" in body
    assert "Open it in AR" in body
