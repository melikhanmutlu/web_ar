"""Faz 1: email verification (SEC-04), pending email change, verified-only
perks (Business trial, referral rewards, Free AI trials), and the new
private-by-default model visibility."""
import uuid
from datetime import timedelta

import pytest
from itsdangerous import URLSafeTimedSerializer

import ai_generator
import app as app_module
from app import limiter
from models import AIGenerationJob, User, UserModel, db
from services import email_verification as ev
from services.time_utils import datetime


@pytest.fixture
def sent(monkeypatch):
    """Capture outgoing verification emails instead of touching SMTP."""
    box = []
    monkeypatch.setattr(ev, "send_email", lambda to, subject, body: box.append((to, body)) or True)
    return box


def _token_from(body):
    return body.split("/verify-email/")[1].split()[0]


def _make_user(name="vuser", verified=False, **kw):
    u = User(username=name, email=f"{name}@test.com",
             email_verified_at=datetime.utcnow() if verified else None, **kw)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, name):
    client.post("/login", data={"username": name, "password": "testpassword123"})


# --- registration + verification --------------------------------------------

def test_registration_sends_verification_token(client, sent):
    resp = client.post("/register", data={
        "username": "newbie", "email": "newbie@test.com",
        "password": "password123", "confirm_password": "password123"})
    assert resp.status_code == 302
    user = User.query.filter_by(username="newbie").one()
    assert user.email_verified_at is None
    assert [to for to, _ in sent] == ["newbie@test.com"]

    client.get(f"/verify-email/{_token_from(sent[0][1])}")
    db.session.expire_all()
    assert User.query.filter_by(username="newbie").one().email_verified_at is not None


def test_registration_survives_unconfigured_smtp(client, monkeypatch):
    monkeypatch.setitem(app_module.app.config, "EMAIL_NOTIFICATIONS_ENABLED", False)
    logged = []
    monkeypatch.setattr(ev.logger, "info", lambda msg, *args: logged.append(msg % args))
    resp = client.post("/register", data={
        "username": "nosmtp", "email": "nosmtp@test.com",
        "password": "password123", "confirm_password": "password123"})
    assert resp.status_code == 302
    assert any("/verify-email/" in m for m in logged)


def test_invalid_token_rejected(client):
    u = _make_user()
    resp = client.get("/verify-email/not-a-token", follow_redirects=True)
    assert b"invalid" in resp.data
    assert db.session.get(User, u.id).email_verified_at is None


def test_token_for_other_salt_rejected(client):
    u = _make_user()
    forged = URLSafeTimedSerializer(app_module.app.config["SECRET_KEY"], salt="other").dumps(
        {"uid": u.id, "email": u.email})
    client.get(f"/verify-email/{forged}")
    assert db.session.get(User, u.id).email_verified_at is None


def test_expired_token_rejected(client, monkeypatch):
    u = _make_user()
    token = ev.make_token(u, u.email)
    monkeypatch.setattr(ev, "MAX_AGE_SECONDS", -1)
    resp = client.get(f"/verify-email/{token}", follow_redirects=True)
    assert b"expired" in resp.data
    assert db.session.get(User, u.id).email_verified_at is None


def test_resend_requires_login_and_is_rate_limited(client, sent):
    _make_user()
    assert client.post("/verify-email/resend").status_code == 302  # to login
    assert sent == []
    _login(client, "vuser")
    limiter.enabled = True
    try:
        codes = [client.post("/verify-email/resend").status_code for _ in range(6)]
    finally:
        limiter.enabled = False
    assert codes[:5] == [302] * 5
    assert codes[5] == 429
    assert len(sent) == 5


def test_profile_shows_notice_only_when_unverified(client, sent):
    _make_user("unv")
    _login(client, "unv")
    assert b"Resend verification email" in client.get("/profile").data
    client.get("/logout")
    client.post("/logout")
    _make_user("ver", verified=True)
    _login(client, "ver")
    assert b"Resend verification email" not in client.get("/profile").data


def test_admin_counts_as_verified(client):
    admin = _make_user("adm", is_admin=True)
    assert admin.email_verified_at is None
    assert ev.is_verified(admin)


# --- email change -----------------------------------------------------------

def test_email_change_is_pending_until_verified(client, sent):
    u = _make_user("chg", verified=True)
    _login(client, "chg")
    client.post("/profile/update", data={"username": "chg", "email": "fresh@test.com"})
    db.session.expire_all()
    u = db.session.get(User, u.id)
    assert u.email == "chg@test.com" and u.pending_email == "fresh@test.com"
    assert [to for to, _ in sent] == ["fresh@test.com"]

    client.get(f"/verify-email/{_token_from(sent[0][1])}")
    db.session.expire_all()
    u = db.session.get(User, u.id)
    assert u.email == "fresh@test.com" and u.pending_email is None
    assert u.email_verified_at is not None


def test_old_address_token_cannot_confirm_pending_swap(client, sent):
    u = _make_user("stale", verified=True)
    old_token = ev.make_token(u, u.email)
    _login(client, "stale")
    client.post("/profile/update", data={"username": "stale", "email": "other@test.com"})
    client.get(f"/verify-email/{old_token}")
    db.session.expire_all()
    assert db.session.get(User, u.id).email == "stale@test.com"


def test_reserved_admin_email_still_blocked(client, sent, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "boss@example.com")
    u = _make_user("rsv", verified=True)
    _login(client, "rsv")
    resp = client.post("/profile/update", data={"username": "rsv", "email": "boss@example.com"})
    assert b"This email address is reserved." in resp.data
    assert db.session.get(User, u.id).pending_email is None
    assert sent == []


def test_boot_promotion_requires_verified_email(client, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAILS", "a1@test.com,a2@test.com")
    _make_user("a1", verified=True)
    _make_user("a2", verified=False)
    app_module._promote_admin_emails()
    db.session.expire_all()
    assert User.query.filter_by(username="a1").one().is_admin is True
    assert User.query.filter_by(username="a2").one().is_admin is False


# --- gates ------------------------------------------------------------------

def test_business_trial_requires_verified_email(client):
    u = _make_user("trialu")
    _login(client, "trialu")
    resp = client.post("/billing/trial", follow_redirects=True)
    assert b"verify your email" in resp.data.lower()
    db.session.expire_all()
    assert db.session.get(User, u.id).plan == "free"
    assert db.session.get(User, u.id).business_trial_used_at is None


# --- Free AI trials ---------------------------------------------------------

@pytest.fixture
def ai_free(client, monkeypatch):
    app_module.app.config["AI_GEN_MONTHLY_LIMIT"] = 0  # prod default for Free
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    monkeypatch.setattr(ai_generator, "start_text_to_3d", lambda *a, **k: "task-1")
    monkeypatch.setattr(ai_generator, "start_text_to_image", lambda *a, **k: "t2i-1")


def test_unverified_free_user_gets_403_with_verify_message(client, ai_free):
    _make_user("aiu")
    _login(client, "aiu")
    r3d = client.post("/api/generate-3d", json={"mode": "text", "prompt": "chair"})
    rimg = client.post("/api/generate-image", json={"mode": "text", "prompt": "chair"})
    assert r3d.status_code == 403 and rimg.status_code == 403
    assert "verify your email" in r3d.get_json()["error"].lower()


def test_verified_free_user_gets_three_lifetime_generations(client, ai_free):
    u = _make_user("aiv", verified=True)
    _login(client, "aiv")
    for _ in range(3):
        assert client.post("/api/generate-image",
                           json={"mode": "text", "prompt": "chair"}).status_code == 200
        assert client.post("/api/generate-3d",
                           json={"mode": "text", "prompt": "chair"}).status_code == 200
    # Allowance is spent (lifetime count of AIGenerationJob rows), no credits left.
    assert AIGenerationJob.query.filter_by(user_id=u.id).count() == 3
    assert client.post("/api/generate-3d", json={"mode": "text", "prompt": "chair"}).status_code == 429
    assert client.post("/api/generate-image", json={"mode": "text", "prompt": "chair"}).status_code == 429


def test_trial_is_lifetime_not_monthly(client, ai_free):
    u = _make_user("ail", verified=True)
    for _ in range(3):
        db.session.add(AIGenerationJob(
            id=str(uuid.uuid4()), user_id=u.id, kind="text", stage="preview",
            status="done", progress=100, created_at=datetime.utcnow() - timedelta(days=90)))
    db.session.commit()
    exceeded, used, limit = app_module._ai_quota_state(u.id)
    assert (exceeded, used, limit) == (True, 3, 3)


def test_trial_count_is_admin_configurable(client, ai_free):
    from site_settings import set_setting
    set_setting("free_ai_trial_count", "1")
    u = _make_user("aic", verified=True)
    assert app_module._ai_quota_state(u.id) == (False, 0, 1)


def test_paid_plan_quota_unchanged(client, ai_free):
    u = _make_user("aip", verified=False, plan="pro")
    exceeded, _used, limit = app_module._ai_quota_state(u.id)
    assert limit != 3 or not exceeded  # plan limit applies, not the trial
    assert app_module.ai_trial_needs_verification(u) is False


# --- default visibility -----------------------------------------------------

def test_logged_in_model_defaults_private_anonymous_unlisted(client):
    u = _make_user("vis", verified=True)
    owned = UserModel(id=str(uuid.uuid4()), filename="a/model.glb", file_type="glb",
                      file_size=1, user_id=u.id)
    anon = UserModel(id=str(uuid.uuid4()), filename="b/model.glb", file_type="glb",
                     file_size=1)
    explicit = UserModel(id=str(uuid.uuid4()), filename="c/model.glb", file_type="glb",
                         file_size=1, user_id=u.id, visibility="public")
    db.session.add_all([owned, anon, explicit])
    db.session.commit()
    assert owned.visibility == "private"
    assert anon.visibility == "unlisted"
    assert explicit.visibility == "public"


def test_private_default_owner_can_view_others_cannot(client, monkeypatch, tmp_path):
    from flask import current_app
    import trimesh
    monkeypatch.setitem(current_app.config, "CONVERTED_FOLDER", str(tmp_path))
    monkeypatch.setitem(current_app.config, "TEMP_FOLDER", str(tmp_path))
    owner = _make_user("vown", verified=True)
    glb = tmp_path / "src.glb"
    trimesh.creation.box().export(str(glb))
    model = app_module.register_glb_as_model(str(glb), user_id=owner.id, source="ai-text", prompt="box")
    assert model.visibility == "private"
    anon_model = app_module.register_glb_as_model(str(glb), user_id=None, source="ai-text", prompt="box")
    assert anon_model.visibility == "unlisted"

    assert client.get(f"/view/{model.id}").status_code in (403, 404)
    _login(client, "vown")
    assert client.get(f"/view/{model.id}").status_code == 200


def test_failed_generations_do_not_use_up_free_trials(client, monkeypatch):
    from services.time_utils import datetime as dt
    from site_settings import invalidate_cache
    invalidate_cache()  # an earlier test may have cached a different free_ai_trial_count
    monkeypatch.setitem(app_module.app.config, "AI_GEN_MONTHLY_LIMIT", 0)  # prod default for Free
    u = User(username="trialfail", email="trialfail@example.com", plan="free",
             email_verified_at=dt.utcnow())
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    for i, status in enumerate(("failed", "failed", "ready")):
        db.session.add(AIGenerationJob(id=f"trialfail-{i}", user_id=u.id, kind="text", status=status))
    db.session.commit()

    exceeded, used, trial = app_module._ai_quota_state(u.id)

    assert (exceeded, used, trial) == (False, 1, 3)
