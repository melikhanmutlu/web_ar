"""Displayed timestamps render in the GMT+3 (Turkey) display timezone while
storage stays naive UTC (see services/time_utils and app.py's localdt filter)."""
from datetime import datetime

import app as app_module
from models import UserModel


def test_localdt_filter_shifts_utc_to_gmt3():
    # 22:30 UTC -> 01:30 next day in GMT+3 (also checks the date rolls over)
    utc = datetime(2026, 1, 1, 22, 30, 0)
    assert app_module._localdt(utc, "%Y-%m-%d %H:%M") == "2026-01-02 01:30"


def test_localdt_filter_is_none_safe():
    assert app_module._localdt(None) == ""


def test_model_upload_date_formatted_is_gmt3():
    m = UserModel(upload_date=datetime(2026, 1, 1, 22, 30, 0))
    assert m.upload_date_formatted == "2026-01-02 01:30"
