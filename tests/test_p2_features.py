"""P2 admin panel tests: CSV export, dashboard/analytics date range,
worker heartbeat, AI-job stale detection + mark-as-failed, and the
accessibility/modal markup additions."""

import csv
import io
from datetime import datetime, timedelta

import pytest

import admin as admin_module
import site_settings
from app import app, db
from models import AdminAuditLog, AIGenerationJob, ConversionJob, User, UserModel


@pytest.fixture
def admin_user(client):
    user = User(username="adminuser", email="admin@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_model(user_id=None, model_id="m-p2-0001", **kwargs):
    model = UserModel(
        id=model_id, filename=f"{model_id}/model.glb", file_size=1234,
        file_type="glb", user_id=user_id, **kwargs,
    )
    db.session.add(model)
    db.session.commit()
    return model


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------


def _parse_csv(response):
    return list(csv.reader(io.StringIO(response.get_data(as_text=True))))


def test_export_users_csv(client, admin_user, init_database):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/users/export.csv")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    rows = _parse_csv(response)
    assert rows[0] == [
        "id", "username", "email", "joined", "models", "storage_bytes", "is_admin", "is_active",
    ]
    usernames = [r[1] for r in rows[1:]]
    assert "testuser" in usernames
    assert "adminuser" in usernames


def test_export_users_csv_respects_search_filter(client, admin_user, init_database):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/users/export.csv?q=testuser")
    rows = _parse_csv(response)
    usernames = [r[1] for r in rows[1:]]
    assert usernames == ["testuser"]


def test_export_models_csv(client, admin_user, init_database):
    make_model(user_id=init_database.id)
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/models/export.csv")
    assert response.status_code == 200
    rows = _parse_csv(response)
    assert rows[0][0] == "id"
    assert any(r[0] == "m-p2-0001" for r in rows[1:])


def test_export_jobs_csv(client, admin_user):
    db.session.add(ConversionJob(id="cj-csv-1", status="completed"))
    db.session.commit()
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/jobs/export.csv")
    assert response.status_code == 200
    rows = _parse_csv(response)
    assert any(r[0] == "cj-csv-1" for r in rows[1:])


def test_export_ai_jobs_csv(client, admin_user, init_database):
    db.session.add(
        AIGenerationJob(id="ai-csv-1", user_id=init_database.id, kind="text", prompt="a lamp")
    )
    db.session.commit()
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/ai-jobs/export.csv")
    assert response.status_code == 200
    rows = _parse_csv(response)
    assert any(r[0] == "ai-csv-1" and r[7] == "a lamp" for r in rows[1:])


def test_export_audit_log_csv(client, admin_user, init_database):
    login(client, "adminuser", "adminpassword")
    client.post(f"/admin/users/{init_database.id}/toggle-active")
    response = client.get("/admin/audit-log/export.csv")
    assert response.status_code == 200
    rows = _parse_csv(response)
    assert any(r[2] == "user.toggle_active" for r in rows[1:])


def test_csv_exports_require_admin(client, init_database):
    login(client, "testuser", "testpassword")
    for path in (
        "/admin/users/export.csv", "/admin/models/export.csv", "/admin/jobs/export.csv",
        "/admin/ai-jobs/export.csv", "/admin/audit-log/export.csv",
    ):
        assert client.get(path).status_code == 404


def test_delete_audit_log_entry(client, admin_user, init_database):
    login(client, "adminuser", "adminpassword")
    client.post(f"/admin/users/{init_database.id}/toggle-active")
    entry = AdminAuditLog.query.filter_by(action="user.toggle_active").first()
    assert entry is not None

    response = client.post(f"/admin/audit-log/{entry.id}/delete")
    assert response.status_code == 200
    assert db.session.get(AdminAuditLog, entry.id) is None
    # The delete itself is logged.
    assert AdminAuditLog.query.filter_by(action="audit_log.delete").first() is not None


def test_delete_audit_log_entry_not_found(client, admin_user):
    login(client, "adminuser", "adminpassword")
    assert client.post("/admin/audit-log/999999/delete").status_code == 404


def test_bulk_delete_audit_log(client, admin_user, init_database):
    login(client, "adminuser", "adminpassword")
    client.post(f"/admin/users/{init_database.id}/toggle-active")
    client.post(f"/admin/users/{init_database.id}/toggle-active")
    ids = [e.id for e in AdminAuditLog.query.filter_by(action="user.toggle_active").all()]
    assert len(ids) == 2

    response = client.post("/admin/audit-log/bulk-delete", json={"ids": ids})
    assert response.status_code == 200
    assert response.get_json()["count"] == 2
    assert AdminAuditLog.query.filter(AdminAuditLog.id.in_(ids)).count() == 0


def test_bulk_delete_audit_log_rejects_empty_selection(client, admin_user):
    login(client, "adminuser", "adminpassword")
    assert client.post("/admin/audit-log/bulk-delete", json={"ids": []}).status_code == 400
    assert client.post("/admin/audit-log/bulk-delete", json={}).status_code == 400


def test_audit_log_delete_routes_require_admin(client, init_database):
    login(client, "testuser", "testpassword")
    assert client.post("/admin/audit-log/1/delete").status_code == 404
    assert client.post("/admin/audit-log/bulk-delete", json={"ids": [1]}).status_code == 404


# ---------------------------------------------------------------------------
# Date range selector
# ---------------------------------------------------------------------------


def test_dashboard_default_range_is_30_days(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/")
    assert b"last 30 days" in response.data


def test_dashboard_accepts_valid_day_range(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/?days=7")
    assert b"last 7 days" in response.data


def test_dashboard_rejects_invalid_day_range(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/?days=365")
    assert b"last 30 days" in response.data


def test_analytics_accepts_valid_day_range(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/analytics?days=90")
    assert response.status_code == 200
    assert b"last 90 days" in response.data


# ---------------------------------------------------------------------------
# Worker heartbeat
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_settings_cache():
    site_settings.invalidate_cache()
    yield
    site_settings.invalidate_cache()


def test_worker_health_reports_never_seen_with_no_heartbeat(client):
    last_seen, seconds_ago, stale = admin_module._worker_health()
    assert last_seen is None
    assert stale is True


def test_worker_health_reports_fresh_heartbeat(client):
    site_settings.set_setting("worker_heartbeat", datetime.utcnow().isoformat())
    last_seen, seconds_ago, stale = admin_module._worker_health()
    assert last_seen is not None
    assert stale is False
    assert seconds_ago < 5


def test_worker_health_reports_stale_heartbeat(client):
    old = datetime.utcnow() - timedelta(minutes=10)
    site_settings.set_setting("worker_heartbeat", old.isoformat())
    _, _, stale = admin_module._worker_health()
    assert stale is True


def test_dashboard_shows_worker_never_seen(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/")
    assert b"never seen" in response.data


def test_dashboard_shows_worker_last_seen(client, admin_user):
    site_settings.set_setting("worker_heartbeat", datetime.utcnow().isoformat())
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/")
    assert b"last seen" in response.data


# ---------------------------------------------------------------------------
# AI job stale detection + mark-as-failed
# ---------------------------------------------------------------------------


def test_stuck_ai_job_flagged_stale_on_dashboard(client, admin_user, init_database):
    job = AIGenerationJob(
        id="ai-stale-1", user_id=init_database.id, kind="text", status="generating",
    )
    db.session.add(job)
    db.session.commit()
    job.updated_at = datetime.utcnow() - timedelta(minutes=45)
    db.session.commit()

    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/")
    assert response.get_data(as_text=True).count("stale ai generations")


def test_stuck_ai_job_shows_stale_badge_on_list_page(client, admin_user, init_database):
    job = AIGenerationJob(
        id="ai-stale-2", user_id=init_database.id, kind="text", status="generating",
    )
    db.session.add(job)
    db.session.commit()
    job.updated_at = datetime.utcnow() - timedelta(minutes=45)
    db.session.commit()

    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/ai-jobs")
    assert b"stale" in response.data


def test_mark_ai_job_failed(client, admin_user, init_database):
    job = AIGenerationJob(
        id="ai-mark-1", user_id=init_database.id, kind="text", status="generating",
    )
    db.session.add(job)
    db.session.commit()

    login(client, "adminuser", "adminpassword")
    response = client.post("/admin/ai-jobs/ai-mark-1/mark-failed")
    assert response.status_code == 200

    updated = db.session.get(AIGenerationJob, "ai-mark-1")
    assert updated.status == "failed"
    assert "admin" in updated.error.lower()
    assert AdminAuditLog.query.filter_by(action="ai_job.mark_failed").first() is not None


def test_mark_ai_job_failed_rejects_already_finished(client, admin_user, init_database):
    job = AIGenerationJob(
        id="ai-mark-2", user_id=init_database.id, kind="text", status="ready",
    )
    db.session.add(job)
    db.session.commit()

    login(client, "adminuser", "adminpassword")
    response = client.post("/admin/ai-jobs/ai-mark-2/mark-failed")
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Accessibility / modal markup
# ---------------------------------------------------------------------------


def test_confirm_modal_has_dialog_semantics(client, admin_user):
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/")
    html = response.get_data(as_text=True)
    assert 'id="adminConfirmModal"' in html
    assert 'role="dialog"' in html
    assert 'aria-modal="true"' in html


def test_model_row_icon_buttons_have_aria_labels(client, admin_user):
    make_model()
    login(client, "adminuser", "adminpassword")
    response = client.get("/admin/models")
    html = response.get_data(as_text=True)
    assert 'aria-label="open viewer"' in html
    assert 'aria-label="move to trash"' in html
    assert 'aria-label="delete permanently"' in html
