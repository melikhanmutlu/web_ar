"""Faz 4 (ADM-18, ADM-20): lifecycle email targeting/copy, and credit top-ups
going through the same e-invoice path as plan payments."""

from datetime import timedelta
from decimal import Decimal
from unittest import mock

from models import Payment, User, db
from services.time_utils import datetime
import services.lifecycle_emails as lifecycle


def _user(username, plan="pro", expires_in_days=None, active=True):
    user = User(username=username, email=f"{username}@test.com", plan=plan, is_active_flag=active)
    user.set_password("testpassword123")
    if expires_in_days is not None:
        user.plan_expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    db.session.add(user)
    db.session.commit()
    return user


def _capture(monkeypatch):
    sent = []
    monkeypatch.setattr(lifecycle, "send_email", lambda to, subject, body: sent.append((to, subject, body)) or True)
    return sent


def test_deactivated_users_get_no_lifecycle_email(client, monkeypatch):
    sent = _capture(monkeypatch)
    _user("lc4_off", expires_in_days=5, active=False)
    _user("lc4_new_off", plan="free", active=False)  # onboarding welcome cohort
    assert lifecycle.run_renewal_sweep() == 0
    assert lifecycle.run_onboarding_sweep() == 0
    assert sent == []


def test_trial_user_gets_trial_copy_not_renew_copy(client, monkeypatch):
    sent = _capture(monkeypatch)
    user = _user("lc4_trial", plan="business", expires_in_days=5)
    user.business_trial_used_at = datetime.utcnow() - timedelta(days=9)
    db.session.commit()
    assert lifecycle.run_renewal_sweep() == 1
    _, subject, body = sent[0]
    assert "trial ends" in subject and "Business" in subject
    assert "Choose a plan" in body and "Renew" not in body


def test_days_left_rounds_up(client, monkeypatch):
    sent = _capture(monkeypatch)
    _user("lc4_ceil", expires_in_days=0).plan_expires_at = datetime.utcnow() + timedelta(days=2, hours=2)
    db.session.commit()
    lifecycle.run_renewal_sweep()
    assert "in 3 days" in sent[0][1]


def test_plan_expiry_email_uses_display_name(client, monkeypatch):
    import worker
    sent = []
    monkeypatch.setattr(worker, "send_email", lambda to, subject, body: sent.append(body) or True)
    _user("lc4_exp", plan="business", expires_in_days=-1)
    worker.expire_stale_plans()
    assert sent and "Your ARVision Business plan has expired" in sent[0]


def test_topup_payment_is_invoiced(client):
    from blueprints.billing import _apply_successful_payment
    user = _user("inv4_user", plan="free")
    payment = Payment(user_id=user.id, plan="credits", kind="topup", credits=10,
                      amount=Decimal("9"), currency="USD", status="pending")
    db.session.add(payment)
    db.session.commit()
    with mock.patch("services.invoicing.issue_invoice") as issue:
        _apply_successful_payment(payment)
    assert issue.call_count == 1
    assert issue.call_args[0][0].id == payment.id
