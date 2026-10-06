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
    """Enable Sentry when SENTRY_DSN is set; a no-op otherwise.

    Runs when app.py is imported, so the web process and worker.py (which
    imports app) both report errors. The release is the deployed commit SHA.
    """
    status = {"sentry": False}
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return status
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=dsn,
            integrations=[FlaskIntegration()],
            release=os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("SOURCE_COMMIT") or None,
            environment=os.environ.get("SENTRY_ENVIRONMENT")
            or os.environ.get("RAILWAY_ENVIRONMENT_NAME")
            or os.environ.get("FLASK_ENV", "production"),
            traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0")),
            send_default_pii=False,
        )
        status["sentry"] = True
    except ImportError:
        app.logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
    return status
