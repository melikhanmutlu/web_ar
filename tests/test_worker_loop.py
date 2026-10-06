"""worker.py loop behaviour (OPS-21): run_once() claim/process/heartbeat, stale
job requeue (incl. poison-pill and missing-source paths), heartbeat rows and
main()'s per-sweep isolation."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

import app as app_module
import worker
from models import ConversionJob, WorkerHeartbeat, db
from services.time_utils import datetime


def _job(job_id, **kwargs):
    kwargs.setdefault("status", "pending")
    kwargs.setdefault("payload", {})
    job = ConversionJob(id=job_id, job_type="upload", **kwargs)
    db.session.add(job)
    db.session.commit()
    return job


def _fresh(job_id):
    db.session.expire_all()
    return db.session.get(ConversionJob, job_id)


def _heartbeat():
    db.session.expire_all()
    return db.session.get(WorkerHeartbeat, worker.WORKER_ID)


# --------------------------------------------------------------------------
# run_once
# --------------------------------------------------------------------------

def test_run_once_is_idle_when_no_job_is_pending(client):
    assert worker.run_once() is None
    assert _heartbeat() is None


def test_run_once_claims_processes_and_completes_job(client, monkeypatch):
    _job("job-1")
    seen = {}

    def fake_pipeline(payload, progress_callback=None):
        # While the job is being processed the heartbeat points at it and the
        # DB row is 'processing'.
        seen["heartbeat_job"] = _heartbeat().current_job_id
        seen["status"] = _fresh("job-1").status
        return "model-1"

    monkeypatch.setattr(app_module, "_run_upload_pipeline", fake_pipeline)
    job = worker.run_once()

    assert job.id == "job-1"
    assert seen == {"heartbeat_job": "job-1", "status": "processing"}
    done = _fresh("job-1")
    assert done.status == "completed" and done.model_id == "model-1"
    assert done.attempts == 1 and done.finished_at is not None
    # Heartbeat cleared once the job is finished.
    beat = _heartbeat()
    assert beat.current_job_id is None
    assert beat.last_seen_at >= beat.started_at


def test_run_once_processes_oldest_job_first_and_one_at_a_time(client, monkeypatch):
    now = datetime.utcnow()
    _job("newer", created_at=now)
    _job("older", created_at=now - timedelta(minutes=5))
    processed = []

    def fake_run(job):
        processed.append(job.id)
        job.status = "completed"
        db.session.commit()

    monkeypatch.setattr(worker, "run_conversion_job", fake_run)
    assert worker.run_once().id == "older"
    assert processed == ["older"]
    assert _fresh("newer").status == "pending"


def test_failed_job_is_rescheduled_with_backoff_not_reclaimed_immediately(client, monkeypatch):
    _job("flaky", max_attempts=3)

    def boom(payload, progress_callback=None):
        raise RuntimeError("converter crashed")

    monkeypatch.setattr(app_module, "_run_upload_pipeline", boom)
    assert worker.run_once().id == "flaky"
    job = _fresh("flaky")
    assert job.status == "pending" and job.attempts == 1
    assert job.next_attempt_at > datetime.utcnow()
    assert "converter crashed" in job.error
    # Backoff: the very next poll finds nothing to do.
    assert worker.run_once() is None


def test_job_dead_letters_after_max_attempts(client, monkeypatch):
    _job("doomed", max_attempts=1)
    monkeypatch.setattr(app_module, "_run_upload_pipeline",
                        lambda payload, progress_callback=None: (_ for _ in ()).throw(
                            RuntimeError("bad input")))
    worker.run_once()
    job = _fresh("doomed")
    assert job.status == "dead_letter" and job.finished_at is not None
    assert worker.run_once() is None


# --------------------------------------------------------------------------
# heartbeat rows
# --------------------------------------------------------------------------

def test_record_worker_heartbeat_creates_then_updates_one_row(client):
    worker.record_worker_heartbeat("job-x")
    first = _heartbeat()
    assert first.current_job_id == "job-x" and first.process_id
    started = first.started_at
    worker.record_worker_heartbeat()
    assert WorkerHeartbeat.query.count() == 1
    again = _heartbeat()
    assert again.current_job_id is None
    assert again.started_at == started
    assert again.last_seen_at >= first.last_seen_at


def test_prune_stale_heartbeats_only_removes_old_rows(client):
    old = WorkerHeartbeat(worker_id="dead:1", last_seen_at=datetime.utcnow() - timedelta(hours=30))
    live = WorkerHeartbeat(worker_id="live:2", last_seen_at=datetime.utcnow())
    db.session.add_all([old, live])
    db.session.commit()
    worker.prune_stale_heartbeats()
    assert [h.worker_id for h in WorkerHeartbeat.query.all()] == ["live:2"]


# --------------------------------------------------------------------------
# requeue_stale_jobs
# --------------------------------------------------------------------------

def _stale_time():
    return datetime.utcnow() - timedelta(minutes=worker.STALE_PROCESSING_MINUTES + 5)


def test_stale_processing_job_is_requeued(client):
    _job("stale", status="processing", attempts=1, max_attempts=3,
         started_at=_stale_time(), last_heartbeat_at=_stale_time())
    worker.requeue_stale_jobs()
    job = _fresh("stale")
    assert job.status == "pending"
    assert job.next_attempt_at <= datetime.utcnow()
    # ...and the requeued job is claimable again by the loop.
    assert worker.claim_next_job().id == "stale"


def test_recent_heartbeat_keeps_long_running_job_alive(client):
    _job("alive", status="processing", started_at=_stale_time(),
         last_heartbeat_at=datetime.utcnow())
    worker.requeue_stale_jobs()
    assert _fresh("alive").status == "processing"


def test_stale_job_without_heartbeat_falls_back_to_started_at(client):
    _job("no-beat", status="processing", attempts=1, max_attempts=3,
         started_at=_stale_time(), last_heartbeat_at=None)
    worker.requeue_stale_jobs()
    assert _fresh("no-beat").status == "pending"


def test_poison_pill_job_is_failed_not_requeued_forever(client):
    _job("poison", status="processing", attempts=2, max_attempts=2,
         started_at=_stale_time(), last_heartbeat_at=_stale_time())
    worker.requeue_stale_jobs()
    job = _fresh("poison")
    assert job.status == "failed" and job.finished_at is not None
    assert "crashed repeatedly" in job.error
    assert worker.claim_next_job() is None


def test_stale_job_with_missing_staged_source_is_failed(client, tmp_path):
    _job("orphan", status="processing", attempts=1, max_attempts=3,
         payload={"temp_file_path": str(tmp_path / "gone.stl")},
         started_at=_stale_time(), last_heartbeat_at=_stale_time())
    worker.requeue_stale_jobs()
    job = _fresh("orphan")
    assert job.status == "failed" and "re-upload" in job.error


def test_stale_job_with_existing_staged_source_is_requeued(client, tmp_path):
    staged = tmp_path / "there.stl"
    staged.write_bytes(b"solid")
    _job("kept", status="processing", attempts=1, max_attempts=3,
         payload={"temp_file_path": str(staged)},
         started_at=_stale_time(), last_heartbeat_at=_stale_time())
    worker.requeue_stale_jobs()
    assert _fresh("kept").status == "pending"


# --------------------------------------------------------------------------
# main(): one failing sweep must not starve the others or the job queue
# --------------------------------------------------------------------------

def test_main_loop_isolates_maintenance_sweeps_and_processes_jobs(client, monkeypatch):
    _job("loop-job")
    calls = []

    def record(name, fail=False):
        def sweep():
            calls.append(name)
            if fail:
                raise RuntimeError(f"{name} blew up")
        sweep.__name__ = name
        return sweep

    for name in ("prune_stale_heartbeats", "prune_stale_chunk_sessions",
                 "expire_stale_plans", "run_renewal_sweep", "run_onboarding_sweep",
                 "send_weekly_report", "run_signal_mining"):
        monkeypatch.setattr(worker, name, record(name, fail=(name == "expire_stale_plans")))
    monkeypatch.setattr(worker, "requeue_stale_jobs", record("requeue_stale_jobs"))
    monkeypatch.setattr(worker, "reconcile_stale_ai_jobs", record("reconcile_stale_ai_jobs"))
    monkeypatch.setattr(worker, "set_setting", lambda *a, **k: calls.append("set_setting"))

    def fake_run(job):
        # Like the real pipeline, leave the job in a terminal state.
        calls.append(f"run:{job.id}")
        job.status = "completed"
        db.session.commit()

    monkeypatch.setattr(worker, "run_conversion_job", fake_run)

    def stop(_seconds):
        raise KeyboardInterrupt

    # main() seeds its timers with 0.0 and compares against time.monotonic(),
    # which is boot-relative; pin it so every sweep is due on the first pass.
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: 1e6, sleep=stop))

    worker.main()  # first iteration runs everything, 2nd finds no job -> sleep -> stop

    assert calls[0] == "set_setting"
    for name in ("requeue_stale_jobs", "reconcile_stale_ai_jobs",
                 "prune_stale_heartbeats", "prune_stale_chunk_sessions",
                 "expire_stale_plans", "run_renewal_sweep", "run_onboarding_sweep",
                 "send_weekly_report", "run_signal_mining"):
        assert calls.count(name) == 1, name
    # The sweep after the failing one still ran, and the job was still processed.
    assert calls.index("run_renewal_sweep") > calls.index("expire_stale_plans")
    assert calls.count("run:loop-job") == 1
    assert _heartbeat() is not None


def test_main_loop_survives_unexpected_errors(client, monkeypatch):
    sleeps = []

    def flaky_run_once():
        raise RuntimeError("db hiccup")

    def sleep(seconds):
        sleeps.append(seconds)

    calls = {"n": 0}

    def flaky_then_stop():
        calls["n"] += 1
        if calls["n"] > 1:
            raise KeyboardInterrupt
        return flaky_run_once()

    monkeypatch.setattr(worker, "run_once", flaky_then_stop)
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: 1e6, sleep=sleep))
    monkeypatch.setattr(worker, "set_setting", lambda *a, **k: None)
    for name in ("requeue_stale_jobs", "reconcile_stale_ai_jobs", "prune_stale_heartbeats",
                 "prune_stale_chunk_sessions", "expire_stale_plans", "run_renewal_sweep",
                 "run_onboarding_sweep", "send_weekly_report", "run_signal_mining"):
        monkeypatch.setattr(worker, name, lambda: None)
    worker.main()
    assert sleeps == [worker.POLL_INTERVAL]  # error path backs off instead of crashing
