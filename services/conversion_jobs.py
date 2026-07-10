from datetime import datetime, timedelta

from sqlalchemy.orm.attributes import flag_modified


class ConversionJobService:
    """Durable state machine for conversion jobs and retry scheduling."""

    def __init__(self, db, *, retry_base_seconds=15, retry_max_seconds=900):
        self.db = db
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds

    def update_progress(self, job, *, progress=None, stage=None, detail=None):
        payload = dict(job.payload or {})
        if progress is not None:
            payload["progress"] = int(max(0, min(100, progress)))
        if stage is not None:
            payload["stage"] = stage
        if detail is not None:
            payload["detail"] = detail
        job.payload = payload
        flag_modified(job, "payload")
        self.db.session.commit()

    def record(self, job, event, message=None, level="info"):
        from models import ConversionJobEvent
        self.db.session.add(ConversionJobEvent(
            job_id=job.id, level=level, event=event,
            message=str(message)[:2000] if message else None,
            attempt=job.attempts,
        ))
        self.db.session.commit()

    def start(self, job):
        job.status = "processing"
        job.started_at = datetime.utcnow()
        job.last_heartbeat_at = job.started_at
        job.next_attempt_at = None
        job.attempts = (job.attempts or 0) + 1
        self.db.session.commit()
        self.record(job, "started", "Conversion attempt started")

    def heartbeat(self, job):
        job.last_heartbeat_at = datetime.utcnow()
        self.db.session.commit()
        self.record(job, "completed", f"Model {model_id} is ready")

    def succeed(self, job, model_id):
        job.model_id = model_id
        job.status = "completed"
        job.error = None
        job.finished_at = datetime.utcnow()
        job.next_attempt_at = None
        self.db.session.commit()

    def fail(self, job, error, *, allow_retry=True):
        self.db.session.rollback()
        retry = allow_retry and job.attempts < (job.max_attempts or 1)
        job.error = str(error)[:2000]
        if retry:
            delay = min(
                self.retry_max_seconds,
                self.retry_base_seconds * (2 ** max(0, job.attempts - 1)),
            )
            job.status = "pending"
            job.next_attempt_at = datetime.utcnow() + timedelta(seconds=delay)
            job.finished_at = None
        else:
            job.status = "dead_letter" if allow_retry else "failed"
            job.next_attempt_at = None
            job.finished_at = datetime.utcnow()
        self.db.session.commit()
        self.record(
            job,
            "retry_scheduled" if retry else ("dead_lettered" if allow_retry else "failed"),
            error,
            level="warning" if retry else "error",
        )
        return retry
