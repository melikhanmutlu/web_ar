"""Real-time job progress via SSE (Faz 4: "Gerçek zamanlı iş ilerlemesi")."""

import io

import app as app_module
import trimesh
from models import ConversionJob, db


def _parse_sse_payloads(body_text):
    payloads = []
    for line in body_text.splitlines():
        if line.startswith("data: "):
            payloads.append(line[len("data: "):])
    return payloads


def test_stream_requires_valid_token(client, monkeypatch):
    # Queue mode so /upload_model doesn't spawn a background thread that
    # outlives (and races with the teardown of) this test's in-memory DB.
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    source = trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(file_type="glb")
    response = client.post(
        '/upload_model',
        data={'file': (io.BytesIO(source), 'box.glb')},
        content_type='multipart/form-data',
    )
    job_id = response.get_json()['job_id']

    resp = client.get(f"/api/upload-jobs/{job_id}/stream")
    assert resp.status_code == 403


def test_stream_emits_terminal_status_and_closes(client, monkeypatch):
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    source = trimesh.creation.box(extents=(0.1, 0.2, 0.3)).export(file_type="glb")
    response = client.post(
        '/upload_model',
        data={'file': (io.BytesIO(source), 'box.glb'), 'compression': 'none'},
        content_type='multipart/form-data',
    )
    payload = response.get_json()
    job = db.session.get(ConversionJob, payload['job_id'])

    # Complete the job before streaming so the generator's first iteration
    # already sees a terminal state and returns immediately (no real-time
    # waiting needed in the test).
    app_module.run_conversion_job(job, allow_retry=False)
    db.session.refresh(job)
    assert job.status == 'completed'

    resp = client.get(
        f"/api/upload-jobs/{job.id}/stream",
        query_string={"status_token": payload["status_token"]},
    )
    assert resp.status_code == 200
    assert resp.mimetype == "text/event-stream"
    body = resp.get_data(as_text=True)
    events = _parse_sse_payloads(body)
    assert len(events) == 1
    import json
    last = json.loads(events[-1])
    assert last["status"] == "completed"
    assert last["viewer_url"] == f"/view/{payload['job_id']}"

    from pathlib import Path
    from models import UserModel
    model = db.session.get(UserModel, payload['job_id'])
    app_module.shutil.rmtree(Path(model.filename).parent, ignore_errors=True)


def test_stream_404s_for_unknown_job(client):
    resp = client.get("/api/upload-jobs/does-not-exist/stream")
    assert resp.status_code == 404
