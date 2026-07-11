"""Recovery of inline (queue-off) jobs whose daemon thread died on restart."""
from datetime import timedelta
from pathlib import Path

from werkzeug.security import generate_password_hash

import app as app_module
from models import ConversionJob, db
from services.time_utils import datetime


def _stale_job(job_id, **overrides):
    stale = datetime.utcnow() - timedelta(hours=1)
    fields = dict(
        id=job_id,
        status="processing",
        started_at=stale,
        last_heartbeat_at=stale,
        status_token_hash=generate_password_hash("poll-token"),
    )
    fields.update(overrides)
    job = ConversionJob(**fields)
    db.session.add(job)
    db.session.commit()
    return job


def _poll(client, job_id):
    return client.get(
        f"/api/upload-jobs/{job_id}", headers={"X-Job-Status-Token": "poll-token"}
    )


def test_stale_inline_job_with_staging_is_restarted(client, monkeypatch, tmp_path):
    restarted = []
    monkeypatch.setattr(app_module, "_start_local_conversion", restarted.append)
    job = _stale_job("stale-restartable", payload={"temp_dir": str(tmp_path)})

    response = _poll(client, job.id)

    assert response.status_code == 200
    assert response.get_json()["status"] == "pending"
    assert restarted == [job.id]
    assert any(event.event == "inline_recovered" for event in job.events)


def test_stale_inline_job_without_staging_fails(client, monkeypatch):
    restarted = []
    monkeypatch.setattr(app_module, "_start_local_conversion", restarted.append)
    job = _stale_job(
        "stale-lost", payload={"temp_dir": str(Path(".does-not-exist").resolve())}
    )

    response = _poll(client, job.id)

    assert response.get_json()["status"] == "failed"
    assert "interrupted" in job.error
    assert restarted == []


def test_fresh_processing_job_is_left_alone(client, monkeypatch):
    restarted = []
    monkeypatch.setattr(app_module, "_start_local_conversion", restarted.append)
    now = datetime.utcnow()
    job = _stale_job(
        "fresh-job", started_at=now, last_heartbeat_at=now, payload={"temp_dir": "x"}
    )

    response = _poll(client, job.id)

    assert response.get_json()["status"] == "processing"
    assert restarted == []


def test_queue_mode_defers_to_worker(client, monkeypatch):
    restarted = []
    monkeypatch.setattr(app_module, "_start_local_conversion", restarted.append)
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    job = _stale_job("queued-stale", payload={"temp_dir": "x"})

    response = _poll(client, job.id)

    assert response.get_json()["status"] == "processing"
    assert restarted == []
