"""Liveness/readiness probe and a small Prometheus-compatible metrics surface."""

import logging
import os
import secrets
from datetime import timedelta

from flask import Blueprint, abort, current_app, jsonify, request

from services.time_utils import datetime
from models import ConversionJob, WorkerHeartbeat, db

health_bp = Blueprint("health", __name__)
logger = logging.getLogger(__name__)


def _storage_writable():
    """True if the converted-model storage root accepts a write+delete."""
    try:
        root = current_app.config.get("CONVERTED_FOLDER")
        if not root:
            return True
        os.makedirs(root, exist_ok=True)
        probe = os.path.join(root, f".healthz-{os.getpid()}")
        with open(probe, "w") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except Exception:
        logger.exception("Storage health check failed")
        return False


def _active_worker_count():
    cutoff = datetime.utcnow() - timedelta(
        seconds=int(os.environ.get("WORKER_HEALTH_MAX_AGE_SECONDS", "90"))
    )
    return WorkerHeartbeat.query.filter(WorkerHeartbeat.last_seen_at >= cutoff).count()


@health_bp.route("/healthz")
def healthz():
    """Liveness/readiness probe including database connectivity."""
    import app as app_module

    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        return jsonify({"status": "unhealthy", "database": "down"}), 503
    # Storage writability — a full/read-only volume still leaves the DB
    # reachable, so without this probe /healthz stayed 200 while uploads failed.
    storage_ok = _storage_writable()
    result = {
        "status": "ok", "database": "up", "storage": "up" if storage_ok else "down",
        "observability": app_module.OBSERVABILITY_STATUS,
    }
    if not storage_ok:
        result["status"] = "degraded"
        return jsonify(result), 503
    if os.environ.get("JOB_QUEUE", "false").lower() in ("true", "1", "yes"):
        active_workers = _active_worker_count()
        result["active_workers"] = active_workers
        if active_workers == 0:
            result["status"] = "degraded"
            return jsonify(result), 503
    return jsonify(result)


@health_bp.route("/healthz/worker")
def healthz_worker():
    """Dedicated worker-liveness probe, so a deployment can watch the worker
    without coupling it to the web instance's readiness probe (a dead worker
    otherwise 503s /healthz and can pull healthy web instances from the LB)."""
    if os.environ.get("JOB_QUEUE", "false").lower() not in ("true", "1", "yes"):
        return jsonify({"status": "ok", "job_queue": "disabled"})
    active = _active_worker_count()
    if active == 0:
        return jsonify({"status": "degraded", "active_workers": 0}), 503
    return jsonify({"status": "ok", "active_workers": active})


@health_bp.route("/metrics")
def metrics():
    """Small Prometheus-compatible operational surface without user data."""
    configured_token = current_app.config.get("METRICS_TOKEN", "")
    if configured_token or current_app.config.get("FLASK_ENV") == "production":
        supplied_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        if not configured_token or not secrets.compare_digest(supplied_token, configured_token):
            abort(404)
    states = dict(
        db.session.query(ConversionJob.status, db.func.count(ConversionJob.id))
        .group_by(ConversionJob.status).all()
    )
    lines = [
        "# HELP arvision_conversion_jobs Conversion jobs by current state",
        "# TYPE arvision_conversion_jobs gauge",
    ]
    for state in ("pending", "processing", "completed", "failed", "dead_letter"):
        lines.append(f'arvision_conversion_jobs{{status="{state}"}} {states.get(state, 0)}')
    completed = ConversionJob.query.filter(
        ConversionJob.finished_at.isnot(None), ConversionJob.started_at.isnot(None)
    ).order_by(ConversionJob.finished_at.desc()).limit(100).all()
    durations = [(j.finished_at - j.started_at).total_seconds() for j in completed]
    lines.extend([
        "# HELP arvision_conversion_duration_seconds Average duration of recent conversions",
        "# TYPE arvision_conversion_duration_seconds gauge",
        f"arvision_conversion_duration_seconds {sum(durations) / len(durations) if durations else 0:.3f}",
    ])
    return "\n".join(lines) + "\n", 200, {"Content-Type": "text/plain; version=0.0.4"}
