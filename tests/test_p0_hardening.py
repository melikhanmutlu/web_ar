"""P0 security/robustness hardening tests:
- login rate limit + per-account lockout
- download_version ownership guard
- rate limiting on hotspot/camera-view/version mutation routes
- automatic version pruning (cleanup_old_versions wired into create_version)
- restore_version stays correct when the restore source falls outside the
  keep-last-N window pruning could otherwise remove mid-operation
"""

import os
import shutil
import uuid

import pytest
import trimesh

from app import app, limiter
from models import ModelVersion, User, UserModel, db
from version_manager import create_version, restore_version


def login(client, username, password, follow_redirects=False):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=follow_redirects,
    )


# ---------------------------------------------------------------------------
# Login lockout + rate limit
# ---------------------------------------------------------------------------


def test_failed_logins_lock_account(client, init_database):
    for _ in range(User.LOCKOUT_THRESHOLD):
        login(client, "testuser", "wrongpassword")

    user = db.session.get(User, init_database.id)
    assert user.is_locked

    # even the correct password is rejected while locked
    response = login(client, "testuser", "testpassword", follow_redirects=True)
    assert b"Too many failed login attempts" in response.data
    assert response.request.path == "/login"


def test_successful_login_resets_lockout_counter(client, init_database):
    login(client, "testuser", "wrongpassword")
    login(client, "testuser", "wrongpassword")
    login(client, "testuser", "testpassword")

    user = db.session.get(User, init_database.id)
    assert user.failed_login_attempts == 0
    assert user.locked_until is None


def test_nonexistent_username_does_not_error(client):
    # Same generic message/path as a wrong password — no user enumeration.
    response = login(client, "nobody-here", "whatever")
    assert response.status_code == 302
    assert response.request.path == "/login" or response.headers.get("Location", "").endswith("/login")


def test_login_rate_limit_enforced(client, init_database):
    limiter.enabled = True
    try:
        responses = [login(client, "testuser", "wrongpassword") for _ in range(15)]
    finally:
        limiter.enabled = False
    assert any(r.status_code == 429 for r in responses)


# ---------------------------------------------------------------------------
# download_version ownership guard
# ---------------------------------------------------------------------------


@pytest.fixture
def owned_model_with_version(client, init_database):
    model_id = "dv-" + uuid.uuid4().hex[:8]
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

    version = create_version(model_id, "upload", comment="initial")
    assert version is not None

    yield model_id, version.version_number
    shutil.rmtree(model_dir, ignore_errors=True)


def test_download_version_requires_login_for_owned_model(client, owned_model_with_version):
    model_id, version_number = owned_model_with_version
    response = client.get(f"/api/versions/{model_id}/download/{version_number}")
    assert response.status_code == 403


def test_download_version_blocks_other_users(client, owned_model_with_version):
    other = User(username="other", email="other@test.com")
    other.set_password("password123")
    db.session.add(other)
    db.session.commit()
    login(client, "other", "password123")

    model_id, version_number = owned_model_with_version
    response = client.get(f"/api/versions/{model_id}/download/{version_number}")
    assert response.status_code == 403


def test_download_version_allows_owner(client, init_database, owned_model_with_version):
    login(client, "testuser", "testpassword")
    model_id, version_number = owned_model_with_version
    response = client.get(f"/api/versions/{model_id}/download/{version_number}")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Rate limiting on hotspot/camera-view/version mutation routes
# ---------------------------------------------------------------------------


def test_create_hotspot_is_rate_limited(client):
    limiter.enabled = True
    try:
        responses = [
            client.post(
                "/api/models/does-not-exist/hotspots",
                json={"title": "x", "position": {"x": 0, "y": 0, "z": 0}},
            )
            for _ in range(65)
        ]
    finally:
        limiter.enabled = False
    assert any(r.status_code == 429 for r in responses)


# ---------------------------------------------------------------------------
# Automatic version pruning + restore race-safety
# ---------------------------------------------------------------------------


@pytest.fixture
def model_on_disk(client):
    model_id = "vp-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    box = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(box).export(file_type="glb"))

    model = UserModel(
        id=model_id, filename=f"{model_id}/model.glb",
        file_type="glb", user_id=None, cumulative_scale=1.0,
    )
    db.session.add(model)
    db.session.commit()
    yield model_id
    shutil.rmtree(model_dir, ignore_errors=True)


def test_old_versions_are_pruned_automatically(client, model_on_disk):
    for i in range(12):
        assert create_version(model_on_disk, "transform", comment=f"edit {i}") is not None

    versions = (
        ModelVersion.query.filter_by(model_id=model_on_disk)
        .order_by(ModelVersion.version_number)
        .all()
    )
    assert len(versions) == 10
    assert [v.version_number for v in versions] == list(range(3, 13))
    # pruned versions' files are gone too, not just their DB rows
    assert not os.path.exists(
        os.path.join(app.config["CONVERTED_FOLDER"], model_on_disk, "version_1.glb")
    )


def test_restore_survives_pruning_of_the_source_version(client, model_on_disk):
    for i in range(12):
        create_version(model_on_disk, "transform", comment=f"edit {i}")

    # version 3 is the oldest survivor after the loop above (1 and 2 pruned)
    surviving = ModelVersion.query.filter_by(
        model_id=model_on_disk, version_number=3
    ).first()
    assert surviving is not None and os.path.exists(surviving.filename)

    # Restoring version 3 creates a new version 13 (pre-restore snapshot),
    # pushing the total to 11 and triggering a prune back down to 10 — which
    # would remove version 3 itself mid-restore without the temp-copy guard
    # in restore_version().
    assert restore_version(model_on_disk, 3) is True

    current_file = os.path.join(app.config["CONVERTED_FOLDER"], model_on_disk, "model.glb")
    assert os.path.exists(current_file)
    assert ModelVersion.query.filter_by(model_id=model_on_disk).count() == 10
