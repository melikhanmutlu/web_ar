"""P1 admin panel tests: audit log recording + page, model detail page
(hotspots/versions/camera-views with admin-bypasses-ownership deletes), and
bulk actions on the users/models tables."""

import os
import shutil
import uuid

import pytest
import trimesh

from app import app, db
from models import (
    AdminAuditLog,
    CameraView,
    ModelHotspot,
    ModelLike,
    ModelSave,
    ModelVersion,
    User,
    UserModel,
)
from version_manager import create_version


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


def make_model(user_id=None, model_id=None):
    model_id = model_id or ("m-" + uuid.uuid4().hex[:8])
    model = UserModel(
        id=model_id, filename=f"{model_id}/model.glb",
        file_size=1234, file_type="glb", user_id=user_id,
    )
    db.session.add(model)
    db.session.commit()
    return model


# ---------------------------------------------------------------------------
# Audit log recording + page
# ---------------------------------------------------------------------------


def test_mutations_are_recorded_in_audit_log(client, admin_user, init_database):
    login(client, "adminuser", "adminpassword")
    client.post(f"/admin/users/{init_database.id}/toggle-admin")

    entry = AdminAuditLog.query.filter_by(action="user.toggle_admin").first()
    assert entry is not None
    assert entry.actor_id == admin_user.id
    assert entry.target_type == "user"
    assert entry.target_id == str(init_database.id)
    assert entry.detail == {"is_admin": True}


def test_settings_save_is_recorded_without_csrf_token_leaking(client, admin_user):
    login(client, "adminuser", "adminpassword")
    client.post("/admin/settings?tab=ai", data={"ai_daily_limit": "7", "csrf_token": "should-not-be-logged"})

    entry = AdminAuditLog.query.filter_by(action="settings.update").first()
    assert entry is not None
    assert entry.target_id == "ai"
    assert "csrf_token" not in entry.detail
    assert entry.detail["ai_daily_limit"] == "7"


def test_audit_log_page_lists_and_filters(client, admin_user, init_database):
    login(client, "adminuser", "adminpassword")
    client.post(f"/admin/users/{init_database.id}/toggle-active")

    # The action filter <select> always lists every distinct action ever
    # seen (regardless of the current filter), so assert on the row-level
    # badge markup, not a bare substring that a dropdown <option> would also
    # satisfy.
    row_marker = b">user.toggle_active</span>"

    response = client.get("/admin/audit-log")
    assert response.status_code == 200
    assert row_marker in response.data

    filtered = client.get("/admin/audit-log?action=user.toggle_active")
    assert row_marker in filtered.data
    filtered_out = client.get("/admin/audit-log?action=user.delete")
    assert row_marker not in filtered_out.data


def test_failed_purge_does_not_log_a_false_success(client, admin_user, monkeypatch):
    model = make_model()
    login(client, "adminuser", "adminpassword")

    import admin as admin_module
    monkeypatch.setattr(
        admin_module, "purge_model_completely",
        lambda session, m: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    response = client.post(f"/admin/models/{model.id}/purge")
    assert response.status_code == 500
    assert AdminAuditLog.query.filter_by(action="model.purge").first() is None


# ---------------------------------------------------------------------------
# Model detail page
# ---------------------------------------------------------------------------


@pytest.fixture
def model_with_content(client, init_database):
    model_id = "md-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    box = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(box).export(file_type="glb"))

    model = UserModel(
        id=model_id, filename=f"{model_id}/model.glb",
        file_type="glb", user_id=init_database.id, cumulative_scale=1.0,
    )
    db.session.add(model)
    db.session.commit()

    create_version(model_id, "upload", comment="initial")
    hotspot = ModelHotspot(
        model_id=model_id, hotspot_id="hs-1", title="Engine",
        position_x=0, position_y=0, position_z=0,
    )
    view = CameraView(
        model_id=model_id, name="Front", orbit_theta=0, orbit_phi=0, orbit_radius=1,
    )
    db.session.add_all([hotspot, view])
    db.session.commit()

    yield model_id
    shutil.rmtree(model_dir, ignore_errors=True)


def test_model_detail_page_shows_versions_hotspots_camera_views(
    client, admin_user, model_with_content
):
    login(client, "adminuser", "adminpassword")
    response = client.get(f"/admin/models/{model_with_content}")
    assert response.status_code == 200
    assert b"Engine" in response.data
    assert b"Front" in response.data
    assert b"upload" in response.data


def test_admin_can_delete_hotspot_on_another_users_model(
    client, admin_user, model_with_content
):
    # admin_user does NOT own model_with_content (init_database does) — the
    # whole point of these admin-only routes is bypassing that ownership gate.
    login(client, "adminuser", "adminpassword")
    response = client.post(
        f"/admin/models/{model_with_content}/hotspots/hs-1/delete"
    )
    assert response.status_code == 200
    assert ModelHotspot.query.filter_by(model_id=model_with_content).count() == 0
    assert AdminAuditLog.query.filter_by(action="hotspot.delete").first() is not None


def test_admin_can_delete_camera_view_on_another_users_model(
    client, admin_user, model_with_content
):
    login(client, "adminuser", "adminpassword")
    view = CameraView.query.filter_by(model_id=model_with_content).first()
    response = client.post(
        f"/admin/models/{model_with_content}/camera-views/{view.id}/delete"
    )
    assert response.status_code == 200
    assert CameraView.query.filter_by(model_id=model_with_content).count() == 0


def test_admin_can_delete_version_on_another_users_model(
    client, admin_user, model_with_content
):
    login(client, "adminuser", "adminpassword")
    response = client.post(
        f"/admin/models/{model_with_content}/versions/1/delete"
    )
    assert response.status_code == 200
    assert ModelVersion.query.filter_by(model_id=model_with_content).count() == 0


def test_delete_nonexistent_version_returns_404_without_logging(
    client, admin_user, model_with_content
):
    login(client, "adminuser", "adminpassword")
    response = client.post(
        f"/admin/models/{model_with_content}/versions/999/delete"
    )
    assert response.status_code == 404
    assert AdminAuditLog.query.filter_by(action="version.delete").first() is None


# ---------------------------------------------------------------------------
# Bulk actions
# ---------------------------------------------------------------------------


def test_bulk_deactivate_users(client, admin_user):
    a = User(username="bulk-a", email="bulk-a@test.com")
    a.set_password("password123")
    b = User(username="bulk-b", email="bulk-b@test.com")
    b.set_password("password123")
    db.session.add_all([a, b])
    db.session.commit()

    login(client, "adminuser", "adminpassword")
    response = client.post(
        "/admin/users/bulk-deactivate", json={"ids": [a.id, b.id, admin_user.id]}
    )
    assert response.status_code == 200
    assert response.get_json()["count"] == 2  # self silently excluded, not rejected

    assert db.session.get(User, a.id).is_active_flag is False
    assert db.session.get(User, b.id).is_active_flag is False
    assert db.session.get(User, admin_user.id).is_active_flag is True


def test_bulk_deactivate_rejects_empty_selection(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.post("/admin/users/bulk-deactivate", json={"ids": [admin_user.id]})
    assert response.status_code == 400


def test_bulk_delete_users_cascades(client, admin_user):
    a = User(username="bulk-c", email="bulk-c@test.com")
    a.set_password("password123")
    db.session.add(a)
    db.session.commit()
    model = make_model(user_id=a.id)
    db.session.add(ModelLike(model_id=model.id, user_id=a.id))
    db.session.commit()
    a_id = a.id

    login(client, "adminuser", "adminpassword")
    response = client.post("/admin/users/bulk-delete", json={"ids": [a_id]})
    assert response.status_code == 200
    assert db.session.get(User, a_id) is None
    assert UserModel.query.filter_by(user_id=a_id).count() == 0
    entry = AdminAuditLog.query.filter_by(action="user.bulk_delete").first()
    assert entry is not None and entry.detail["count"] == 1


def test_bulk_trash_restore_purge_models(client, admin_user, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "CONVERTED_FOLDER", str(tmp_path / "converted"))
    monkeypatch.setitem(app.config, "QR_FOLDER", str(tmp_path / "qr"))

    m1 = make_model()
    m2 = make_model()
    login(client, "adminuser", "adminpassword")

    response = client.post("/admin/models/bulk-trash", json={"ids": [m1.id, m2.id]})
    assert response.status_code == 200
    assert response.get_json()["count"] == 2
    assert db.session.get(UserModel, m1.id).deleted_at is not None
    assert db.session.get(UserModel, m2.id).deleted_at is not None

    response = client.post("/admin/models/bulk-restore", json={"ids": [m1.id]})
    assert response.status_code == 200
    assert db.session.get(UserModel, m1.id).deleted_at is None

    response = client.post("/admin/models/bulk-purge", json={"ids": [m1.id, m2.id]})
    assert response.status_code == 200
    assert response.get_json()["count"] == 2
    assert db.session.get(UserModel, m1.id) is None
    assert db.session.get(UserModel, m2.id) is None


def test_bulk_models_rejects_empty_selection(client, admin_user):
    login(client, "adminuser", "adminpassword")
    assert client.post("/admin/models/bulk-trash", json={"ids": []}).status_code == 400
    assert client.post("/admin/models/bulk-trash", json={}).status_code == 400
