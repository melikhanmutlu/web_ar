"""Programmatic write API (/api/v1 upload/convert, job status, update, delete)."""
import io

import trimesh

from models import ConversionJob, User, UserModel, db


def _owner_with_token(client, scopes):
    owner = User(username="writeapi", email="writeapi@example.com", plan="business")
    owner.set_password("password")
    db.session.add(owner)
    db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    token = client.post(
        "/api/tokens", json={"name": "CI", "scopes": scopes}
    ).get_json()["token"]
    client.post("/logout")
    return owner, token


def _stl_bytes():
    return trimesh.creation.box(extents=(1, 1, 1)).export(file_type="stl")


def test_write_scope_required_to_upload(client):
    _, read_token = _owner_with_token(client, ["models:read"])
    response = client.post(
        "/api/v1/models",
        data={"file": (io.BytesIO(_stl_bytes()), "cube.stl")},
        headers={"Authorization": f"Bearer {read_token}"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 403
    assert "models:write" in response.get_json()["error"]


def test_upload_creates_job_scoped_to_token(client, monkeypatch):
    # Don't actually run the (heavy) conversion in-process; just verify the job
    # is created and correctly scoped. The pipeline itself is covered elsewhere.
    import app as app_module
    monkeypatch.setattr(app_module, "_start_local_conversion", lambda job_id: None)

    owner, token = _owner_with_token(client, ["models:read", "models:write"])
    response = client.post(
        "/api/v1/models",
        data={"file": (io.BytesIO(_stl_bytes()), "cube.stl"), "name": "My Cube"},
        headers={"Authorization": f"Bearer {token}"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 202
    body = response.get_json()["data"]
    job_id = body["job_id"]
    assert body["model_id"] == job_id
    job = db.session.get(ConversionJob, job_id)
    assert job is not None
    assert job.user_id == owner.id
    assert job.job_type == "upload"
    assert job.payload["display_name"] == "My Cube"

    status = client.get(
        f"/api/v1/jobs/{job_id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert status.status_code == 200
    assert status.get_json()["data"]["status"] in {"pending", "processing", "completed"}


def test_upload_rejects_unsupported_type(client):
    _, token = _owner_with_token(client, ["models:write"])
    response = client.post(
        "/api/v1/models",
        data={"file": (io.BytesIO(b"nope"), "notes.txt")},
        headers={"Authorization": f"Bearer {token}"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 400


def test_patch_and_delete_model_via_token(client):
    owner, token = _owner_with_token(client, ["models:read", "models:write"])
    model = UserModel(
        id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        filename="unused.glb", user_id=owner.id, visibility="private",
    )
    db.session.add(model)
    db.session.commit()

    patched = client.patch(
        f"/api/v1/models/{model.id}",
        json={"name": "Renamed", "visibility": "public"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert patched.status_code == 200
    assert patched.get_json()["data"]["name"] == "Renamed"
    assert patched.get_json()["data"]["visibility"] == "public"

    bad = client.patch(
        f"/api/v1/models/{model.id}",
        json={"visibility": "nonsense"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert bad.status_code == 400

    deleted = client.delete(
        f"/api/v1/models/{model.id}", headers={"Authorization": f"Bearer {token}"}
    )
    assert deleted.status_code == 200
    assert db.session.get(UserModel, model.id).deleted_at is not None
    # A soft-deleted model is no longer visible to the API.
    assert client.get(
        f"/api/v1/models/{model.id}", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 404


def test_token_cannot_touch_another_users_model(client):
    _, token = _owner_with_token(client, ["models:write"])
    stranger = User(username="stranger", email="stranger@example.com")
    stranger.set_password("password")
    db.session.add(stranger)
    db.session.flush()
    other = UserModel(
        id="eeee1111-eeee-1111-eeee-111111111111",
        filename="unused.glb", user_id=stranger.id, visibility="private",
    )
    db.session.add(other)
    db.session.commit()
    assert client.patch(
        f"/api/v1/models/{other.id}", json={"name": "hijack"},
        headers={"Authorization": f"Bearer {token}"},
    ).status_code == 404
    assert client.delete(
        f"/api/v1/models/{other.id}", headers={"Authorization": f"Bearer {token}"}
    ).status_code == 404
