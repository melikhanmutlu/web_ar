"""Plan/billing foundation (Faz 5: "Kullanım kotaları ve plan/faturalama
temeli"): User.plan overrides the global storage/AI daily quotas."""

import io

import pytest
import site_settings
from app import app, db
from models import User, UserModel
from services.plans import (
    effective_ai_daily_limit,
    effective_storage_quota_mb,
    plan_allows,
    plan_limit,
)


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


def _seed_models(user_id, n):
    """Insert n non-trashed UserModel rows directly (fast/deterministic vs
    running real uploads through the conversion pipeline)."""
    for i in range(n):
        db.session.add(UserModel(
            id=f"{user_id}-model-{i}",
            filename=f"{user_id}-model-{i}/model.glb",
            file_size=1,
            user_id=user_id,
        ))
    db.session.commit()


# --- helper unit tests ---

def test_plan_limit_free_max_models_and_business_unlimited():
    assert plan_limit(User(plan="free"), "max_models") == 10
    assert plan_limit(User(plan="business"), "max_models") is None


def test_plan_limit_none_falls_through_to_global_default():
    assert plan_limit(User(plan="free"), "storage_mb", 500) == 500
    assert plan_limit(User(plan="pro"), "storage_mb", 500) == 10240


def test_plan_allows_api_access_by_tier():
    assert plan_allows(User(plan="free"), "api_access") is False
    assert plan_allows(User(plan="pro"), "api_access") is True
    assert plan_allows(User(plan="business"), "organizations") is True


def test_business_gets_a_higher_storage_and_ai_ceiling():
    assert effective_storage_quota_mb(User(plan="business"), 500) > 10240
    assert effective_ai_daily_limit(User(plan="business"), 10) > 1000


# --- model-count gate ---

def test_free_plan_blocked_at_model_cap(client):
    owner = make_user("count_free", plan="free")
    _seed_models(owner.id, 10)  # free cap is 10
    login(client, "count_free", "testpassword123")

    small = io.BytesIO(b"0" * 1024)
    response = client.post(
        "/upload_model",
        data={"file": (small, "one_more.stl")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    assert "Model limit" in response.get_json()["error"]


def test_business_plan_not_blocked_at_same_count(client):
    owner = make_user("count_business", plan="business")
    _seed_models(owner.id, 10)
    login(client, "count_business", "testpassword123")

    small = io.BytesIO(b"0" * 1024)
    response = client.post(
        "/upload_model",
        data={"file": (small, "one_more.stl")},
        content_type="multipart/form-data",
    )
    # business max_models is None (unlimited) -> the count gate never fires.
    assert response.status_code != 413


# --- plan-aware per-file upload size ---

def test_free_plan_blocked_by_plan_upload_size(client):
    make_user("size_free", plan="free")
    login(client, "size_free", "testpassword123")
    site_settings.set_setting("max_upload_mb", "0")  # admin global disabled

    # 60 MB exceeds free's 50 MB per-file cap even though the admin global is off.
    big = io.BytesIO(b"0" * (60 * 1024 * 1024))
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.stl")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 413
    assert "upload limit" in response.get_json()["error"]


def test_pro_plan_allows_larger_file_than_free(client):
    make_user("size_pro", plan="pro")
    login(client, "size_pro", "testpassword123")
    site_settings.set_setting("max_upload_mb", "0")

    # 60 MB is over free's 50 MB cap but under pro's 100 MB cap.
    big = io.BytesIO(b"0" * (60 * 1024 * 1024))
    response = client.post(
        "/upload_model",
        data={"file": (big, "big.stl")},
        content_type="multipart/form-data",
    )
    assert response.status_code != 413


# --- API access feature gate ---

def test_free_plan_cannot_mint_api_token(client):
    make_user("api_free", plan="free")
    login(client, "api_free", "testpassword123")
    resp = client.post("/api/tokens", json={"name": "t", "scopes": ["models:read"]})
    assert resp.status_code == 403


def test_pro_plan_can_mint_api_token(client):
    make_user("api_pro", plan="pro")
    login(client, "api_pro", "testpassword123")
    resp = client.post("/api/tokens", json={"name": "t", "scopes": ["models:read"]})
    assert resp.status_code == 201
    assert resp.get_json()["token"].startswith("arv_")


# --- admin can assign the business tier ---

def test_admin_can_set_business_plan(client, admin_user):
    target = make_user("biz_target")
    login(client, "adminuser", "adminpassword")

    resp = client.post(f"/admin/users/{target.id}/set-plan", json={"plan": "business"})
    assert resp.status_code == 200
    assert resp.get_json()["plan"] == "business"
    assert db.session.get(User, target.id).plan == "business"
