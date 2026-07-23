"""USD -> TRY exchange rate for PayTR checkout.

Plan prices are USD-denominated (services/plans.py), but PayTR settles in
TRY, so a PayTR checkout must convert the USD price to TRY at the current
rate before creating the payment. The rate is cached in SiteSetting so a
live lookup only happens once per CACHE_SECONDS; a failed lookup falls back
to the last known cached rate, and finally to USD_TRY_FALLBACK_RATE if
nothing has ever been cached -- a checkout must never hard-fail just
because the FX API had a bad moment.
"""

import logging
import os
import time
from decimal import ROUND_HALF_UP, Decimal

import requests

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
REQUEST_TIMEOUT = 5
FALLBACK_RATE = float(os.getenv("USD_TRY_FALLBACK_RATE", "34.0"))
_RATE_URL = "https://open.er-api.com/v6/latest/USD"
_RATE_KEY = "fx_usd_try_rate"
_RATE_AT_KEY = "fx_usd_try_rate_at"


def get_usd_try_rate():
    """Current USD->TRY rate, refreshed at most once every CACHE_SECONDS."""
    from site_settings import get_setting, set_setting

    cached = get_setting(_RATE_KEY)
    cached_at = get_setting(_RATE_AT_KEY)
    now = time.time()
    if cached and cached_at:
        try:
            if now - float(cached_at) < CACHE_SECONDS and float(cached) > 0:
                return float(cached)
        except (TypeError, ValueError):
            pass

    try:
        resp = requests.get(_RATE_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        rate = float(resp.json()["rates"]["TRY"])
        if rate > 0:
            set_setting(_RATE_KEY, rate)
            set_setting(_RATE_AT_KEY, now)
            return rate
    except Exception as e:
        logger.warning(f"USD->TRY rate fetch failed, using cached/fallback rate: {e}")

    if cached:
        try:
            if float(cached) > 0:
                return float(cached)
        except (TypeError, ValueError):
            pass
    # API is down AND no valid rate has ever been cached: this hardcoded rate
    # is about to convert a real charge. Surface it so ops can catch a
    # cold-cache + API-outage window.
    logger.warning(
        "USD->TRY: API unavailable and no valid cached rate; using hardcoded "
        "fallback rate %s for a live charge", FALLBACK_RATE
    )
    return FALLBACK_RATE


def usd_to_try(usd_amount):
    """Convert a USD amount to a TRY Decimal, rounded to 2 places."""
    rate = get_usd_try_rate()
    return (Decimal(str(usd_amount)) * Decimal(str(rate))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
