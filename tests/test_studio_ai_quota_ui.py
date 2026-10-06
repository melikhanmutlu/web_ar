"""UIA-23 / UIA-15: Studio AI tab quota messaging and upload limit rendering."""
import uuid

import pytest

import ai_generator
import app as app_module
from models import AIGenerationJob, User, db
from services.time_utils import datetime
from site_settings import invalidate_cache


@pytest.fixture
def free_ai(client, monkeypatch):
    invalidate_cache()
    monkeypatch.setitem(app_module.app.config, "AI_GEN_MONTHLY_LIMIT", 0)  # prod default for Free
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)


def _user(name, verified, **kw):
    u = User(username=name, email=f"{name}@test.com", plan=kw.pop("plan", "free"),
             email_verified_at=datetime.utcnow() if verified else None, **kw)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def _studio(client, name):
    client.post("/login", data={"username": name, "password": "testpassword123"})
    return client.get("/studio").get_data(as_text=True)


def test_unverified_free_user_sees_verify_cta_and_locked_button(client, free_ai):
    _user("q_unver", verified=False)
    html = _studio(client, "q_unver")
    assert "Verify your email to unlock 3 free AI generations" in html
    assert 'id="generateBtn" class="btn-primary" disabled data-locked="1"' in html
    assert "left today" not in html


def test_verified_free_user_sees_trial_remaining(client, free_ai):
    _user("q_trial", verified=True)
    html = _studio(client, "q_trial")
    assert "of 3 free trial generations left" in html
    assert 'data-locked="1"' not in html


def test_exhausted_trial_locks_button_with_upgrade_cta(client, free_ai):
    u = _user("q_done", verified=True)
    for i in range(3):
        db.session.add(AIGenerationJob(id=str(uuid.uuid4()), user_id=u.id, kind="text", status="ready"))
    db.session.commit()
    html = _studio(client, "q_done")
    assert "You've used all 3 free trial generations" in html
    assert 'data-locked="1"' in html
    assert "/pricing" in html


def test_credits_keep_generate_enabled_when_quota_is_zero(client, free_ai):
    _user("q_credit", verified=False, ai_credit_balance=2)
    html = _studio(client, "q_credit")
    assert 'data-locked="1"' not in html


def test_studio_renders_users_plan_upload_limit(client):
    from site_settings import set_setting
    set_setting("max_upload_mb", "7")
    try:
        html = client.get("/studio").get_data(as_text=True)
        assert "const UPLOAD_MAX_BYTES = 7340032;" in html
        assert "max. 7MB each" in html
    finally:
        set_setting("max_upload_mb", "0")
        invalidate_cache()
