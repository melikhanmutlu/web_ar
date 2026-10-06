"""Small in-process "budget per key per window" helper used to dedupe cheap
anonymous counter writes (view counts, anonymous likes).

State is per process (like the default Flask-Limiter memory:// storage), which
matches the single-worker gunicorn deployment; with several workers the budget
is simply applied per worker, which still bounds inflation. Keys are hashed so
no raw IP address is kept in memory longer than needed.
"""

import hashlib
import threading
import time

from flask import request
from flask_login import current_user

_lock = threading.Lock()
_hits = {}  # (namespace, digest) -> list of timestamps
_MAX_KEYS = 50000


def visitor_key():
    """Stable per-visitor key: the account when logged in, else the client IP."""
    try:
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return f"ip:{request.remote_addr or 'unknown'}"


def allow(namespace, subject, limit, window_seconds):
    """Return True (and record the hit) if `subject` has made fewer than
    `limit` hits in `namespace` during the last `window_seconds`."""
    now = time.monotonic()
    digest = hashlib.sha256(f"{subject}".encode()).hexdigest()
    key = (namespace, digest)
    with _lock:
        if len(_hits) >= _MAX_KEYS:
            for k in [k for k, ts in _hits.items() if not ts or now - ts[-1] > window_seconds]:
                del _hits[k]
            if len(_hits) >= _MAX_KEYS:
                _hits.clear()
        recent = [t for t in _hits.get(key, ()) if now - t < window_seconds]
        if len(recent) >= limit:
            _hits[key] = recent
            return False
        recent.append(now)
        _hits[key] = recent
        return True


def reset():
    """Forget all recorded hits (used by tests)."""
    with _lock:
        _hits.clear()
