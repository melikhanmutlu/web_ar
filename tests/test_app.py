"""End-to-end smoke tests: auth, upload→conversion→viewer flow."""

import io
import os
import tempfile

import pytest
import trimesh

os.environ["SKIP_DB_BOOTSTRAP"] = "1"
os.environ["JOB_QUEUE"] = "false"
os.environ["USDZ_EXPORT"] = "false"

_tmp = tempfile.mkdtemp(prefix="webar-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["WEB_AR_UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["WEB_AR_CONVERTED_DIR"] = f"{_tmp}/converted"
os.environ["WEB_AR_QR_DIR"] = f"{_tmp}/qr"

from webar import create_app  # noqa: E402
from webar.extensions import db  # noqa: E402


@pytest.fixture(scope="module")
def app():
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    with app.app_context():
        db.create_all()
    yield app


@pytest.fixture()
def client(app):
    return app.test_client()


def register_and_login(client):
    client.post("/register", data={
        "username": "tester",
        "email": "tester@example.com",
        "password": "supersecret1",
        "confirm": "supersecret1",
    })
    client.post("/login", data={"username": "tester", "password": "supersecret1"})


def make_stl_bytes() -> bytes:
    return trimesh.creation.box(extents=(0.2, 0.2, 0.2)).export(file_type="stl")


def test_index(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json == {"status": "ok"}


def test_auth_flow(client):
    register_and_login(client)
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_upload_requires_login(client):
    client.post("/logout")
    resp = client.post("/api/upload", data={})
    assert resp.status_code in (302, 401)


def test_upload_convert_and_view(client):
    register_and_login(client)

    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(make_stl_bytes()), "kutu.stl")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202, resp.get_json()
    job_id = resp.get_json()["job_id"]

    status = client.get(f"/api/jobs/{job_id}").get_json()
    assert status["status"] == "completed", status
    model_id = status["model_id"]

    page = client.get(f"/m/{model_id}")
    assert page.status_code == 200
    assert "kutu".encode() in page.data

    glb = client.get(f"/files/models/{model_id}.glb")
    assert glb.status_code == 200
    assert glb.data[:4] == b"glTF"

    assert client.get(f"/m/{model_id}/embed").status_code == 200


def test_reject_unknown_extension(client):
    register_and_login(client)
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"hello"), "evil.exe")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
