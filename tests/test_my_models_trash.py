"""Coverage for the My Models trash view: /my_models/trash, and the new
restore_selected_models / delete_selected_models bulk actions used there."""

import uuid

import pytest

from app import app, db
from models import User, UserModel


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=False)


def make_model(user_id, deleted=False, model_id=None):
    model = UserModel(id=model_id or str(uuid.uuid4()), filename="x/model.glb",
                      file_size=10, file_type="glb", user_id=user_id)
    if deleted:
        from datetime import datetime
        model.deleted_at = datetime.utcnow()
    db.session.add(model)
    db.session.commit()
    return model


@pytest.fixture
def other_user(client):
    user = User(username="otheruser", email="other@test.com")
    user.set_password("otherpassword")
    db.session.add(user)
    db.session.commit()
    return user


def test_trash_route_requires_login(client):
    resp = client.get("/my_models/trash")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_trash_route_shows_only_own_trashed_models(client, init_database, other_user):
    mine_trashed = make_model(init_database.id, deleted=True)
    make_model(init_database.id, deleted=False)  # active, must not appear
    make_model(other_user.id, deleted=True)  # someone else's trash

    login(client, "testuser", "testpassword")
    resp = client.get("/my_models/trash")
    assert resp.status_code == 200
    assert mine_trashed.id.encode() in resp.data


def test_root_view_shows_trash_folder_card_with_count(client, init_database):
    make_model(init_database.id, deleted=True)
    make_model(init_database.id, deleted=True)

    login(client, "testuser", "testpassword")
    resp = client.get("/my_models")
    assert resp.status_code == 200
    assert b"Trash" in resp.data
    assert b"2 models" in resp.data


def test_root_view_includes_the_site_footer(client, init_database):
    login(client, "testuser", "testpassword")

    resp = client.get("/my_models")

    assert resp.status_code == 200
    assert b"<footer>" in resp.data
    assert b"One workspace for turning 3D files" in resp.data


def test_restore_selected_models_requires_login(client):
    resp = client.post("/restore_selected_models", json={"model_ids": ["x"]})
    assert resp.status_code == 302


def test_restore_selected_models_restores_and_checks_ownership(client, init_database, other_user):
    mine = make_model(init_database.id, deleted=True)
    theirs = make_model(other_user.id, deleted=True)

    login(client, "testuser", "testpassword")
    resp = client.post("/restore_selected_models", json={"model_ids": [mine.id, theirs.id]})
    body = resp.get_json()
    assert resp.status_code == 403
    assert body["success"] is False

    # Nothing was restored — ownership check rejects the whole batch
    db.session.refresh(mine)
    db.session.refresh(theirs)
    assert mine.deleted_at is not None
    assert theirs.deleted_at is not None


def test_restore_selected_models_success(client, init_database):
    m1 = make_model(init_database.id, deleted=True)
    m2 = make_model(init_database.id, deleted=True)

    login(client, "testuser", "testpassword")
    resp = client.post("/restore_selected_models", json={"model_ids": [m1.id, m2.id]})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["success"] is True

    db.session.refresh(m1)
    db.session.refresh(m2)
    assert m1.deleted_at is None
    assert m2.deleted_at is None


def test_delete_selected_models_purges_only_own_models(client, init_database, other_user, tmp_path, monkeypatch):
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setitem(app.config, "CONVERTED_FOLDER", str(tmp_path / "converted"))
    monkeypatch.setitem(app.config, "QR_FOLDER", str(tmp_path / "qr"))

    mine = make_model(init_database.id, deleted=True)
    theirs = make_model(other_user.id, deleted=True)

    login(client, "testuser", "testpassword")
    resp = client.post("/delete_selected_models", json={"model_ids": [mine.id, theirs.id]})
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["success"] is True

    assert db.session.get(UserModel, mine.id) is None
    # Someone else's model must survive untouched
    assert db.session.get(UserModel, theirs.id) is not None
