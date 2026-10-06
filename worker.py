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
import signal
import threading
import time
import socket
from datetime import timedelta
from services.time_utils import datetime
from sqlalchemy import or_

from app import app, db
from services.ai_jobs import _advance_ai_job, _claim_ai_stage
from services.upload_pipeline import run_conversion_job
from config import WORKER_POLL_INTERVAL as POLL_INTERVAL, WORKER_STALE_MINUTES as STALE_PROCESSING_MINUTES
from models import AIGenerationJob, ConversionJob, User, WorkerHeartbeat
from services.plans import DEFAULT_PLAN, get_plan_config
from services import send_email
from services.email_preferences import unsubscribe_url, wants
from services.lifecycle_emails import run_onboarding_sweep, run_renewal_sweep
from services.weekly_report import send_weekly_report
from services.signal_mining import run_signal_mining
from site_settings import set_setting

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - worker - %(levelname)s - %(message)s",
)
logger = logging.getLogger("worker")

WORKER_ID = os.environ.get("WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}"


# While a job runs, a background thread keeps the worker heartbeat (and the
# job's own last_heartbeat_at) fresh: a single conversion can take many minutes
# with no progress commit, which made /healthz report the worker dead and let
# the stale sweep double-process the job.
JOB_HEARTBEAT_INTERVAL = float(os.environ.get("WORKER_JOB_HEARTBEAT_SECONDS", "15"))
# After SIGTERM/SIGINT the current job gets this long to finish; past it the job
# is put back in the queue immediately and the process exits.
SHUTDOWN_GRACE_SECONDS = float(os.environ.get("WORKER_SHUTDOWN_GRACE_SECONDS", "25"))
# A 'processing' job with no live owner (no fresh WorkerHeartbeat pointing at it
# and no job heartbeat) for this long is requeued without waiting for
# WORKER_STALE_MINUTES.
ORPHAN_SECONDS = float(os.environ.get("WORKER_ORPHAN_SECONDS", "60"))

_shutdown = threading.Event()
_shutdown_at = None


def request_shutdown(signum=None, frame=None):
    """Signal handler: stop claiming jobs and let the current one wind down."""
    global _shutdown_at
    if _shutdown_at is None:
        _shutdown_at = time.monotonic()
    _shutdown.set()
    logger.info("Shutdown requested; finishing current job (grace %ss)", SHUTDOWN_GRACE_SECONDS)


def install_signal_handlers():
    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


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
        previous = get_plan_config(user.plan).get("display_name") or user.plan
        user.plan = DEFAULT_PLAN
        user.plan_expires_at = None
        if user.email and wants(user, "renewal"):
            try:
                send_email(
                    user.email, "Your ARVision plan has ended",
                    f"Your ARVision {previous} plan has expired and your account is back on the "
                    f"Free plan. Renew any time from your billing page to restore your "
                    f"paid features.",
                    unsubscribe_url=unsubscribe_url(user, "renewal"),
                )
            except Exception as exc:
                logger.warning(f"Plan-expiry email failed for user {user.id}: {exc}")
    if expired:
        db.session.commit()


def _live_owned_job_ids(max_age_seconds):
    cutoff = datetime.utcnow() - timedelta(seconds=max_age_seconds)
    rows = WorkerHeartbeat.query.filter(
        WorkerHeartbeat.current_job_id.isnot(None),
        WorkerHeartbeat.last_seen_at >= cutoff,
    ).all()
    return {row.current_job_id for row in rows}


def requeue_orphaned_jobs():
    """Fast recovery: requeue 'processing' jobs that no live worker owns.

    Jobs a live worker heartbeat still points at are left alone. Used at
    startup and in the loop so a crashed worker's job doesn't wait for
    WORKER_STALE_MINUTES.
    """
    _requeue_jobs(stale_seconds=ORPHAN_SECONDS, only_orphaned=True)


def requeue_stale_jobs():
    _requeue_jobs()


def _requeue_jobs(stale_seconds=None, only_orphaned=False):
    """Recover orphaned 'processing' jobs (crashed worker).

    run_conversion_job increments and commits `attempts` *before* the pipeline
    runs, so a hard crash mid-conversion still persists the attempt. We respect
    max_attempts here: a job that keeps crashing the worker (toxic input) is
    marked failed instead of being requeued forever (poison-pill protection).
    """
    if stale_seconds is None:
        stale_seconds = STALE_PROCESSING_MINUTES * 60
    cutoff = datetime.utcnow() - timedelta(seconds=stale_seconds)
    stale = ConversionJob.query.filter(
        ConversionJob.status == "processing",
        db.func.coalesce(ConversionJob.last_heartbeat_at, ConversionJob.started_at) < cutoff,
    ).all()
    if only_orphaned and stale:
        owned = _live_owned_job_ids(stale_seconds)
        stale = [job for job in stale if job.id not in owned]
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


def requeue_job_now(job_id):
    """Put a 'processing' job straight back in the queue (graceful shutdown).

    The attempt that was started is refunded: being interrupted by a deploy is
    not the job's fault. Returns True when the row was still 'processing'.
    """
    now = datetime.utcnow()
    changed = ConversionJob.query.filter(
        ConversionJob.id == job_id, ConversionJob.status == "processing",
    ).update(
        {
            "status": "pending",
            "attempts": db.case(
                (db.func.coalesce(ConversionJob.attempts, 0) > 1, ConversionJob.attempts - 1),
                else_=0,
            ),
            "next_attempt_at": now,
            "last_heartbeat_at": now,
        },
        synchronize_session=False,
    )
    db.session.commit()
    return bool(changed)


class JobHeartbeat:
    """Background thread that heartbeats while a job runs and enforces the
    shutdown grace period (requeue + exit when the job can't finish in time)."""

    def __init__(self, job_id, interval=None, grace=None, exit_fn=None):
        self.job_id = job_id
        self.interval = JOB_HEARTBEAT_INTERVAL if interval is None else interval
        self.grace = SHUTDOWN_GRACE_SECONDS if grace is None else grace
        self.exit_fn = exit_fn or (lambda: os._exit(0))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="job-heartbeat", daemon=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=10)
        return False

    def _beat(self):
        now = datetime.utcnow()
        ConversionJob.query.filter(
            ConversionJob.id == self.job_id, ConversionJob.status == "processing",
        ).update({"last_heartbeat_at": now}, synchronize_session=False)
        WorkerHeartbeat.query.filter(WorkerHeartbeat.worker_id == WORKER_ID).update(
            {"last_seen_at": now, "current_job_id": self.job_id}, synchronize_session=False,
        )
        db.session.commit()

    def _run(self):
        last_beat = time.monotonic()
        tick = max(0.05, min(self.interval, 0.5))
        with app.app_context():
            while not self._stop.wait(tick):
                try:
                    if time.monotonic() - last_beat >= self.interval:
                        self._beat()
                        last_beat = time.monotonic()
                    if (_shutdown_at is not None
                            and time.monotonic() - _shutdown_at >= self.grace):
                        if requeue_job_now(self.job_id):
                            logger.warning(
                                "Job %s did not finish within %ss of shutdown; requeued",
                                self.job_id, self.grace,
                            )
                            WorkerHeartbeat.query.filter(
                                WorkerHeartbeat.worker_id == WORKER_ID
                            ).delete(synchronize_session=False)
                            db.session.commit()
                            self.exit_fn()
                        return
                except Exception as e:
                    logger.warning("Job heartbeat failed: %s", e)
                    db.session.rollback()
            db.session.remove()


def run_once():
    """Claim and process a single pending job; returns it, or None when idle."""
    if _shutdown.is_set():
        return None
    job = claim_next_job()
    if job is None:
        return None

    logger.info(f"Processing job {job.id} (attempt {(job.attempts or 0) + 1})")
    record_worker_heartbeat(job.id)
    with JobHeartbeat(job.id):
        run_conversion_job(job)
    record_worker_heartbeat()
    logger.info(f"Job {job.id} -> {job.status}")
    return job


def main():
    logger.info(
        f"Conversion worker started (poll {POLL_INTERVAL}s, "
        f"db {db.engine.dialect.name})"
    )
    # -inf, not 0.0: time.monotonic() counts from host boot, so on a container
    # up for less than an hour a 0.0 seed delayed the hourly sweeps until then.
    last_stale_sweep = float("-inf")
    record_worker_heartbeat()
    # A previous worker that died mid-job left it 'processing'; pick it up now
    # rather than after WORKER_STALE_MINUTES (jobs a live worker owns are kept).
    try:
        requeue_orphaned_jobs()
    except Exception as e:
        logger.warning(f"Startup orphan requeue failed: {e}")
        db.session.rollback()
    last_heartbeat = float("-inf")
    last_ai_reconcile = float("-inf")
    last_heartbeat_prune = float("-inf")
    while not _shutdown.is_set():
        try:
            if time.monotonic() - last_heartbeat > HEARTBEAT_INTERVAL:
                try:
                    set_setting("worker_heartbeat", datetime.utcnow().isoformat())
                except Exception as e:
                    logger.warning(f"Heartbeat write failed: {e}")
                last_heartbeat = time.monotonic()

            if time.monotonic() - last_stale_sweep > 60:
                requeue_stale_jobs()
                requeue_orphaned_jobs()
                record_worker_heartbeat()
                last_stale_sweep = time.monotonic()

            if time.monotonic() - last_ai_reconcile > 60:
                reconcile_stale_ai_jobs()
                last_ai_reconcile = time.monotonic()

            if time.monotonic() - last_heartbeat_prune > 3600:
                # Run each maintenance sweep independently: one failing sweep
                # must not skip the others OR prevent the timer below from
                # advancing (which would hot-loop the whole block every poll).
                for _sweep in (
                    prune_stale_heartbeats, prune_stale_chunk_sessions,
                    expire_stale_plans, run_renewal_sweep, run_onboarding_sweep,
                    send_weekly_report, run_signal_mining,
                ):
                    try:
                        _sweep()
                    except Exception as _sweep_err:
                        logger.error(
                            "Maintenance sweep %s failed: %s",
                            _sweep.__name__, _sweep_err, exc_info=True,
                        )
                        db.session.rollback()
                last_heartbeat_prune = time.monotonic()

            if run_once() is None:
                time.sleep(POLL_INTERVAL)
                continue
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
    if _shutdown.is_set():
        # Clean exit: drop our heartbeat row so nothing waits on a dead worker id.
        try:
            WorkerHeartbeat.query.filter(WorkerHeartbeat.worker_id == WORKER_ID).delete(
                synchronize_session=False
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
    logger.info("Worker exited cleanly")


if __name__ == "__main__":
    install_signal_handlers()
    with app.app_context():
        main()
