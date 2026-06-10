"""QR code generation for AR share links."""

import logging
import os
from pathlib import Path

import qrcode
from flask import current_app, has_request_context, request

logger = logging.getLogger(__name__)


def public_base_url() -> str:
    """Best public-facing base URL.

    Inside a request we trust the request host; in the worker process we
    fall back to PUBLIC_BASE_URL or Railway's injected RAILWAY_PUBLIC_DOMAIN.
    """
    if has_request_context():
        return request.url_root.rstrip("/")
    explicit = os.getenv("PUBLIC_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}"
    return "http://localhost:5000"


def generate_qr(model_id: str) -> str | None:
    """Create a QR PNG pointing at the public viewer URL; returns filename."""
    try:
        url = f"{public_base_url()}/m/{model_id}"
        image = qrcode.make(url, box_size=10, border=2)
        qr_dir = Path(current_app.config["QR_DIR"])
        qr_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{model_id}.png"
        image.save(str(qr_dir / filename))
        return filename
    except Exception as e:  # QR is auxiliary — never fail the conversion
        logger.warning(f"QR generation failed for {model_id}: {e}")
        return None
