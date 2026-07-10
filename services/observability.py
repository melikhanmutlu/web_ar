import json
import logging
import os
from datetime import datetime, timezone


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        try:
            from flask import g, has_request_context, request
            if has_request_context():
                payload.update({
                    "request_id": getattr(g, "request_id", None),
                    "method": request.method,
                    "path": request.path,
                })
        except Exception:
            pass
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, default=str)


def configure_json_logging():
    root = logging.getLogger()
    for handler in root.handlers:
        stream = getattr(handler, "stream", None)
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass
    if os.environ.get("LOG_FORMAT", "text").lower() != "json":
        return False
    formatter = JsonLogFormatter()
    for handler in root.handlers:
        handler.setFormatter(formatter)
    return True


def initialize_external_observability(app):
    """Enable Sentry and OpenTelemetry when their env/config packages exist."""
    status = {"sentry": False, "opentelemetry": False}
    dsn = os.environ.get("SENTRY_DSN")
    if dsn:
        try:
            import sentry_sdk
            from sentry_sdk.integrations.flask import FlaskIntegration
            sentry_sdk.init(
                dsn=dsn,
                integrations=[FlaskIntegration()],
                environment=os.environ.get("SENTRY_ENVIRONMENT", os.environ.get("FLASK_ENV", "production")),
                traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
                send_default_pii=False,
            )
            status["sentry"] = True
        except ImportError:
            app.logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")

    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        try:
            from opentelemetry.instrumentation.flask import FlaskInstrumentor
            FlaskInstrumentor().instrument_app(app)
            status["opentelemetry"] = True
        except ImportError:
            app.logger.warning("OTEL exporter is configured but Flask instrumentation is not installed")
    return status
