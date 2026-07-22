"""Weekly business report email (growth F3.5)."""

from datetime import timedelta

import pytest

from app import db
from models import User
from services import weekly_report
from services.time_utils import datetime
from site_settings import get_setting, invalidate_cache


@pytest.fixture(autouse=True)
def _fresh_settings_cache():
    # The site_settings cache is process-global with a 30s TTL; the per-test DB
    # reset doesn't clear it, so drop it around each test for isolation.
    invalidate_cache()
    yield
    invalidate_cache()


def _admin(username="wr_admin"):
    user = User(username=username, email=f"{username}@test.com", is_admin=True)
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def _capture(monkeypatch, result=True):
    sent = []
    monkeypatch.setattr(weekly_report, "send_email",
                        lambda to, subj, body: (sent.append((to, subj, body)) or result))
    return sent


def _a_monday():
    d = datetime.utcnow()
    return d - timedelta(days=d.weekday())  # back to Monday


def test_report_sent_to_admins_on_monday(client, monkeypatch):
    sent = _capture(monkeypatch)
    _admin("wr_a1")
    _admin("wr_a2")
    assert weekly_report.send_weekly_report(now=_a_monday()) is True
    assert len(sent) == 2
    assert "weekly growth report" in sent[0][1]
    assert "Activation funnel" in sent[0][2]


def test_report_is_deduped_within_the_week(client, monkeypatch):
    sent = _capture(monkeypatch)
    _admin("wr_dedupe")
    monday = _a_monday()
    assert weekly_report.send_weekly_report(now=monday) is True
    assert weekly_report.send_weekly_report(now=monday) is False  # same week
    assert len(sent) == 1
    year, week, _ = monday.isocalendar()
    assert get_setting(weekly_report.LAST_SENT_SETTING) == f"{year}-W{week:02d}"


def test_no_send_on_non_report_weekday(client, monkeypatch):
    _capture(monkeypatch)
    _admin("wr_tue")
    monday = _a_monday()
    tuesday = monday + timedelta(days=1)
    assert weekly_report.send_weekly_report(now=tuesday) is False
    # force overrides the weekday guard
    assert weekly_report.send_weekly_report(now=tuesday, force=True) is True


def test_no_admins_means_no_send(client, monkeypatch):
    _capture(monkeypatch)
    assert weekly_report.send_weekly_report(now=_a_monday()) is False


def test_failed_delivery_does_not_mark_week_sent(client, monkeypatch):
    _capture(monkeypatch, result=False)  # SMTP down
    _admin("wr_fail")
    monday = _a_monday()
    assert weekly_report.send_weekly_report(now=monday) is False
    assert get_setting(weekly_report.LAST_SENT_SETTING) is None  # retryable next run
