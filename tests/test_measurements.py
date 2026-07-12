"""Saved distance measurements (measure tool: line + XYZ + persistence)."""

import uuid

from app import db
from models import ModelMeasurement, User, UserModel


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_user(username, email):
    u = User(username=username, email=email)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def make_model(user_id=None):
    model_id = "test-" + uuid.uuid4().hex[:8]
    model = UserModel(id=model_id, filename=f"{model_id}.glb",
                      file_type="glb", file_size=1000, user_id=user_id)
    db.session.add(model)
    db.session.commit()
    return model_id


PAYLOAD = {
    "a": {"x": 0.0, "y": 0.0, "z": 0.0},
    "b": {"x": 0.3, "y": 0.0, "z": 0.4},
    "distance_cm": 50.0,
    "label": "diagonal",
}


def test_owner_can_create_list_and_delete_measurement(client):
    owner = make_user("m_owner", "m_owner@test.com")
    model_id = make_model(user_id=owner.id)
    login(client, "m_owner", "testpassword123")

    resp = client.post(f"/api/models/{model_id}/measurements", json=PAYLOAD)
    assert resp.status_code == 201, resp.get_json()
    created = resp.get_json()["measurement"]
    assert created["label"] == "diagonal"
    assert created["distance_cm"] == 50.0
    assert created["a"] == PAYLOAD["a"] and created["b"] == PAYLOAD["b"]

    listing = client.get(f"/api/models/{model_id}/measurements").get_json()
    assert listing["success"] is True
    assert len(listing["measurements"]) == 1

    mid = created["id"]
    dele = client.delete(f"/api/models/{model_id}/measurements/{mid}")
    assert dele.status_code == 200
    assert ModelMeasurement.query.count() == 0


def test_non_owner_cannot_create_measurement(client):
    owner = make_user("m_owner2", "m_owner2@test.com")
    make_user("m_other", "m_other@test.com")
    model_id = make_model(user_id=owner.id)

    login(client, "m_other", "testpassword123")
    resp = client.post(f"/api/models/{model_id}/measurements", json=PAYLOAD)
    assert resp.status_code == 403
    assert ModelMeasurement.query.count() == 0


def test_invalid_measurement_payload_rejected(client):
    owner = make_user("m_owner3", "m_owner3@test.com")
    model_id = make_model(user_id=owner.id)
    login(client, "m_owner3", "testpassword123")

    resp = client.post(f"/api/models/{model_id}/measurements",
                       json={"a": {"x": 0, "y": 0, "z": 0}})  # missing b + distance
    assert resp.status_code == 400
    assert ModelMeasurement.query.count() == 0
