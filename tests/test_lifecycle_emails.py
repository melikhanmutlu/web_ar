"""Renewal-reminder / win-back sweep (services/lifecycle_emails.py).

send_email is monkeypatched at the module under test, so these cover window
selection, dedupe, re-arming after a renewal, and retry-on-failed-delivery
without any SMTP configuration.
"""

from datetime import timedelta
from decimal import Decimal

from app import db
from models import LifecycleEmail, Payment, User
from services.time_utils import datetime
import services.lifecycle_emails as lifecycle


def _user(username, plan="pro", expires_in_days=None):
    user = User(username=username, email=f"{username}@test.com", plan=plan)
    user.set_password("testpassword123")
    if expires_in_days is not None:
        user.plan_expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    db.session.add(user)
    db.session.commit()
    return user


def _capture_sends(monkeypatch, result=True):
    sent = []
    def fake_send(to_email, subject, body):
        sent.append((to_email, subject, body))
        return result
    monkeypatch.setattr(lifecycle, "send_email", fake_send)
    return sent


def test_t7_reminder_sent_exactly_once(client, monkeypatch):
    sent = _capture_sends(monkeypatch)
    user = _user("lc_t7", expires_in_days=5)

    assert lifecycle.run_renewal_sweep() == 1
    assert lifecycle.run_renewal_sweep() == 0  # dedupe: second sweep is free

    assert len(sent) == 1
    assert sent[0][0] == user.email
    assert "expires in" in sent[0][1]
    rows = LifecycleEmail.query.filter_by(user_id=user.id).all()
    assert [r.kind for r in rows] == ["renewal_t7"]


def test_t1_window_is_disjoint_from_t7(client, monkeypatch):
    sent = _capture_sends(monkeypatch)
    user = _user("lc_t1", expires_in_days=None)
    user.plan_expires_at = datetime.utcnow() + timedelta(hours=12)
    db.session.commit()

    assert lifecycle.run_renewal_sweep() == 1
    kinds = [r.kind for r in LifecycleEmail.query.filter_by(user_id=user.id)]
    assert kinds == ["renewal_t1"]
    assert "tomorrow" in sent[0][1]


def test_free_expired_and_far_future_users_are_skipped(client, monkeypatch):
    _capture_sends(monkeypatch)
    _user("lc_free", plan="free", expires_in_days=3)      # free plan
    _user("lc_far", plan="pro", expires_in_days=30)        # outside window
    _user("lc_none", plan="pro", expires_in_days=None)     # admin grant, no expiry
    past = _user("lc_past", plan="pro")
    past.plan_expires_at = datetime.utcnow() - timedelta(days=1)  # already lapsed
    db.session.commit()

    assert lifecycle.run_renewal_sweep() == 0
    assert LifecycleEmail.query.count() == 0


def test_failed_delivery_is_retried_next_sweep(client, monkeypatch):
    _capture_sends(monkeypatch, result=False)  # SMTP down / unconfigured
    user = _user("lc_retry", expires_in_days=5)

    assert lifecycle.run_renewal_sweep() == 0
    assert LifecycleEmail.query.count() == 0  # nothing recorded -> retryable

    _capture_sends(monkeypatch, result=True)
    assert lifecycle.run_renewal_sweep() == 1
    assert LifecycleEmail.query.filter_by(user_id=user.id).count() == 1


def test_renewal_rearms_the_same_reminder_kind(client, monkeypatch):
    sent = _capture_sends(monkeypatch)
    user = _user("lc_rearm", expires_in_days=5)
    assert lifecycle.run_renewal_sweep() == 1

    # A renewal pushes plan_expires_at forward -> new dedupe key. Land it back
    # inside the T-7 window to prove the same kind fires again next period.
    user.plan_expires_at = datetime.utcnow() + timedelta(days=6)
    db.session.commit()
    assert lifecycle.run_renewal_sweep() == 1

    assert len(sent) == 2
    assert LifecycleEmail.query.filter_by(user_id=user.id, kind="renewal_t7").count() == 2


def _paid_payment(user, plan="pro", period_end_days_ago=5):
    payment = Payment(
        user_id=user.id, plan=plan, amount=Decimal("19.00"), status="paid",
        period_end=(datetime.utcnow() - timedelta(days=period_end_days_ago)).date(),
    )
    db.session.add(payment)
    db.session.commit()
    return payment


def test_winback_emails_lapsed_payer_once(client, monkeypatch):
    sent = _capture_sends(monkeypatch)
    user = _user("lc_wb", plan="free")  # already swept back to free
    _paid_payment(user, period_end_days_ago=5)

    assert lifecycle.run_renewal_sweep() == 1
    assert lifecycle.run_renewal_sweep() == 0
    assert len(sent) == 1
    assert "one click away" in sent[0][1]
    kinds = [r.kind for r in LifecycleEmail.query.filter_by(user_id=user.id)]
    assert kinds == ["winback_t3"]


def test_winback_skips_renewed_and_too_recent_or_ancient(client, monkeypatch):
    _capture_sends(monkeypatch)
    renewed = _user("lc_wb_renewed", plan="pro", expires_in_days=25)
    _paid_payment(renewed, period_end_days_ago=5)  # old period, but they renewed

    fresh = _user("lc_wb_fresh", plan="free")
    _paid_payment(fresh, period_end_days_ago=1)  # lapsed < WINBACK_AFTER_DAYS ago

    ancient = _user("lc_wb_ancient", plan="free")
    _paid_payment(ancient, period_end_days_ago=90)  # beyond WINBACK_MAX_AGE_DAYS

    assert lifecycle.run_renewal_sweep() == 0
    assert LifecycleEmail.query.count() == 0
