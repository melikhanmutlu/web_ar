from datetime import datetime, timedelta

from models import ConversionJob, db


def test_health_and_request_correlation_headers(client):
    response = client.get("/healthz", headers={"X-Request-ID": "test-request-42"})
    assert response.status_code == 200
    assert response.get_json()["database"] == "up"
    assert response.headers["X-Request-ID"] == "test-request-42"
    assert "app;dur=" in response.headers["Server-Timing"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_metrics_report_queue_state_and_duration(client, monkeypatch):
    import config
    # The suite runs with DATABASE_URL set (production-like); /metrics is only
    # open without a token in a true local-dev setup.
    monkeypatch.setattr(config, "_IS_PRODUCTION", False)
    now = datetime.utcnow()
    db.session.add_all([
        ConversionJob(id="metric-pending", status="pending"),
        ConversionJob(
            id="metric-complete",
            status="completed",
            started_at=now - timedelta(seconds=5),
            finished_at=now,
        ),
    ])
    db.session.commit()
    response = client.get("/metrics")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert 'arvision_conversion_jobs{status="pending"} 1' in text
    assert "arvision_conversion_duration_seconds 5.000" in text


def test_metrics_closed_without_token_in_production_like_env(client):
    # DATABASE_URL/RAILWAY_ENVIRONMENT count as production even if FLASK_ENV
    # is left at its development default (SEC-29).
    import config
    assert config._IS_PRODUCTION
    assert client.application.config.get("FLASK_ENV") != "production"
    assert client.get("/metrics").status_code == 404


def test_metrics_require_bearer_token_whenever_configured(client):
    app = client.application
    previous_token = app.config.get("METRICS_TOKEN")
    app.config.update(METRICS_TOKEN="metrics-secret")
    try:
        assert client.get("/metrics").status_code == 404
        assert client.get(
            "/metrics", headers={"Authorization": "Bearer wrong"}
        ).status_code == 404
        assert client.get(
            "/metrics", headers={"Authorization": "Bearer metrics-secret"}
        ).status_code == 200
    finally:
        app.config.update(METRICS_TOKEN=previous_token)


def test_production_metrics_require_bearer_token(client):
    app = client.application
    previous_env = app.config.get("FLASK_ENV")
    previous_token = app.config.get("METRICS_TOKEN")
    app.config.update(FLASK_ENV="production", METRICS_TOKEN="metrics-secret")
    try:
        assert client.get("/metrics").status_code == 404
        assert client.get(
            "/metrics", headers={"Authorization": "Bearer metrics-secret"}
        ).status_code == 200
    finally:
        app.config.update(FLASK_ENV=previous_env, METRICS_TOKEN=previous_token)


def test_live_probe_ignores_worker_and_maintenance(client, monkeypatch):
    """The deploy healthcheck must not fail because the worker hasn't sent a
    heartbeat yet, or because an admin switched maintenance mode on."""
    from site_settings import invalidate_cache, set_setting
    monkeypatch.setenv("JOB_QUEUE", "true")
    assert client.get("/healthz").status_code == 503  # no worker heartbeat
    set_setting("maintenance_mode", "true")
    invalidate_cache()
    try:
        resp = client.get("/healthz/live")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
    finally:
        set_setting("maintenance_mode", "false")
        invalidate_cache()
