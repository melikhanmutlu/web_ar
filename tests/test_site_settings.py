"""SiteSetting-backed runtime settings and their enforcement points:
registration toggle, AI daily limit, maintenance mode, upload size cap."""

import io

import pytest

import site_settings
from app import app, db
from models import AIGenerationJob, User


@pytest.fixture
def admin_user(client):
    user = User(username="adminuser", email="admin@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username, password):
    return client.post(
        "/login", data={"username": username, "password": password}
    )


@pytest.fixture(autouse=True)
def fresh_settings_cache():
    site_settings.invalidate_cache()
    yield
    site_settings.invalidate_cache()


def test_get_setting_falls_back_to_default(client):
    assert site_settings.get_setting("missing", "fallback") == "fallback"
    assert site_settings.setting_bool("missing", True) is True
    assert site_settings.setting_int("missing", 42) == 42


def test_set_and_read_back(client):
    site_settings.set_setting("ai_daily_limit", "3")
    assert site_settings.setting_int("ai_daily_limit", 10) == 3
    site_settings.set_setting("maintenance_mode", "true")
    assert site_settings.setting_bool("maintenance_mode") is True


def test_registration_can_be_disabled(client):
    site_settings.set_setting("registration_enabled", "false")
    response = client.post(
        "/register",
        data={
            "username": "newuser",
            "email": "new@test.com",
            "password": "password123",
            "confirm_password": "password123",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert User.query.filter_by(username="newuser").first() is None


def test_registration_enabled_by_default(client):
    response = client.post(
        "/register",
        data={
            "username": "newuser",
            "email": "new@test.com",
            "password": "password123",
            "confirm_password": "password123",
        },
    )
    assert response.status_code == 302
    assert User.query.filter_by(username="newuser").first() is not None


def test_ai_daily_limit_setting_overrides_config(client, init_database):
    from app import _ai_quota_state

    site_settings.set_setting("ai_daily_limit", "1")
    db.session.add(
        AIGenerationJob(id="ai-quota-1", user_id=init_database.id, kind="text")
    )
    db.session.commit()

    exceeded, count, limit = _ai_quota_state(init_database.id)
    assert limit == 1
    assert count == 1
    assert exceeded is True


def test_maintenance_mode_blocks_visitors_but_not_admins(client, admin_user):
    site_settings.set_setting("maintenance_mode", "true")

    assert client.get("/").status_code == 503
    # login stays reachable so admins can get in
    assert client.get("/login").status_code == 200

    login(client, "adminuser", "adminpassword")
    assert client.get("/").status_code == 200
    assert client.get("/admin/").status_code == 200

    site_settings.set_setting("maintenance_mode", "false")
    client.post("/logout")
    assert client.get("/").status_code == 200


def test_upload_size_limit_setting(client):
    site_settings.set_setting("max_upload_mb", "1")
    big = io.BytesIO(b"0" * (2 * 1024 * 1024))
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.stl")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413


def test_admin_can_save_settings_form(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post(
        "/admin/settings?tab=ai", data={"ai_daily_limit": "5"}, follow_redirects=False
    )
    assert response.status_code == 302
    site_settings.invalidate_cache()
    assert site_settings.setting_int("ai_daily_limit", 10) == 5

    # invalid value is rejected with a flash, not saved
    response = client.post(
        "/admin/settings?tab=ai", data={"ai_daily_limit": "nope"}
    )
    assert response.status_code == 302
    site_settings.invalidate_cache()
    assert site_settings.setting_int("ai_daily_limit", 10) == 5


def test_storage_quota_blocks_upload_when_exceeded(client, init_database):
    login(client, "testuser", "testpassword")
    site_settings.set_setting("storage_quota_mb", "1")
    big = io.BytesIO(b"0" * (2 * 1024 * 1024))
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.stl")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    assert b"Storage quota exceeded" in response.data


def test_storage_quota_zero_means_unlimited(client, init_database):
    login(client, "testuser", "testpassword")
    site_settings.set_setting("storage_quota_mb", "0")
    big = io.BytesIO(b"0" * (2 * 1024 * 1024))
    # .txt fails the extension check right after the quota gate — proves the
    # quota didn't block it without also spinning up the real conversion
    # pipeline (which the size of the quota check itself has no bearing on).
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code != 413


def test_anonymous_uploads_are_not_subject_to_storage_quota(client):
    site_settings.set_setting("storage_quota_mb", "1")
    big = io.BytesIO(b"0" * (2 * 1024 * 1024))
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code != 413


def test_admin_settings_uploads_tab_saves_storage_quota(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post(
        "/admin/settings?tab=uploads",
        data={"max_upload_mb": "50", "storage_quota_mb": "500"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    site_settings.invalidate_cache()
    assert site_settings.setting_int("storage_quota_mb", 0) == 500
