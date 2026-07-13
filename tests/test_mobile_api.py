"""Mobile app API: Bearer-token auth (register/login/logout) and the
Bearer-only /api/v1/... routes added for the React Native app (folders,
model list/detail/file-download, chunked upload)."""

import pytest
import trimesh

import app as app_module
from models import ApiToken, ConversionJob, Folder, User, UserModel, db


@pytest.fixture
def csrf_client(client):
    # Local copy of tests/test_csrf.py's fixture of the same name (fixtures
    # don't cross test files without a conftest.py entry) -- re-enables real
    # CSRF enforcement, which the `client` fixture disables for other tests.
    app = client.application
    app.config["WTF_CSRF_ENABLED"] = True
    yield client
    app.config["WTF_CSRF_ENABLED"] = False


def _glb_bytes():
    return bytes(trimesh.creation.box(extents=(0.1, 0.2, 0.3)).export(file_type="glb"))


def _register(client, username="mobileuser", email=None, password="password123"):
    return client.post("/api/v1/auth/register", json={
        "username": username,
        "email": email or f"{username}@test.com",
        "password": password,
        "confirm_password": password,
    })


def _login(client, username="mobileuser", password="password123"):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# --- register / login / logout ------------------------------------------

def test_mobile_register_creates_user_and_returns_token(client):
    resp = _register(client)
    assert resp.status_code == 201, resp.get_json()
    body = resp.get_json()
    assert body["success"] is True
    assert body["token"].startswith("arv_")
    assert body["user"]["username"] == "mobileuser"
    assert body["user"]["plan"] == "free"

    user = User.query.filter_by(username="mobileuser").first()
    assert user is not None
    assert user.check_password("password123")
    token = ApiToken.query.filter_by(user_id=user.id).first()
    assert token is not None
    assert set(token.scopes.split(",")) == {"models:read", "models:write"}


def test_mobile_register_rejects_duplicate_username(client):
    _register(client)
    resp = _register(client, email="other@test.com")
    assert resp.status_code == 400
    assert "username" in resp.get_json()["errors"]


def test_mobile_register_rejects_short_password(client):
    resp = client.post("/api/v1/auth/register", json={
        "username": "shortpw", "email": "shortpw@test.com",
        "password": "abc", "confirm_password": "abc",
    })
    assert resp.status_code == 400
    assert "password" in resp.get_json()["errors"]


def test_mobile_register_rejected_when_registration_disabled(client):
    from site_settings import set_setting
    set_setting("registration_enabled", "false")
    try:
        resp = _register(client)
        assert resp.status_code == 403
    finally:
        set_setting("registration_enabled", "true")


def test_mobile_login_returns_token_for_valid_credentials(client):
    _register(client)
    resp = _login(client)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["token"].startswith("arv_")


def test_mobile_login_rejects_wrong_password_and_increments_failed_attempts(client):
    _register(client)
    resp = _login(client, password="wrong-password")
    assert resp.status_code == 401
    user = User.query.filter_by(username="mobileuser").first()
    assert user.failed_login_attempts == 1


def test_mobile_login_locks_after_threshold_failed_attempts(client):
    _register(client)
    for _ in range(User.LOCKOUT_THRESHOLD):
        _login(client, password="wrong-password")
    resp = _login(client, password="password123")  # correct password, but locked
    assert resp.status_code == 423


def test_mobile_logout_revokes_token(client):
    _register(client)
    token = _login(client).get_json()["token"]
    assert client.get("/api/v1/models", headers=_auth_header(token)).status_code == 200

    logout_resp = client.post("/api/v1/auth/logout", headers=_auth_header(token))
    assert logout_resp.status_code == 200
    assert client.get("/api/v1/models", headers=_auth_header(token)).status_code == 401


# --- folders / models isolation ------------------------------------------

def _user_with_token(client, username):
    _register(client, username=username)
    token = _login(client, username=username).get_json()["token"]
    user = User.query.filter_by(username=username).first()
    return user, token


def test_mobile_folders_and_models_are_scoped_per_user(client):
    alice, alice_token = _user_with_token(client, "alice")
    bob, bob_token = _user_with_token(client, "bob")

    db.session.add(Folder(name="Alice Stuff", slug="alice-stuff-1", user_id=alice.id))
    db.session.add(Folder(name="Bob Stuff", slug="bob-stuff-1", user_id=bob.id))
    db.session.add(UserModel(id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", filename="a.glb",
                              display_name="Alice Model", user_id=alice.id, visibility="private"))
    db.session.add(UserModel(id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", filename="b.glb",
                              display_name="Bob Model", user_id=bob.id, visibility="private"))
    db.session.commit()

    alice_folders = client.get("/api/v1/folders", headers=_auth_header(alice_token)).get_json()["data"]
    assert [f["name"] for f in alice_folders] == ["Alice Stuff"]

    alice_models = client.get("/api/v1/models", headers=_auth_header(alice_token)).get_json()["data"]
    assert [m["name"] for m in alice_models] == ["Alice Model"]

    bob_models = client.get("/api/v1/models", headers=_auth_header(bob_token)).get_json()["data"]
    assert [m["name"] for m in bob_models] == ["Bob Model"]


def test_mobile_models_folder_id_filter_and_backcompat(client):
    alice, token = _user_with_token(client, "alice")
    folder = Folder(name="Sub", slug="sub-1", user_id=alice.id)
    db.session.add(folder)
    db.session.commit()

    db.session.add(UserModel(id="11111111-1111-1111-1111-111111111111", filename="root.glb",
                              display_name="Root Model", user_id=alice.id, folder_id=None))
    db.session.add(UserModel(id="22222222-2222-2222-2222-222222222222", filename="sub.glb",
                              display_name="Sub Model", user_id=alice.id, folder_id=folder.id))
    db.session.commit()

    # Omitted folder_id -> unfiltered (back-compat with the pre-mobile API).
    all_models = client.get("/api/v1/models", headers=_auth_header(token)).get_json()["data"]
    assert {m["name"] for m in all_models} == {"Root Model", "Sub Model"}

    # folder_id="" -> root only.
    root_models = client.get("/api/v1/models?folder_id=", headers=_auth_header(token)).get_json()["data"]
    assert [m["name"] for m in root_models] == ["Root Model"]

    # folder_id=<id> -> that folder only.
    sub_models = client.get(f"/api/v1/models?folder_id={folder.id}", headers=_auth_header(token)).get_json()["data"]
    assert [m["name"] for m in sub_models] == ["Sub Model"]


def test_mobile_model_detail_includes_public_glb_url_for_scene_viewer(client):
    # Android's Scene Viewer app fetches the model file itself and can't
    # carry a Bearer header, so the mobile AR handoff needs the same
    # unauthenticated URL <model-viewer> already uses on the web (see
    # mobile/src/ar/launchAR.js) rather than the Bearer-gated glb_url.
    alice, token = _user_with_token(client, "alice")
    db.session.add(UserModel(id="33333333-3333-3333-3333-333333333333", filename="pub.glb",
                              display_name="Public Model", user_id=alice.id))
    db.session.commit()

    detail = client.get(
        "/api/v1/models/33333333-3333-3333-3333-333333333333", headers=_auth_header(token)
    ).get_json()["data"]
    assert detail["public_glb_url"].endswith("/converted_files/33333333-3333-3333-3333-333333333333/model.glb")
    assert detail["glb_url"] != detail["public_glb_url"]


# --- chunked upload (the critical ownership regression test) -------------

def _init_v1(client, token, filename, total_size, total_chunks):
    return client.post("/api/v1/uploads/chunked/init", json={
        "filename": filename, "total_size": total_size, "total_chunks": total_chunks,
    }, headers=_auth_header(token))


def _put_chunks_v1(client, token, upload_id, chunks):
    for i, chunk in enumerate(chunks):
        resp = client.put(f"/api/v1/uploads/chunked/{upload_id}/chunks/{i}", data=chunk,
                          headers=_auth_header(token))
        assert resp.status_code == 200, resp.get_json()


def test_mobile_chunked_upload_end_to_end_owns_model(client, monkeypatch):
    """Regression test for the bug this refactor exists to fix: without
    threading the token's owner through _finalize_staged_upload, a
    Bearer-authenticated mobile upload would be attributed to no one
    (payload["user_id"] would be None, same as an anonymous web upload)."""
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    owner, token = _user_with_token(client, "uploader")

    data = _glb_bytes()
    mid = len(data) // 2
    chunks = [data[:mid], data[mid:]]

    init_resp = _init_v1(client, token, "model.glb", len(data), len(chunks))
    assert init_resp.status_code == 201, init_resp.get_json()
    upload_id = init_resp.get_json()["upload_id"]

    _put_chunks_v1(client, token, upload_id, chunks)

    complete = client.post(f"/api/v1/uploads/chunked/{upload_id}/complete", json={},
                           headers=_auth_header(token))
    assert complete.status_code == 202, complete.get_json()
    job = db.session.get(ConversionJob, complete.get_json()["job_id"])
    assert job is not None
    assert job.payload["user_id"] == owner.id
    assert job.user_id == owner.id


def test_mobile_chunked_upload_requires_bearer_token(client):
    resp = client.post("/api/v1/uploads/chunked/init", json={
        "filename": "model.glb", "total_size": 10, "total_chunks": 1,
    })
    assert resp.status_code == 401

    put_resp = client.put("/api/v1/uploads/chunked/does-not-exist/chunks/0", data=b"x")
    assert put_resp.status_code == 401

    complete_resp = client.post("/api/v1/uploads/chunked/does-not-exist/complete", json={})
    assert complete_resp.status_code == 401


def test_mobile_chunked_upload_rejects_read_only_scope(client):
    owner, _ = _user_with_token(client, "readonly")
    from blueprints.api_tokens import _issue_api_token
    issued = _issue_api_token(owner, name="read-only", scopes=["models:read"], expires_in_days=1)
    resp = _init_v1(client, issued["token"], "model.glb", 10, 1)
    assert resp.status_code == 403


# --- file download / thumbnail ownership ---------------------------------

def test_mobile_file_download_and_thumbnail_require_ownership(client, tmp_path, monkeypatch):
    alice, alice_token = _user_with_token(client, "alice")
    bob, bob_token = _user_with_token(client, "bob")

    converted_dir = tmp_path / "converted" / "cccccccc-cccc-cccc-cccc-cccccccccccc"
    converted_dir.mkdir(parents=True)
    glb_path = converted_dir / "model.glb"
    glb_path.write_bytes(_glb_bytes())
    monkeypatch.setitem(app_module.app.config, "CONVERTED_FOLDER", str(tmp_path / "converted"))

    db.session.add(UserModel(id="cccccccc-cccc-cccc-cccc-cccccccccccc", filename=str(glb_path),
                              display_name="Alice Model", user_id=alice.id))
    db.session.commit()

    owner_resp = client.get(
        "/api/v1/models/cccccccc-cccc-cccc-cccc-cccccccccccc/glb", headers=_auth_header(alice_token)
    )
    assert owner_resp.status_code == 200

    other_resp = client.get(
        "/api/v1/models/cccccccc-cccc-cccc-cccc-cccccccccccc/glb", headers=_auth_header(bob_token)
    )
    assert other_resp.status_code == 404

    thumb_resp = client.get(
        "/api/v1/models/cccccccc-cccc-cccc-cccc-cccccccccccc/thumbnail", headers=_auth_header(alice_token)
    )
    assert thumb_resp.status_code == 404  # no thumbnail.png cached -- placeholder case, not an error


# --- CSRF exemption --------------------------------------------------------

def test_mobile_endpoints_exempt_from_csrf(csrf_client):
    # csrf_client has WTF_CSRF_ENABLED=True and no CSRF token is presented
    # anywhere below. If these routes weren't csrf.exempt()'d in app.py,
    # CSRFProtect would 400 every one of them before the view ever ran
    # (see tests/test_csrf.py's test_api_post_without_token_returns_json_400).
    register_resp = _register(csrf_client, username="csrfmobile")
    assert register_resp.status_code == 201, register_resp.get_json()
    token = register_resp.get_json()["token"]

    login_resp = _login(csrf_client, username="csrfmobile")
    assert login_resp.status_code == 200

    init_resp = _init_v1(csrf_client, token, "model.glb", 10, 1)
    assert init_resp.status_code == 201, init_resp.get_json()
    upload_id = init_resp.get_json()["upload_id"]

    put_resp = csrf_client.put(f"/api/v1/uploads/chunked/{upload_id}/chunks/0", data=b"x" * 10,
                               headers=_auth_header(token))
    assert put_resp.status_code == 200, put_resp.get_json()

    logout_resp = csrf_client.post("/api/v1/auth/logout", headers=_auth_header(token))
    assert logout_resp.status_code == 200
