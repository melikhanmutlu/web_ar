"""Token-based CSRF protection (CSRFProtect) on state-changing endpoints.

The conftest client fixture disables CSRF for unrelated tests; the fixture
here re-enables it so these tests exercise the real production behaviour.
"""
import re

import pytest

from models import Folder, User, UserModel, db


@pytest.fixture
def csrf_client(client):
    app = client.application
    app.config["WTF_CSRF_ENABLED"] = True
    yield client
    app.config["WTF_CSRF_ENABLED"] = False


def _register_user(name="csrf-user"):
    user = User(username=name, email=f"{name}@test.com")
    user.set_password("password123")
    db.session.add(user)
    db.session.commit()
    return user


def _page_token(client, path="/login"):
    page = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match, f"no csrf_token field rendered on {path}"
    return match.group(1)


def _login(client, username="csrf-user", password="password123"):
    token = _page_token(client)
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": token},
    )


def test_login_page_renders_hidden_csrf_token(csrf_client):
    assert 'name="csrf_token"' in csrf_client.get("/login").get_data(as_text=True)


def test_login_without_token_is_rejected(csrf_client):
    _register_user()
    response = csrf_client.post(
        "/login", data={"username": "csrf-user", "password": "password123"}
    )
    assert response.status_code == 302  # bounced by the CSRF handler, not logged in
    protected = csrf_client.get("/my_models")
    assert protected.status_code == 302
    assert "/login" in protected.headers["Location"]


def test_login_with_token_succeeds(csrf_client):
    _register_user()
    assert _login(csrf_client).status_code == 302
    assert csrf_client.get("/my_models").status_code == 200


def test_form_post_without_token_is_rejected(csrf_client):
    user = _register_user()
    _login(csrf_client)
    response = csrf_client.post("/create_folder", data={"folder_name": "Blocked"})
    assert response.status_code == 302
    assert Folder.query.filter_by(user_id=user.id).count() == 0


def test_header_token_accepted_for_fetch_style_posts(csrf_client):
    user = _register_user()
    _login(csrf_client)
    # /login redirects once authenticated; the home page still renders a token
    token = _page_token(csrf_client, "/")
    response = csrf_client.post(
        "/create_folder",
        data={"folder_name": "Allowed"},
        headers={"X-CSRFToken": token},
    )
    assert response.status_code == 302
    assert Folder.query.filter_by(user_id=user.id, name="Allowed").count() == 1


def test_api_post_without_token_returns_json_400(csrf_client):
    _register_user()
    _login(csrf_client)
    response = csrf_client.post("/api/organizations/999/folders", json={"name": "x"})
    assert response.status_code == 400
    assert "CSRF" in response.get_json()["error"]


def test_upload_model_requires_token_but_accepts_it(csrf_client):
    # Without a token the request never reaches the view.
    rejected = csrf_client.post("/upload_model", data={})
    assert rejected.status_code == 302
    # With the token from the upload page, the view runs (and reports the
    # actual validation problem: no file).
    token = _page_token(csrf_client, "/studio")
    accepted = csrf_client.post(
        "/upload_model", data={"csrf_token": token}
    )
    assert accepted.status_code == 400
    assert "CSRF" not in (accepted.get_json() or {}).get("error", "")


def test_exempt_endpoints_still_answer(csrf_client):
    assert csrf_client.post("/upload", data={}).status_code == 410
    assert csrf_client.post("/convert", json={}).status_code == 410

    model = UserModel(id="csrf-embed-model", filename="m.glb", visibility="unlisted")
    db.session.add(model)
    db.session.commit()
    beacon = csrf_client.post(
        f"/api/models/{model.id}/events", json={"event_type": "ar_launch"}
    )
    assert beacon.status_code == 202
