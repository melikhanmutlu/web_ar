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


@health_bp.route("/healthz")
def healthz():
    """Liveness/readiness probe including database connectivity."""
    import app as app_module

    try:
        db.session.execute(db.text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        return jsonify({"status": "unhealthy", "database": "down"}), 503
    result = {"status": "ok", "database": "up", "observability": app_module.OBSERVABILITY_STATUS}
    if os.environ.get("JOB_QUEUE", "false").lower() in ("true", "1", "yes"):
        cutoff = datetime.utcnow() - timedelta(
            seconds=int(os.environ.get("WORKER_HEALTH_MAX_AGE_SECONDS", "90"))
        )
        active_workers = WorkerHeartbeat.query.filter(
            WorkerHeartbeat.last_seen_at >= cutoff
        ).count()
        result["active_workers"] = active_workers
        if active_workers == 0:
            result["status"] = "degraded"
            return jsonify(result), 503
    return jsonify(result)


@health_bp.route("/metrics")
def metrics():
    """Small Prometheus-compatible operational surface without user data."""
    configured_token = current_app.config.get("METRICS_TOKEN", "")
    if current_app.config.get("FLASK_ENV") == "production":
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
