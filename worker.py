"""Background conversion worker (academic_ar pattern).

Polls the ConversionJob table and runs pending jobs through the same
pipeline /upload_model uses inline. Started as a separate process next to
gunicorn (see nixpacks.toml); enable queueing on the web side with
JOB_QUEUE=true, otherwise the web process keeps converting inline and this
worker simply idles.

On PostgreSQL, jobs are claimed with FOR UPDATE SKIP LOCKED so multiple
workers never grab the same job. SQLite (local dev) falls back to a plain
query — run a single worker there.

Also periodically reconciles AIGenerationJob rows (see
reconcile_stale_ai_jobs) -- those otherwise only advance via client-side
polling, so this loop is what unsticks one left behind by a closed browser
tab, independent of ConversionJob's own queue above.
"""

import logging
import os
import time
import socket
from datetime import timedelta
from services.time_utils import datetime
from sqlalchemy import or_

from app import (
    app, db, run_conversion_job, _advance_ai_job,
    _claim_ai_stage,
)
from config import WORKER_POLL_INTERVAL as POLL_INTERVAL, WORKER_STALE_MINUTES as STALE_PROCESSING_MINUTES
from models import AIGenerationJob, ConversionJob, User, WorkerHeartbeat
from services.plans import DEFAULT_PLAN
from services import send_email
from services.lifecycle_emails import run_onboarding_sweep, run_renewal_sweep
from site_settings import set_setting

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - worker - %(levelname)s - %(message)s",
)
logger = logging.getLogger("worker")

WORKER_ID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"


def record_worker_heartbeat(current_job_id=None):
    heartbeat = db.session.get(WorkerHeartbeat, WORKER_ID)
    now = datetime.utcnow()
    if heartbeat is None:
        heartbeat = WorkerHeartbeat(
            worker_id=WORKER_ID,
            hostname=socket.gethostname(),
            process_id=os.getpid(),
            started_at=now,
        )
        db.session.add(heartbeat)
    heartbeat.current_job_id = current_job_id
    heartbeat.last_seen_at = now
    db.session.commit()


# How often the loop records a liveness timestamp (site_settings-backed) so
# the admin dashboard can show "worker last seen Ns ago" instead of only
# inferring liveness indirectly from stale ConversionJob rows.
HEARTBEAT_INTERVAL = 30
# AI generations otherwise only advance via client-side polling of
# /api/generate-3d/<job_id>/status -- a closed browser tab leaves a job stuck
# in a non-terminal stage forever with nothing to move it along. This sweep
# re-checks any such job server-side, independent of whether a client is
# still watching (and independent of whether Meshy's webhook ever fires).
AI_RECONCILE_MINUTES = int(os.environ.get("AI_RECONCILE_MINUTES", "5"))


def claim_next_job():
    """Atomically claim the oldest pending job; returns it or None."""
    now = datetime.utcnow()
    query = (
        ConversionJob.query.filter(
            ConversionJob.status == "pending",
            or_(ConversionJob.next_attempt_at.is_(None), ConversionJob.next_attempt_at <= now),
        )
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
    job.last_heartbeat_at = job.started_at
    db.session.commit()
    # The DB row is now authoritatively 'processing' (so a crash before
    # run_conversion_job is recoverable by the stale sweep). run_conversion_job
    # owns the attempts increment and the terminal status transition; we hand it
    # an in-memory object that looks pending so those transitions stay uniform
    # with the inline path. The brief in-memory/DB disagreement is intentional.
    job.status = "pending"
    return job


def prune_stale_chunk_sessions(max_age_hours=24):
    """Remove abandoned resumable-upload chunk directories.

    A session is created on /api/uploads/chunked/init and only cleaned up by
    complete_chunked_upload's own finally -- any upload the client never
    finishes (tab closed mid-transfer, the exact scenario chunked upload
    exists for) leaves its chunks on the persistent volume forever.
    """
    import shutil

    root = os.path.join(app.config["TEMP_FOLDER"], "chunked")
    if not os.path.isdir(root):
        return
    cutoff = time.time() - max_age_hours * 3600
    pruned = 0
    for name in os.listdir(root):
        session_dir = os.path.join(root, name)
        try:
            if os.path.isdir(session_dir) and os.path.getmtime(session_dir) < cutoff:
                shutil.rmtree(session_dir, ignore_errors=True)
                pruned += 1
        except OSError:
            continue
    if pruned:
        logger.info(f"Pruned {pruned} abandoned chunked-upload session(s)")


def prune_stale_heartbeats(max_age_hours=24):
    """Delete WorkerHeartbeat rows not seen in `max_age_hours`.

    WORKER_ID is hostname:pid, so every process restart (the deploy loop
    restarts a crashed worker every few seconds) inserts a NEW row instead of
    updating one — nothing else ever removes old rows.
    """
    cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
    deleted = WorkerHeartbeat.query.filter(WorkerHeartbeat.last_seen_at < cutoff).delete(
        synchronize_session=False
    )
    if deleted:
        db.session.commit()
        logger.info(f"Pruned {deleted} stale worker heartbeat row(s)")


def expire_stale_plans():
    """Downgrade users whose paid plan has run out (plan_expires_at < now) back
    to Free, and email them once. Idempotent: after the reset plan_expires_at is
    NULL, so a user is only swept (and notified) a single time. _plan_name in
    services/plans.py already treats an expired plan as Free at enforcement
    time, so this sweep just makes the stored state catch up."""
    now = datetime.utcnow()
    expired = User.query.filter(
        User.plan_expires_at.isnot(None),
        User.plan_expires_at < now,
        User.plan != DEFAULT_PLAN,
    ).all()
    for user in expired:
        logger.info(f"Plan expired for user {user.id}: {user.plan} -> {DEFAULT_PLAN}")
        previous = user.plan
        user.plan = DEFAULT_PLAN
        user.plan_expires_at = None
        if user.email:
            try:
                send_email(
                    user.email, "Your ARVision plan has ended",
                    f"Your {previous} plan has expired and your account is back on the "
                    f"Free plan. Renew any time from your billing page to restore your "
                    f"paid features.",
                )
            except Exception as exc:
                logger.warning(f"Plan-expiry email failed for user {user.id}: {exc}")
    if expired:
        db.session.commit()


def requeue_stale_jobs():
    """Recover orphaned 'processing' jobs (crashed worker).

    run_conversion_job increments and commits `attempts` *before* the pipeline
    runs, so a hard crash mid-conversion still persists the attempt. We respect
    max_attempts here: a job that keeps crashing the worker (toxic input) is
    marked failed instead of being requeued forever (poison-pill protection).
    """
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_PROCESSING_MINUTES)
    stale = ConversionJob.query.filter(
        ConversionJob.status == "processing",
        db.func.coalesce(ConversionJob.last_heartbeat_at, ConversionJob.started_at) < cutoff,
    ).all()
    for job in stale:
        staged = (job.payload or {}).get("temp_file_path")
        if staged and not os.path.exists(staged):
            # The staged source is gone (e.g. cleaned up before a redeploy);
            # retrying can only fail. Fail it directly instead of reprocessing
            # doomed jobs on every restart (which floods the logs).
            logger.warning(f"Stale job {job.id} source missing; marking failed")
            job.status = "failed"
            job.error = "Source file is no longer available — please re-upload the model."
            job.finished_at = datetime.utcnow()
        elif (job.attempts or 0) >= (job.max_attempts or 1):
            logger.error(
                f"Stale job {job.id} exhausted attempts "
                f"({job.attempts}/{job.max_attempts}); marking failed"
            )
            job.status = "failed"
            job.error = "Conversion worker crashed repeatedly on this job."
            job.finished_at = datetime.utcnow()
        else:
            logger.warning(f"Requeueing stale job {job.id} (started {job.started_at})")
            job.status = "pending"
            job.next_attempt_at = datetime.utcnow()
    if stale:
        db.session.commit()


# _finalize_ai_job downloads the result GLB (and sometimes a
# USDZ) with no intermediate commit, so "finalizing"/"refining" can look
# stale under the ordinary AI_RECONCILE_MINUTES window while a real transfer
# is still in flight -- give the unstick logic a much longer grace period
# before treating those specific transitional stages as truly orphaned, so a
# slow-but-alive finalize doesn't get its claim ripped out from under it.
AI_ORPHAN_STAGE_GRACE_MINUTES = int(os.environ.get("AI_ORPHAN_STAGE_GRACE_MINUTES", str(AI_RECONCILE_MINUTES * 4)))


def _unstick_orphaned_ai_stage(job):
    """`stage` can be left at "refining"/"finalizing" -- values _claim_ai_stage
    moves it to right before starting the next Meshy call or finalizing, and
    which _advance_ai_job's `if job.stage ==` branches never match -- if the
    process dies (deploy, OOM) between that commit and the follow-up commit
    that would either complete the step or roll the claim back on exception.
    Left alone, the job spins in place forever (every reconcile sweep calls
    _advance_ai_job, which no-ops for these stage values) while still
    counting against the user's daily AI quota. Roll the claim back to the
    stage it was claimed from so the next _advance_ai_job call has a real
    branch to retry.

    Only fires past AI_ORPHAN_STAGE_GRACE_MINUTES (longer than the ordinary
    reconcile window -- see above), and via the same atomic
    UPDATE...WHERE stage=expected pattern _claim_ai_stage uses, so this can
    never stomp a job a concurrent _advance_ai_job call has already moved on
    from (e.g. a slow-but-alive finalize that completes and advances the
    stage between this function reading `job.stage` and committing the
    rollback)."""
    grace_cutoff = datetime.utcnow() - timedelta(minutes=AI_ORPHAN_STAGE_GRACE_MINUTES)
    if job.updated_at is not None and job.updated_at >= grace_cutoff:
        return
    if job.stage == "refining":
        if _claim_ai_stage(job.id, "refining", "preview"):
            db.session.refresh(job)
            logger.warning(f"AI job {job.id} had an orphaned 'refining' claim; rolled back to 'preview'")
    elif job.stage == "finalizing":
        # "finalizing" is claimed from "image" (image-kind jobs) or "refine"
        # (text-kind jobs) -- job.kind disambiguates which.
        target = "image" if job.kind == "image" else "refine"
        if _claim_ai_stage(job.id, "finalizing", target):
            db.session.refresh(job)
            logger.warning(f"AI job {job.id} had an orphaned 'finalizing' claim; rolled back to '{target}'")


def reconcile_stale_ai_jobs():
    """Re-advance any AIGenerationJob that hasn't moved in AI_RECONCILE_MINUTES.

    This is the actual fix for the "closed tab" problem -- a Meshy webhook is
    only a latency optimization on top of this; delivery of the webhook is
    never guaranteed (network blip, endpoint down during a deploy), so a
    periodic sweep is the one thing that's guaranteed to eventually unstick a
    job. Uses the exact same _advance_ai_job the client-poll route and the
    webhook receiver use, so the existing _claim_ai_stage atomic claim keeps
    this safe to run concurrently with either of them.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=AI_RECONCILE_MINUTES)
    stuck = AIGenerationJob.query.filter(
        AIGenerationJob.status == "generating",
        AIGenerationJob.updated_at < cutoff,
    ).all()
    for job in stuck:
        try:
            _unstick_orphaned_ai_stage(job)
            _advance_ai_job(job)
        except Exception as e:
            logger.warning(f"AI reconcile failed for job {job.id}: {e}")
            db.session.rollback()


def main():
    logger.info(
        f"Conversion worker started (poll {POLL_INTERVAL}s, "
        f"db {db.engine.dialect.name})"
    )
    last_stale_sweep = 0.0
    record_worker_heartbeat()
    last_heartbeat = 0.0
    last_ai_reconcile = 0.0
    last_heartbeat_prune = 0.0
    while True:
        try:
            if time.monotonic() - last_heartbeat > HEARTBEAT_INTERVAL:
                try:
                    set_setting("worker_heartbeat", datetime.utcnow().isoformat())
                except Exception as e:
                    logger.warning(f"Heartbeat write failed: {e}")
                last_heartbeat = time.monotonic()

            if time.monotonic() - last_stale_sweep > 60:
                requeue_stale_jobs()
                record_worker_heartbeat()
                last_stale_sweep = time.monotonic()

            if time.monotonic() - last_ai_reconcile > 60:
                reconcile_stale_ai_jobs()
                last_ai_reconcile = time.monotonic()

            if time.monotonic() - last_heartbeat_prune > 3600:
                prune_stale_heartbeats()
                prune_stale_chunk_sessions()
                expire_stale_plans()
                run_renewal_sweep()
                run_onboarding_sweep()
                last_heartbeat_prune = time.monotonic()

            job = claim_next_job()
            if job is None:
                time.sleep(POLL_INTERVAL)
                continue

            logger.info(f"Processing job {job.id} (attempt {(job.attempts or 0) + 1})")
            record_worker_heartbeat(job.id)
            run_conversion_job(job)
            record_worker_heartbeat()
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
