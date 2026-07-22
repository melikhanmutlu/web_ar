"""Self-serve 14-day Business trial (growth F2.4)."""

from datetime import timedelta

from app import db
from models import User
from services.time_utils import datetime


def _user(username, plan="free", is_admin=False):
    user = User(username=username, email=f"{username}@test.com", plan=plan, is_admin=is_admin)
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, username):
    client.post("/login", data={"username": username, "password": "testpassword123"})


def test_free_user_can_start_trial_once(client):
    user = _user("trial_ok")
    _login(client, "trial_ok")

    client.post("/billing/trial")
    refreshed = db.session.get(User, user.id)
    assert refreshed.plan == "business"
    assert refreshed.business_trial_used_at is not None
    assert refreshed.plan_expires_at > datetime.utcnow() + timedelta(days=13)


def test_trial_cannot_be_taken_twice(client):
    user = _user("trial_twice")
    user.business_trial_used_at = datetime.utcnow() - timedelta(days=30)
    user.plan = "free"
    db.session.commit()
    _login(client, "trial_twice")

    client.post("/billing/trial")
    assert db.session.get(User, user.id).plan == "free"  # not re-granted


def test_paid_user_cannot_start_trial(client):
    user = _user("trial_paid", plan="pro")
    user.plan_expires_at = datetime.utcnow() + timedelta(days=20)
    db.session.commit()
    _login(client, "trial_paid")

    client.post("/billing/trial")
    refreshed = db.session.get(User, user.id)
    assert refreshed.business_trial_used_at is None  # untouched


def test_expired_trial_downgrades_via_worker_sweep(client):
    import worker
    user = _user("trial_expired", plan="business")
    user.business_trial_used_at = datetime.utcnow() - timedelta(days=15)
    user.plan_expires_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()

    worker.expire_stale_plans()
    refreshed = db.session.get(User, user.id)
    assert refreshed.plan == "free"
    # Trial stays marked used, so it can't be taken again after it lapses.
    assert refreshed.business_trial_used_at is not None


def test_billing_page_offers_trial_only_to_eligible_free_user(client):
    _user("trial_page")
    _login(client, "trial_page")
    assert "Start your" in client.get("/billing").get_data(as_text=True)

    client.post("/billing/trial")  # take it
    # The CTA button is gone (the success flash may still mention "trial").
    assert "Start your" not in client.get("/billing").get_data(as_text=True)
