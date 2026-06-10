"""Background conversion worker (academic_ar pattern).

Polls the ConversionJob table and runs pending jobs through the same
pipeline /upload_model uses inline. Started as a separate process next to
gunicorn (see nixpacks.toml); enable queueing on the web side with
JOB_QUEUE=true, otherwise the web process keeps converting inline and this
worker simply idles.

On PostgreSQL, jobs are claimed with FOR UPDATE SKIP LOCKED so multiple
workers never grab the same job. SQLite (local dev) falls back to a plain
query — run a single worker there.
"""

import logging
import os
import time
from datetime import datetime, timedelta

from app import app, db, run_conversion_job
from models import ConversionJob

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - worker - %(levelname)s - %(message)s",
)
logger = logging.getLogger("worker")

POLL_INTERVAL = float(os.environ.get("WORKER_POLL_INTERVAL", "2"))
# Jobs stuck in 'processing' longer than this are assumed orphaned
# (worker crashed mid-job) and put back to pending.
STALE_PROCESSING_MINUTES = int(os.environ.get("WORKER_STALE_MINUTES", "30"))


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
        db.session.rollback()  # release any FOR UPDATE transaction
        return None
    job.status = "processing"
    job.started_at = datetime.utcnow()
    db.session.commit()
    # run_conversion_job re-sets status/attempts itself; hand it a job that
    # looks pending again so its transitions stay uniform.
    job.status = "pending"
    return job


def requeue_stale_jobs():
    """Put orphaned 'processing' jobs (crashed worker) back to pending."""
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PROCESSING_MINUTES)
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
        f"Conversion worker started (poll {POLL_INTERVAL}s, "
        f"db {db.engine.dialect.name})"
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
