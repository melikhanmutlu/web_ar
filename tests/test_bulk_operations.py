"""Expanded bulk operations (Faz 3: "Genişletilmiş toplu işlemler"):
bulk visibility change and bulk tag add on the My Models library."""

import uuid

import pytest

from app import app, db
from models import User, UserModel


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_model(user_id, model_id=None, tags=None):
    model = UserModel(id=model_id or str(uuid.uuid4()), filename="x/model.glb",
                      file_size=10, file_type="glb", user_id=user_id, tags=tags)
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


def test_bulk_update_visibility_requires_login(client):
    resp = client.post("/bulk_update_visibility", json={"model_ids": ["x"], "visibility": "public"})
    assert resp.status_code == 302


def test_bulk_update_visibility_sets_all_selected(client, init_database):
    m1 = make_model(init_database.id)
    m2 = make_model(init_database.id)
    login(client, "testuser", "testpassword")

    resp = client.post("/bulk_update_visibility", json={
        "model_ids": [m1.id, m2.id], "visibility": "public"})
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True
    assert db.session.get(UserModel, m1.id).visibility == "public"
    assert db.session.get(UserModel, m2.id).visibility == "public"


def test_bulk_update_visibility_rejects_invalid_value(client, init_database):
    m1 = make_model(init_database.id)
    login(client, "testuser", "testpassword")
    resp = client.post("/bulk_update_visibility", json={"model_ids": [m1.id], "visibility": "bogus"})
    assert resp.status_code == 400


def test_bulk_update_visibility_rejects_models_not_owned(client, init_database, other_user):
    mine = make_model(init_database.id)
    theirs = make_model(other_user.id)
    login(client, "testuser", "testpassword")

    resp = client.post("/bulk_update_visibility", json={
        "model_ids": [mine.id, theirs.id], "visibility": "public"})
    assert resp.status_code == 403
    assert db.session.get(UserModel, mine.id).visibility != "public"


def test_bulk_add_tags_merges_with_existing(client, init_database):
    m1 = make_model(init_database.id, tags="red,large")
    m2 = make_model(init_database.id)
    login(client, "testuser", "testpassword")

    resp = client.post("/bulk_add_tags", json={
        "model_ids": [m1.id, m2.id], "tags": ["sale", "RED"]})
    assert resp.status_code == 200

    m1_tags = db.session.get(UserModel, m1.id).tags.split(",")
    assert set(m1_tags) == {"red", "large", "sale"}  # dedup keeps existing "red"
    m2_tags = db.session.get(UserModel, m2.id).tags.split(",")
    assert set(m2_tags) == {"sale", "red"}


def test_bulk_add_tags_rejects_empty_list(client, init_database):
    m1 = make_model(init_database.id)
    login(client, "testuser", "testpassword")
    resp = client.post("/bulk_add_tags", json={"model_ids": [m1.id], "tags": []})
    assert resp.status_code == 400
