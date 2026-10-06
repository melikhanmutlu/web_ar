import json
import os
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
    assert initialize_external_observability(client.application) == {"sentry": False}


def test_sentry_init_uses_release_and_environment(client, monkeypatch):
    import sys
    import types

    calls = {}
    fake = types.ModuleType("sentry_sdk")
    fake.init = lambda **kw: calls.update(kw)
    integrations = types.ModuleType("sentry_sdk.integrations")
    flask_int = types.ModuleType("sentry_sdk.integrations.flask")
    flask_int.FlaskIntegration = lambda: "flask-integration"
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations", integrations)
    monkeypatch.setitem(sys.modules, "sentry_sdk.integrations.flask", flask_int)
    monkeypatch.setenv("SENTRY_DSN", "https://key@example.invalid/1")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
    monkeypatch.delenv("SENTRY_TRACES_SAMPLE_RATE", raising=False)

    assert initialize_external_observability(client.application) == {"sentry": True}
    assert calls["release"] == "abc123"
    assert calls["environment"] == "staging"
    assert calls["traces_sample_rate"] == 0.0


def test_healthz_does_not_expose_observability(client):
    resp = client.get("/healthz")
    assert "observability" not in resp.get_json()


def test_json_formatter_escapes_unicode_for_legacy_consoles():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "✅ ready", (), None)
    rendered = JsonLogFormatter().format(record)
    assert "\\u2705" in rendered


def test_importing_app_does_not_write_app_log(tmp_path):
    """Logs go to stdout/stderr only; no unbounded app.log in the CWD."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parent.parent
    env = dict(os.environ, PYTHONPATH=str(repo), SECRET_KEY="test-secret",
               DATABASE_URL=f"sqlite:///{tmp_path / 'log.db'}", SKIP_DB_BOOTSTRAP="1",
               STORAGE_ROOT=str(tmp_path))
    result = subprocess.run([sys.executable, "-c", "import app"], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    assert not (tmp_path / "app.log").exists()
