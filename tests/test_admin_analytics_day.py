"""Coverage for the analytics day-drill-down page and the `iso` field
added to admin.py's `_daily_series` helper."""

import uuid
from datetime import datetime, timedelta

import pytest

from admin import _DISPLAY_TZ_OFFSET, _daily_series
from app import db
from models import AIGenerationJob, User, UserModel


@pytest.fixture
def admin_user(client):
    user = User(username="dayadmin", email="dayadmin@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def owner(client):
    user = User(username="dayowner", email="dayowner@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    return user


def local_today():
    """The admin pages bucket by the display timezone (UTC+3 by default), so
    "today" is the local date -- not UTC's, which differs 21:00-24:00 UTC."""
    return (datetime.utcnow() + _DISPLAY_TZ_OFFSET).date()


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=False)


def make_model(user_id, upload_date=None, model_id=None):
    model = UserModel(id=model_id or str(uuid.uuid4()), filename="x/model.glb",
                      file_size=10, file_type="glb", user_id=user_id,
                      upload_date=upload_date or datetime.utcnow())
    db.session.add(model)
    db.session.commit()
    return model


def test_daily_series_includes_iso_field(client):
    series = _daily_series(User.created_at, days=3)
    assert len(series) == 3
    for point in series:
        assert "iso" in point
        datetime.strptime(point["iso"], "%Y-%m-%d")
    assert series[-1]["iso"] == local_today().isoformat()


def test_analytics_day_requires_admin(client, owner):
    today = local_today().isoformat()
    resp = client.get(f"/admin/analytics/day/{today}")
    assert resp.status_code == 302

    login(client, "dayowner", "testpassword")
    assert client.get(f"/admin/analytics/day/{today}").status_code == 404


@pytest.mark.parametrize("bad", ["not-a-date", "2024-13-40", "20240101"])
def test_analytics_day_rejects_malformed_date(client, admin_user, bad):
    login(client, "dayadmin", "adminpassword")
    assert client.get(f"/admin/analytics/day/{bad}").status_code == 404


def test_analytics_day_rejects_future_date(client, admin_user):
    future = (local_today() + timedelta(days=1)).isoformat()
    login(client, "dayadmin", "adminpassword")
    assert client.get(f"/admin/analytics/day/{future}").status_code == 404


def test_analytics_day_shows_that_days_activity_only(client, admin_user, owner):
    today = datetime.utcnow()
    yesterday = today - timedelta(days=1)

    today_model = make_model(owner.id, upload_date=today)
    make_model(owner.id, upload_date=yesterday)

    today_ai_job = AIGenerationJob(id=str(uuid.uuid4()), user_id=owner.id, kind="text",
                                   prompt="today job", stage="preview", status="ready")
    db.session.add(today_ai_job)
    db.session.commit()
    AIGenerationJob.query.filter_by(id=today_ai_job.id).update({"created_at": today})
    db.session.commit()

    login(client, "dayadmin", "adminpassword")
    resp = client.get(f"/admin/analytics/day/{local_today().isoformat()}")
    assert resp.status_code == 200
    assert today_model.id.encode() in resp.data
    assert b"today job" in resp.data


def test_analytics_day_prev_next_links(client, admin_user):
    today = local_today()
    login(client, "dayadmin", "adminpassword")
    resp = client.get(f"/admin/analytics/day/{today.isoformat()}")
    prev_day = (today - timedelta(days=1)).isoformat()
    next_day = (today + timedelta(days=1)).isoformat()
    assert f"/admin/analytics/day/{prev_day}".encode() in resp.data
    # today has no "next day" link (future dates are rejected)
    assert f"/admin/analytics/day/{next_day}".encode() not in resp.data


def test_analytics_charts_render(client, admin_user):
    login(client, "dayadmin", "adminpassword")
    resp = client.get("/admin/analytics")
    assert resp.status_code == 200
    assert b"data-drill-base=" in resp.data


def test_daily_series_counts_rows_in_local_day_buckets(client, owner):
    """The bucket arithmetic used to break on SQLite and report 0 every day."""
    make_model(owner.id, upload_date=datetime.utcnow())
    make_model(owner.id, upload_date=datetime.utcnow() - timedelta(days=1))

    series = _daily_series(UserModel.upload_date, days=3)

    assert [p["v"] for p in series][-2:] == [1, 1]
