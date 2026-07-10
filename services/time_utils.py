"""UTC-compatible datetime helpers for naive database columns."""

from datetime import datetime as _datetime, timezone


class datetime(_datetime):
    """Drop-in datetime with a non-deprecated naive-UTC clock.

    Existing database columns store naive UTC values. Returning an aware value
    without a schema migration would mix incompatible timestamp semantics, so
    the timezone is intentionally removed after reading the UTC clock.
    """

    @classmethod
    def utcnow(cls):
        return cls.now(timezone.utc).replace(tzinfo=None)
