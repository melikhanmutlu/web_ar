"""Admin panel tests: access control, lockout guards, cascade deletes,
model purge, job retry and the make-admin CLI."""

import os

import pytest

from app import app, db
from models import (
    AIGenerationJob,
    ConversionJob,
    Folder,
    ModelLike,
    ModelSave,
    User,
    UserModel,
)

ADMIN_GET_PAGES = [
    "/admin/",
    "/admin/users",
    "/admin/models",
    "/admin/jobs",
    "/admin/ai-jobs",
    "/admin/analytics",
    "/admin/settings",
    "/admin/audit-log",
]


@pytest.fixture
def admin_user(client):
    user = User(username="adminuser", email="admin@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username, password):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def make_model(user_id=None, model_id="m-test-0001"):
    model = UserModel(
        id=model_id,
        filename=f"{model_id}/model.glb",
        file_size=1234,
        file_type="glb",
        user_id=user_id,
    )
    db.session.add(model)
    db.session.commit()
    return model


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ADMIN_GET_PAGES)
def test_admin_pages_redirect_anonymous_to_login(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


@pytest.mark.parametrize("path", ADMIN_GET_PAGES)
def test_admin_pages_hidden_from_regular_users(client, init_database, path):
    login(client, "testuser", "testpassword")
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ADMIN_GET_PAGES)
def test_admin_pages_render_for_admins(client, admin_user, path):
    login(client, "adminuser", "adminpassword")
    assert client.get(path).status_code == 200


def test_admin_posts_hidden_from_regular_users(client, init_database, admin_user):
    login(client, "testuser", "testpassword")
    response = client.post(f"/admin/users/{admin_user.id}/toggle-admin")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# User actions
# ---------------------------------------------------------------------------


def test_toggle_admin_rejects_self(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post(f"/admin/users/{admin_user.id}/toggle-admin")
    assert response.status_code == 400
    assert db.session.get(User, admin_user.id).is_admin is True


def test_toggle_active_rejects_self(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post(f"/admin/users/{admin_user.id}/toggle-active")
    assert response.status_code == 400


def test_toggle_admin_flips_flag(client, init_database, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post(f"/admin/users/{init_database.id}/toggle-admin")
    assert response.status_code == 200
    assert db.session.get(User, init_database.id).is_admin is True


def test_deactivated_user_cannot_log_in(client, init_database, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post(f"/admin/users/{init_database.id}/toggle-active")
    assert response.status_code == 200
    client.post("/logout")

    response = login(client, "testuser", "testpassword")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    # A deactivated session gets no access to authed pages either
    assert client.get("/my_models").status_code == 302


def test_reset_password_returns_temp_password_once(client, init_database, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post(f"/admin/users/{init_database.id}/reset-password")
    assert response.status_code == 200
    temp_password = response.get_json()["temp_password"]
    assert db.session.get(User, init_database.id).check_password(temp_password)


def test_delete_user_cascades(client, init_database, admin_user, tmp_path, monkeypatch):
    # monkeypatch.setitem restores these after the test, so a later test in
    # the same session can't inherit a stale tmp_path (app.config is a
    # process-wide singleton, not reset per-test like the DB is).
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "CONVERTED_FOLDER", str(tmp_path / "converted"))
    monkeypatch.setitem(app.config, "QR_FOLDER", str(tmp_path / "qr"))

    user = init_database
    model = make_model(user_id=user.id)
    folder = Folder(name="stuff", slug="stuff-1", user_id=user.id)
    db.session.add_all(
        [
            folder,
            ModelLike(model_id=model.id, user_id=user.id),
            ModelSave(model_id=model.id, user_id=user.id),
            AIGenerationJob(id="ai-1", user_id=user.id, kind="text"),
            ConversionJob(id="cj-1", user_id=user.id),
        ]
    )
    db.session.commit()
    user_id = user.id

    login(client, "adminuser", "adminpassword")
    response = client.post(f"/admin/users/{user_id}/delete")
    assert response.status_code == 200

    assert db.session.get(User, user_id) is None
    assert UserModel.query.filter_by(user_id=user_id).count() == 0
    assert ModelLike.query.count() == 0
    assert ModelSave.query.count() == 0
    assert AIGenerationJob.query.filter_by(user_id=user_id).count() == 0
    assert ConversionJob.query.filter_by(user_id=user_id).count() == 0
    assert Folder.query.filter_by(user_id=user_id).count() == 0


def test_delete_user_rejects_self(client, admin_user):
    login(client, "adminuser", "adminpassword")
    assert client.post(f"/admin/users/{admin_user.id}/delete").status_code == 400


# ---------------------------------------------------------------------------
# Model actions
# ---------------------------------------------------------------------------


def test_model_trash_restore_purge(client, admin_user, init_database, tmp_path, monkeypatch):
    upload_dir = tmp_path / "uploads"
    converted_dir = tmp_path / "converted"
    # monkeypatch.setitem restores these after the test (see comment in
    # test_delete_user_cascades above).
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(upload_dir))
    monkeypatch.setitem(app.config, "CONVERTED_FOLDER", str(converted_dir))
    monkeypatch.setitem(app.config, "QR_FOLDER", str(tmp_path / "qr"))

    model = make_model(user_id=init_database.id)
    db.session.add(ModelLike(model_id=model.id, session_id="anon-1"))
    db.session.commit()
    model_id = model.id

    # fake on-disk artifacts
    (upload_dir / model_id).mkdir(parents=True)
    (converted_dir / model_id).mkdir(parents=True)
    (converted_dir / model_id / "model.glb").write_bytes(b"glb")

    login(client, "adminuser", "adminpassword")

    assert client.post(f"/admin/models/{model_id}/trash").status_code == 200
    assert db.session.get(UserModel, model_id).deleted_at is not None

    assert client.post(f"/admin/models/{model_id}/restore").status_code == 200
    assert db.session.get(UserModel, model_id).deleted_at is None

    assert client.post(f"/admin/models/{model_id}/purge").status_code == 200
    assert db.session.get(UserModel, model_id) is None
    assert ModelLike.query.filter_by(model_id=model_id).count() == 0
    assert not (converted_dir / model_id).exists()
    assert not (upload_dir / model_id).exists()


# ---------------------------------------------------------------------------
# Conversion jobs
# ---------------------------------------------------------------------------


def test_retry_failed_job(client, admin_user):
    job = ConversionJob(id="cj-fail", status="failed", error="boom", attempts=2, max_attempts=2)
    db.session.add(job)
    db.session.commit()

    login(client, "adminuser", "adminpassword")
    response = client.post("/admin/jobs/cj-fail/retry")
    assert response.status_code == 200

    job = db.session.get(ConversionJob, "cj-fail")
    assert job.status == "pending"
    assert job.error is None
    assert job.max_attempts > job.attempts


def test_retry_rejects_non_failed_job(client, admin_user):
    db.session.add(ConversionJob(id="cj-ok", status="completed"))
    db.session.commit()
    login(client, "adminuser", "adminpassword")
    assert client.post("/admin/jobs/cj-ok/retry").status_code == 400


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_make_admin_cli(client, init_database):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["make-admin", "test@test.com"])
    assert "is now an admin" in result.output
    assert db.session.get(User, init_database.id).is_admin is True


def test_make_admin_cli_unknown_email(client):
    runner = app.test_cli_runner()
    result = runner.invoke(args=["make-admin", "nobody@test.com"])
    assert result.exit_code == 1
