from datetime import datetime, timedelta
from pathlib import Path
from werkzeug.security import generate_password_hash

from models import ConversionJob, db
from services import ConversionJobService
from worker import claim_next_job, record_worker_heartbeat, WORKER_ID


def test_conversion_job_retries_with_backoff_then_dead_letters(client):
    service = ConversionJobService(db, retry_base_seconds=10, retry_max_seconds=60)
    job = ConversionJob(id="retry-job", status="pending", max_attempts=2)
    db.session.add(job)
    db.session.commit()

    service.start(job)
    assert job.attempts == 1
    assert service.fail(job, RuntimeError("converter crashed"), allow_retry=True)
    assert job.status == "pending"
    assert job.next_attempt_at > datetime.utcnow()

    service.start(job)
    assert not service.fail(job, RuntimeError("still broken"), allow_retry=True)
    assert job.status == "dead_letter"
    assert job.finished_at is not None
    assert [event.event for event in job.events] == [
        "started", "retry_scheduled", "started", "dead_lettered"
    ]


def test_worker_claim_respects_retry_schedule_and_records_heartbeat(client):
    future = ConversionJob(
        id="future-job", status="pending", next_attempt_at=datetime.utcnow() + timedelta(hours=1)
    )
    due = ConversionJob(
        id="due-job", status="pending", next_attempt_at=datetime.utcnow() - timedelta(seconds=1)
    )
    db.session.add_all([future, due])
    db.session.commit()

    claimed = claim_next_job()
    assert claimed.id == "due-job"
    record_worker_heartbeat(claimed.id)
    heartbeat = db.session.get(__import__("models").WorkerHeartbeat, WORKER_ID)
    assert heartbeat.current_job_id == "due-job"


def test_dead_letter_can_be_manually_requeued_with_status_token(client):
    staged = Path(".test-dead-letter").resolve()
    staged.mkdir(exist_ok=True)
    job = ConversionJob(
        id="dead-job",
        status="dead_letter",
        attempts=2,
        payload={"temp_dir": str(staged)},
        status_token_hash=generate_password_hash("requeue-token"),
    )
    db.session.add(job)
    db.session.commit()
    denied = client.post(f"/api/upload-jobs/{job.id}/retry")
    assert denied.status_code == 403
    response = client.post(
        f"/api/upload-jobs/{job.id}/retry",
        headers={"X-Job-Status-Token": "requeue-token"},
    )
    assert response.status_code == 202
    assert job.status == "pending"
    assert job.attempts == 0
    staged.rmdir()
