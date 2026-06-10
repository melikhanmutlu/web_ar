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


def test_upload_with_customizations(client):
    register_and_login(client)
    resp = client.post(
        "/api/upload",
        data={
            "file": (io.BytesIO(make_stl_bytes()), "parca.stl"),
            "name": "Özel Parça",
            "target_size": "1.5",
            "color": "#ff8800",
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 202, resp.get_json()
    status = client.get(f"/api/jobs/{resp.get_json()['job_id']}").get_json()
    assert status["status"] == "completed", status

    page = client.get(f"/m/{status['model_id']}")
    assert "Özel Parça".encode() in page.data
    # largest dimension scaled to 1.5 m
    assert b"1.50 m" in page.data


def test_model_edit_resize(client):
    register_and_login(client)
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(make_stl_bytes()), "kutu2.stl")},
        content_type="multipart/form-data",
    )
    model_id = client.get(f"/api/jobs/{resp.get_json()['job_id']}").get_json()["model_id"]

    patch = client.patch(
        f"/api/models/{model_id}",
        json={"name": "Yeniden", "target_size": 2.0, "color": "#112233"},
    )
    body = patch.get_json()
    assert patch.status_code == 200, body
    assert body["name"] == "Yeniden"
    assert abs(max(body["dimensions"].values()) - 2.0) < 0.01


def test_ai_endpoints_disabled_without_key(client):
    register_and_login(client)
    assert client.get("/api/ai/status").get_json() == {"enabled": False, "remaining": 0}
    resp = client.post("/api/ai/text", json={"prompt": "bir vazo"})
    assert resp.status_code == 503


def test_ai_text_flow_mocked(client, app, monkeypatch):
    register_and_login(client)
    app.config["MESHY_API_KEY"] = "test-key"

    from webar import ai as ai_mod

    calls = {"n": 0}

    def fake_post(path, payload):
        return "task-refine" if payload.get("mode") == "refine" else "task-preview"

    def fake_get_task(path, task_id):
        calls["n"] += 1
        if task_id == "task-preview":
            return {"status": "SUCCEEDED", "progress": 100}
        if calls["n"] < 3:
            return {"status": "IN_PROGRESS", "progress": 50}
        return {"status": "SUCCEEDED", "progress": 100,
                "model_urls": {"glb": "https://example.com/out.glb"}}

    glb_bytes = bytes(
        __import__("trimesh").creation.box(extents=(0.1, 0.1, 0.1))
        .scene().export(file_type="glb")
    )

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): yield glb_bytes
        def __enter__(self): return self
        def __exit__(self, *a): pass

    monkeypatch.setattr(ai_mod, "_post", fake_post)
    monkeypatch.setattr(ai_mod, "_get_task", fake_get_task)
    monkeypatch.setattr(ai_mod.requests, "get", lambda *a, **k: FakeResp())

    resp = client.post("/api/ai/text", json={"prompt": "test vazo"})
    assert resp.status_code == 202, resp.get_json()
    job_id = resp.get_json()["job_id"]

    # poll until ready (preview -> refine -> ready)
    for _ in range(6):
        state = client.get(f"/api/ai/jobs/{job_id}").get_json()
        if state["status"] == "ready":
            break
    assert state["status"] == "ready", state
    assert client.get(f"/m/{state['model_id']}").status_code == 200

    app.config["MESHY_API_KEY"] = ""


def test_slice_model(client):
    register_and_login(client)
    resp = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(make_stl_bytes()), "dilim.stl")},
        content_type="multipart/form-data",
    )
    model_id = client.get(f"/api/jobs/{resp.get_json()['job_id']}").get_json()["model_id"]

    cut = client.post(f"/api/models/{model_id}/slice",
                      json={"axis": "x", "position": 0.5, "keep": "above", "cap": True})
    body = cut.get_json()
    assert cut.status_code == 200, body
    # box was 0.2 wide on x; keeping the upper half leaves ~0.1
    assert abs(body["dimensions"]["x"] - 0.1) < 0.01, body

    bad = client.post(f"/api/models/{model_id}/slice",
                      json={"axis": "q", "position": 0.5})
    assert bad.status_code == 400
