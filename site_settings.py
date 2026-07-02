"""Typed access to admin-editable runtime settings (SiteSetting table).

Values are stored as strings and cached in-process for a short TTL, so a
change made in the admin panel propagates to every gunicorn worker within
~CACHE_TTL seconds without any cross-process signalling. Absent keys fall
back to the caller-provided default (usually the env-derived config value),
so an empty table changes nothing.
"""

import logging
import time

from models import db, SiteSetting

logger = logging.getLogger(__name__)

CACHE_TTL = 30  # seconds

_cache = {"at": 0.0, "values": {}}


def invalidate_cache():
    _cache["at"] = 0.0


def _load():
    now = time.monotonic()
    if now - _cache["at"] > CACHE_TTL:
        try:
            _cache["values"] = {s.key: s.value for s in SiteSetting.query.all()}
        except Exception as e:
            # Table missing (migration not applied yet) or transient DB error:
            # fall back to defaults instead of taking every request down.
            logger.warning(f"site_settings load failed, using defaults: {e}")
            db.session.rollback()
            _cache["values"] = {}
        _cache["at"] = now
    return _cache["values"]


def get_setting(key, default=None):
    value = _load().get(key)
    return default if value is None else value


def set_setting(key, value):
    row = db.session.get(SiteSetting, key)
    if row is None:
        row = SiteSetting(key=key)
        db.session.add(row)
    row.value = None if value is None else str(value)
    db.session.commit()
    invalidate_cache()


def setting_bool(key, default=False):
    raw = get_setting(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def setting_int(key, default=0):
    raw = get_setting(key)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default
