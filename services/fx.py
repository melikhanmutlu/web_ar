"""Price-currency -> TRY exchange rate for PayTR checkout.

Plan and credit-pack prices are listed in USD (services/plans.py), but PayTR
settles in TRY, so a PayTR checkout converts the list price at the day's
Central Bank of Turkey (TCMB) selling rate, with open.er-api.com as a backup
source. Rates are cached in SiteSetting for CACHE_SECONDS. When no source
answers, a cached rate up to MAX_STALE_SECONDS old is still used; past that
FxUnavailable is raised and the checkout is refused -- charging a real card at
a guessed rate is worse than asking the customer to retry.
"""

import logging
import re
import time
from decimal import ROUND_HALF_UP, Decimal

import requests

logger = logging.getLogger(__name__)

CACHE_SECONDS = 6 * 3600
MAX_STALE_SECONDS = 72 * 3600
REQUEST_TIMEOUT = 5
_TCMB_URL = "https://www.tcmb.gov.tr/kurlar/today.xml"
_BACKUP_URL = "https://open.er-api.com/v6/latest/{code}"


class FxUnavailable(RuntimeError):
    """No trustworthy exchange rate is available right now."""


def _rate_from_tcmb_xml(xml_text, code):
    """ForexSelling / Unit for `code` from TCMB's today.xml, or None."""
    block = re.search(
        rf'<Currency\b[^>]*\bCurrencyCode="{re.escape(code)}"[^>]*>(.*?)</Currency>',
        xml_text, re.S,
    )
    if not block:
        return None
    selling = re.search(r"<ForexSelling>\s*([\d.]+)\s*</ForexSelling>", block.group(1))
    unit = re.search(r"<Unit>\s*(\d+)\s*</Unit>", block.group(1))
    if not selling:
        return None
    return float(selling.group(1)) / (int(unit.group(1)) if unit else 1)


def _fetch_tcmb(code):
    resp = requests.get(_TCMB_URL, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return _rate_from_tcmb_xml(resp.text, code)


def _fetch_backup(code):
    resp = requests.get(_BACKUP_URL.format(code=code), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return float(resp.json()["rates"]["TRY"])


def get_try_rate(code="USD"):
    """How many TRY one unit of `code` costs today."""
    from site_settings import get_setting, set_setting

    code = code.upper()
    if code == "TRY":
        return 1.0
    rate_key, at_key = f"fx_{code.lower()}_try_rate", f"fx_{code.lower()}_try_rate_at"
    now = time.time()
    try:
        cached, cached_at = float(get_setting(rate_key)), float(get_setting(at_key))
    except (TypeError, ValueError):
        cached, cached_at = None, None
    if cached and cached > 0 and now - cached_at < CACHE_SECONDS:
        return cached

    for source in (_fetch_tcmb, _fetch_backup):
        try:
            rate = source(code)
        except Exception as e:
            logger.warning(f"{code}->TRY rate from {source.__name__} failed: {e}")
            continue
        if rate and rate > 0:
            set_setting(rate_key, rate)
            set_setting(at_key, now)
            return rate

    if cached and cached > 0 and now - cached_at < MAX_STALE_SECONDS:
        logger.warning(f"{code}->TRY: all sources down, using rate cached {int(now - cached_at)}s ago")
        return cached
    raise FxUnavailable(f"No current {code}->TRY exchange rate available.")


def to_try(amount, code="USD"):
    """(TRY amount rounded to kuruş, rate used) for `amount` in `code`."""
    rate = get_try_rate(code)
    try_amount = (Decimal(str(amount)) * Decimal(str(rate))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return try_amount, rate
