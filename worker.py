"""Background conversion worker.

Polls the ConversionJob table for pending rows and runs them through the
same pipeline the upload endpoint uses inline. Started as a separate process
next to gunicorn by the Railway start command (nixpacks.toml); enable
queueing on the web side with JOB_QUEUE=true, otherwise the web process
converts inline and this worker simply idles.

On PostgreSQL pending jobs are claimed with FOR UPDATE SKIP LOCKED so
multiple workers never grab the same job; SQLite (local dev) falls back to a
plain query — run a single worker there.
"""

import logging
import os
import time
from datetime import datetime, timedelta, timezone

from app import app, db, run_conversion_job
from webar.models import ConversionJob

logger = logging.getLogger("worker")

POLL_INTERVAL = float(os.environ.get("WORKER_POLL_INTERVAL", "2"))
# Jobs stuck in 'processing' longer than this are assumed orphaned (worker
# crashed mid-job) and are put back to pending.
STALE_PROCESSING_MINUTES = int(os.environ.get("WORKER_STALE_MINUTES", "30"))


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def claim_next_job():
    """Atomically claim the oldest pending job; returns it or None."""
    query = (
        ConversionJob.query.filter_by(status="pending")
        .order_by(ConversionJob.created_at)
    )
    if db.engine.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    job = query.first()
    if job is None:
        db.session.rollback()  # release the FOR UPDATE transaction
        return None
    job.status = "processing"
    job.started_at = _utcnow()
    db.session.commit()
    return job


def requeue_stale_jobs():
    cutoff = _utcnow() - timedelta(minutes=STALE_PROCESSING_MINUTES)
    stale = ConversionJob.query.filter(
        ConversionJob.status == "processing",
        ConversionJob.started_at < cutoff,
    ).all()
    for job in stale:
        logger.warning(f"Requeueing stale job {job.id} (started {job.started_at})")
        job.status = "pending"
    if stale:
        db.session.commit()


def main():
    logger.info(
        f"Conversion worker started (poll {POLL_INTERVAL}s, db {db.engine.dialect.name})"
    )
    last_stale_sweep = 0.0
    while True:
        try:
            if time.monotonic() - last_stale_sweep > 60:
                requeue_stale_jobs()
                last_stale_sweep = time.monotonic()

            job = claim_next_job()
            if job is None:
                time.sleep(POLL_INTERVAL)
                continue

            logger.info(f"Processing job {job.id} (attempt {(job.attempts or 0) + 1})")
            run_conversion_job(job)
            logger.info(f"Job {job.id} -> {job.status}")
        except KeyboardInterrupt:
            logger.info("Worker stopped")
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}", exc_info=True)
            try:
                db.session.rollback()
            except Exception:
                pass
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    with app.app_context():
        main()
