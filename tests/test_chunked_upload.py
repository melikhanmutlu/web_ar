"""Chunked/resumable upload (Faz 4: "Parçalı/devam ettirilebilir upload")."""

import trimesh

import app as app_module
from models import ConversionJob, db


def _glb_bytes():
    return bytes(trimesh.creation.box(extents=(0.1, 0.2, 0.3)).export(file_type="glb"))


def _init(client, filename, total_size, total_chunks):
    return client.post("/api/uploads/chunked/init", json={
        "filename": filename, "total_size": total_size, "total_chunks": total_chunks,
    })


def _put_chunks(client, upload_id, chunks):
    for i, chunk in enumerate(chunks):
        resp = client.put(f"/api/uploads/chunked/{upload_id}/chunks/{i}", data=chunk)
        assert resp.status_code == 200, resp.get_json()


def test_init_rejects_disallowed_extension(client):
    resp = _init(client, "malware.exe", 100, 1)
    assert resp.status_code == 400


def test_init_rejects_zip(client):
    resp = _init(client, "model.zip", 100, 1)
    assert resp.status_code == 400


def test_full_chunked_upload_completes_pipeline(client, monkeypatch):
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    data = _glb_bytes()
    mid = len(data) // 2
    chunks = [data[:mid], data[mid:]]

    init_resp = _init(client, "model.glb", len(data), len(chunks))
    assert init_resp.status_code == 201
    upload_id = init_resp.get_json()["upload_id"]

    _put_chunks(client, upload_id, chunks)

    status = client.get(f"/api/uploads/chunked/{upload_id}/status").get_json()
    assert status["success"] is True
    assert sorted(status["received"]) == [0, 1]

    complete = client.post(f"/api/uploads/chunked/{upload_id}/complete", json={})
    assert complete.status_code == 202, complete.get_json()
    body = complete.get_json()
    assert body["success"] is True
    job = db.session.get(ConversionJob, body["job_id"])
    assert job is not None
    assert job.payload["original_filename"] == "model.glb"


def test_complete_rejects_when_chunks_missing(client):
    data = _glb_bytes()
    init_resp = _init(client, "model.glb", len(data), 2)
    upload_id = init_resp.get_json()["upload_id"]
    _put_chunks(client, upload_id, [data])  # only chunk 0, never chunk 1

    resp = client.post(f"/api/uploads/chunked/{upload_id}/complete", json={})
    assert resp.status_code == 409
    assert resp.get_json()["missing_chunks"] == [1]


def test_status_and_put_reject_unknown_upload_id(client):
    assert client.get("/api/uploads/chunked/does-not-exist/status").status_code == 404
    assert client.put("/api/uploads/chunked/does-not-exist/chunks/0", data=b"x").status_code == 404


def test_reputting_same_chunk_index_is_idempotent(client):
    data = _glb_bytes()
    init_resp = _init(client, "model.glb", len(data), 1)
    upload_id = init_resp.get_json()["upload_id"]

    client.put(f"/api/uploads/chunked/{upload_id}/chunks/0", data=data)
    resp = client.put(f"/api/uploads/chunked/{upload_id}/chunks/0", data=data)
    assert resp.status_code == 200
    assert resp.get_json()["received_count"] == 1
