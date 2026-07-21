"""Plan/billing foundation (Faz 5: "Kullanım kotaları ve plan/faturalama
temeli"): User.plan overrides the global storage/monthly-AI quotas."""

import io

import pytest
import site_settings
from app import app, db
from models import User, UserModel
from services.plans import (
    effective_ai_monthly_limit,
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


def test_effective_ai_monthly_limit_pro_overrides_global_default():
    u = User(plan="pro")
    assert effective_ai_monthly_limit(u, 5) == 20


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
    assert effective_ai_monthly_limit(User(plan="business"), 5) == 200


def test_free_ai_monthly_falls_through_to_global_default():
    # free leaves ai_monthly None -> uses the admin global (0 = off by default).
    assert effective_ai_monthly_limit(User(plan="free"), 0) == 0
    assert effective_ai_monthly_limit(User(plan="free"), 3) == 3


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


# --- DB-backed plan CRUD (services/plans.py + admin plans tab) ---

def _full_plan_form(prefix, base_slug, **overrides):
    """Build the full admin plans-form payload for one plan, seeded from
    PLAN_CONFIG[base_slug] so unmentioned fields keep their real values (the
    real editor renders every field, so a submit always carries the full
    state). `limits`/`features` overrides merge into the base."""
    from services.plans import PLAN_CONFIG, LIMIT_KEYS, FEATURE_KEYS
    cfg = PLAN_CONFIG[base_slug]
    limits = {**cfg["limits"], **overrides.pop("limits", {})}
    features = {**cfg["features"], **overrides.pop("features", {})}
    price = overrides.pop("price", cfg["price"])
    data = {
        "plan_action": "save",
        f"{prefix}__display_name": overrides.pop("display_name", cfg["display_name"]),
        f"{prefix}__price": "" if price is None else str(price),
        f"{prefix}__currency": "TRY",
        f"{prefix}__billing_period": "monthly",
        f"{prefix}__sort_order": "5",
        f"{prefix}__is_public": "on",
    }
    for key in LIMIT_KEYS:
        if limits.get(key) is not None:
            data[f"{prefix}__{key}"] = str(limits[key])
    for key in FEATURE_KEYS:
        if features.get(key):
            data[f"{prefix}__{key}"] = "on"
    return data


def test_get_plan_config_no_context_matches_code_default():
    # No app context -> fallback to PLAN_CONFIG. limits/features must match the
    # code defaults exactly (the config also carries currency/billing_period).
    from services.plans import PLAN_CONFIG, get_plan_config
    cfg = get_plan_config("pro")
    assert cfg["limits"] == PLAN_CONFIG["pro"]["limits"]
    assert cfg["features"] == PLAN_CONFIG["pro"]["features"]


def test_plan_limit_pure_without_app_context_uses_fallback():
    # No `client` fixture -> no Flask app context. Regression guard: the DB
    # lookup must not fire outside a request; PLAN_CONFIG fallback applies.
    assert plan_limit(User(plan="pro"), "max_models") == 200
    assert plan_allows(User(plan="pro"), "api_access") is True


def test_admin_can_edit_existing_plan(client, admin_user):
    login(client, "adminuser", "adminpassword")
    form = _full_plan_form("pro", "pro", limits={"max_models": 500}, features={"webhooks": True})
    form["plan_slug"] = "pro"
    resp = client.post("/admin/settings?tab=plans", data=form)
    assert resp.status_code == 302

    pro_user = User(plan="pro")
    assert plan_limit(pro_user, "max_models") == 500
    assert plan_allows(pro_user, "webhooks") is True
    # Full-form edit preserves untouched fields (pro's storage stays 10 GB).
    assert plan_limit(pro_user, "storage_mb") == 10240
    assert plan_allows(pro_user, "api_access") is True


def test_admin_can_create_and_delete_custom_plan(client, admin_user):
    from services.plans import public_plan_slugs, plan_allows, plan_limit, delete_plan

    login(client, "adminuser", "adminpassword")
    form = _full_plan_form("new", "business", features={"webhooks": False})
    form["new__slug"] = "studio"
    resp = client.post("/admin/settings?tab=plans", data=form)
    assert resp.status_code == 302
    assert "studio" in public_plan_slugs()
    studio_user = User(plan="studio")
    assert plan_allows(studio_user, "organizations") is True   # inherited from business base
    assert plan_allows(studio_user, "webhooks") is False       # explicitly turned off
    assert plan_limit(studio_user, "max_upload_mb") == 100

    # Deleting a non-system plan works.
    delete = client.post("/admin/settings?tab=plans", data={
        "plan_action": "delete", "plan_slug": "studio",
    })
    assert delete.status_code == 302
    assert "studio" not in public_plan_slugs()


def test_system_plan_cannot_be_deleted(client, admin_user):
    from services.plans import public_plan_slugs
    login(client, "adminuser", "adminpassword")
    client.post("/admin/settings?tab=plans", data={
        "plan_action": "delete", "plan_slug": "free",
    })
    assert "free" in public_plan_slugs()


def test_admin_unlimited_plan_ignores_plan_edits(client, admin_user):
    from services.plans import ADMIN_PLAN, plan_name

    login(client, "adminuser", "adminpassword")
    form = _full_plan_form("pro", "pro", limits={"max_models": 1})
    form["plan_slug"] = "pro"
    client.post("/admin/settings?tab=plans", data=form)
    admin = db.session.get(User, admin_user.id)
    assert plan_name(admin) == ADMIN_PLAN
    assert plan_limit(admin, "max_models") is None
    assert plan_allows(admin, "webhooks") is True


def test_invalid_plan_price_is_rejected(client, admin_user):
    from services.plans import plan_limit
    login(client, "adminuser", "adminpassword")
    form = _full_plan_form("pro", "pro", limits={"max_models": 500})
    form["plan_slug"] = "pro"
    form["pro__price"] = "-5"
    resp = client.post("/admin/settings?tab=plans", data=form)
    assert resp.status_code == 302
    # Rejected -- the max_models edit didn't take effect either.
    assert plan_limit(User(plan="pro"), "max_models") == 200


def test_plan_expiry_falls_back_to_free(client):
    from datetime import datetime, timedelta
    from services.plans import plan_name, plan_allows
    expired = make_user("expired_pro", plan="business")
    expired.plan_expires_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()
    assert plan_name(expired) == "free"
    assert plan_allows(expired, "organizations") is False

    active = make_user("active_pro", plan="business")
    active.plan_expires_at = datetime.utcnow() + timedelta(days=1)
    db.session.commit()
    assert plan_name(active) == "business"
