from datetime import datetime, timedelta

from models import ConversionJob, db


def test_health_and_request_correlation_headers(client):
    response = client.get("/healthz", headers={"X-Request-ID": "test-request-42"})
    assert response.status_code == 200
    assert response.get_json()["database"] == "up"
    assert response.headers["X-Request-ID"] == "test-request-42"
    assert "app;dur=" in response.headers["Server-Timing"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_metrics_report_queue_state_and_duration(client):
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
