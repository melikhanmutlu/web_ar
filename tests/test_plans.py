"""Plan/billing foundation (Faz 5: "Kullanım kotaları ve plan/faturalama
temeli"): User.plan overrides the global storage/AI daily quotas."""

import io

import pytest
import site_settings
from app import app, db
from models import User
from services.plans import effective_ai_daily_limit, effective_storage_quota_mb


@pytest.fixture
def admin_user(client):
    user = User(username="adminuser", email="admin@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_user(username, plan="free"):
    u = User(username=username, email=f"{username}@test.com", plan=plan)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def test_default_plan_is_free(client):
    u = make_user("planuser1")
    assert u.plan == "free"


def test_effective_storage_quota_mb_free_uses_global_default():
    u = User(plan="free")
    assert effective_storage_quota_mb(u, 500) == 500


def test_effective_storage_quota_mb_pro_overrides_global_default():
    u = User(plan="pro")
    assert effective_storage_quota_mb(u, 500) != 500
    assert effective_storage_quota_mb(u, 500) > 500


def test_effective_storage_quota_mb_no_user_uses_global_default():
    assert effective_storage_quota_mb(None, 500) == 500


def test_effective_ai_daily_limit_pro_overrides_global_default():
    u = User(plan="pro")
    assert effective_ai_daily_limit(u, 10) > 10


def test_pro_plan_gets_a_higher_storage_quota_on_real_upload(client):
    owner = make_user("plan_uploader", plan="pro")
    login(client, "plan_uploader", "testpassword123")
    site_settings.set_setting("storage_quota_mb", "1")  # 1MB global default

    # 2MB exceeds the 1MB *global* default but is comfortably under the
    # "pro" override -- proves the pro plan's higher ceiling actually wins.
    big = io.BytesIO(b"0" * (2 * 1024 * 1024))
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.txt")},
        content_type="multipart/form-data",
    )
    assert response.status_code != 413


def test_free_plan_still_blocked_by_global_quota(client):
    make_user("plan_free_uploader", plan="free")
    login(client, "plan_free_uploader", "testpassword123")
    site_settings.set_setting("storage_quota_mb", "1")

    big = io.BytesIO(b"0" * (2 * 1024 * 1024))
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.stl")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413


def test_admin_can_set_and_reject_plan(client, admin_user):
    target = make_user("plan_target")
    login(client, "adminuser", "adminpassword")

    resp = client.post(f"/admin/users/{target.id}/set-plan", json={"plan": "pro"})
    assert resp.status_code == 200
    assert resp.get_json()["plan"] == "pro"
    assert db.session.get(User, target.id).plan == "pro"

    resp = client.post(f"/admin/users/{target.id}/set-plan", json={"plan": "enterprise-bogus"})
    assert resp.status_code == 400
    assert db.session.get(User, target.id).plan == "pro"


def test_non_admin_cannot_set_plan(client, init_database):
    # admin_required hides /admin from non-admins with a 404, not 403 —
    # consistent with every other admin.py route.
    login(client, "testuser", "testpassword")
    resp = client.post(f"/admin/users/{init_database.id}/set-plan", json={"plan": "pro"})
    assert resp.status_code == 404
