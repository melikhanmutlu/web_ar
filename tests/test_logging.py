import json
import logging

from services.observability import JsonLogFormatter, initialize_external_observability


def test_json_formatter_includes_correlation_context(client):
    formatter = JsonLogFormatter()
    with client.application.test_request_context(
        "/api/test", method="POST", headers={"X-Request-ID": "log-test"}
    ):
        from flask import g
        g.request_id = "log-test"
        record = logging.LogRecord("arvision", logging.INFO, __file__, 1, "hello %s", ("world",), None)
        payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello world"
    assert payload["request_id"] == "log-test"
    assert payload["method"] == "POST"


def test_external_observability_is_safe_when_not_configured(client, monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert initialize_external_observability(client.application) == {
        "sentry": False, "opentelemetry": False
    }
