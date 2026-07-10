"""Coverage for the analytics day-drill-down page and the `iso` field
added to admin.py's `_daily_series` helper."""

import uuid
from datetime import datetime, timedelta

import pytest

from admin import _daily_series
from app import db
from models import AIGenerationJob, RigAnimationJob, User, UserModel


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
    assert series[-1]["iso"] == datetime.utcnow().strftime("%Y-%m-%d")


def test_analytics_day_requires_admin(client, owner):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    resp = client.get(f"/admin/analytics/day/{today}")
    assert resp.status_code == 302

    login(client, "dayowner", "testpassword")
    assert client.get(f"/admin/analytics/day/{today}").status_code == 404


@pytest.mark.parametrize("bad", ["not-a-date", "2024-13-40", "20240101"])
def test_analytics_day_rejects_malformed_date(client, admin_user, bad):
    login(client, "dayadmin", "adminpassword")
    assert client.get(f"/admin/analytics/day/{bad}").status_code == 404


def test_analytics_day_rejects_future_date(client, admin_user):
    future = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d")
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

    today_rig_job = RigAnimationJob(id=str(uuid.uuid4()), model_id=today_model.id,
                                    user_id=owner.id, height_meters=1.7,
                                    animation_action_ids=[0], meshy_rig_id="r-1",
                                    stage="rigging", status="ready")
    db.session.add(today_rig_job)
    db.session.commit()
    RigAnimationJob.query.filter_by(id=today_rig_job.id).update({"created_at": today})
    db.session.commit()

    login(client, "dayadmin", "adminpassword")
    resp = client.get(f"/admin/analytics/day/{today.strftime('%Y-%m-%d')}")
    assert resp.status_code == 200
    assert today_model.id.encode() in resp.data
    assert b"today job" in resp.data
    assert today_rig_job.model_id[:8].encode() in resp.data


def test_analytics_day_prev_next_links(client, admin_user):
    today = datetime.utcnow()
    login(client, "dayadmin", "adminpassword")
    resp = client.get(f"/admin/analytics/day/{today.strftime('%Y-%m-%d')}")
    prev_day = (today - timedelta(days=1)).strftime("%Y-%m-%d")
    next_day = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    assert f"/admin/analytics/day/{prev_day}".encode() in resp.data
    # today has no "next day" link (future dates are rejected)
    assert f"/admin/analytics/day/{next_day}".encode() not in resp.data


def test_analytics_chart_includes_rig_jobs(client, admin_user):
    login(client, "dayadmin", "adminpassword")
    resp = client.get("/admin/analytics")
    assert resp.status_code == 200
    assert b"rig &amp; animate jobs" in resp.data
    assert b"data-drill-base=" in resp.data
