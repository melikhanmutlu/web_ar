"""Faz 4 (ADM-10, ADM-13): one MRR definition everywhere, and one plan
summary shared by the profile and billing pages."""

from datetime import timedelta
from decimal import Decimal

from models import Payment, User, db
from services.growth_metrics import collect_growth_metrics, compute_mrr, _active_paid_users, format_mrr
from services.plans import plan_summary
from services.time_utils import datetime


def _user(name, plan="free", expires_in_days=None, is_admin=False, verified=True):
    u = User(username=name, email=f"{name}@test.com", plan=plan, is_admin=is_admin)
    u.set_password("testpassword")
    if expires_in_days is not None:
        u.plan_expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
    if verified:
        u.email_verified_at = datetime.utcnow()
    db.session.add(u)
    db.session.commit()
    return u


def _pay(user, plan, days_left=20):
    db.session.add(Payment(user_id=user.id, plan=plan, kind="plan", amount=Decimal("19"),
                           status="paid",
                           period_end=(datetime.utcnow() + timedelta(days=days_left)).date()))
    db.session.commit()


def _login(client, name):
    client.post("/login", data={"username": name, "password": "testpassword"})


def test_billing_and_growth_report_same_mrr(client):
    payer = _user("mrr_payer", plan="pro", expires_in_days=20)
    _pay(payer, "pro")
    _user("mrr_trial", plan="business", expires_in_days=5)      # trial/comp: no payment
    # Paid plan row exists but for a different plan than the one now active.
    switched = _user("mrr_switched", plan="business", expires_in_days=5)
    _pay(switched, "pro")
    admin = _user("mrr_admin", plan="free", is_admin=True)

    growth = collect_growth_metrics()["mrr"]
    assert growth == {"USD": 19}
    assert compute_mrr(_active_paid_users(datetime.utcnow())) == growth

    _login(client, "mrr_admin")
    html = client.get("/admin/billing").get_data(as_text=True)
    assert "19.00 USD" in html
    assert format_mrr(growth) == "19.00 USD"
    assert admin.is_admin


def test_weekly_report_mrr_includes_currency(client):
    from services.weekly_report import _build_body
    payer = _user("mrr_wr", plan="pro", expires_in_days=20)
    _pay(payer, "pro")
    body = _build_body(collect_growth_metrics(), datetime.utcnow())
    assert "MRR: 19.00 USD" in body


def test_plan_summary_expired_plan_is_free_with_expired_on(client):
    u = _user("ps_expired", plan="business", expires_in_days=-3)
    info = plan_summary(u)
    assert info["slug"] == "free" and info["expired"] is True
    assert info["expires_at"] is None and info["expired_on"] is not None


def test_plan_summary_trial_flag(client):
    u = _user("ps_trial", plan="business", expires_in_days=14)
    u.business_trial_used_at = datetime.utcnow()
    db.session.commit()
    assert plan_summary(u)["is_trial"] is True
    u.plan_expires_at = datetime.utcnow() + timedelta(days=30)
    assert plan_summary(u)["is_trial"] is False


def test_profile_and_billing_agree_for_lapsed_plan(client):
    _user("ps_lapsed", plan="business", expires_in_days=-3)
    _login(client, "ps_lapsed")
    profile = client.get("/profile").get_data(as_text=True)
    billing = client.get("/billing").get_data(as_text=True)
    assert "Your paid plan expired on" in profile
    assert "<h2>Free</h2>" in profile
    assert "EXPIRED" in billing and "Renew before" not in billing


def test_trial_button_disabled_for_unverified_user(client):
    _user("ps_unverified", verified=False)
    _login(client, "ps_unverified")
    html = client.get("/billing").get_data(as_text=True)
    assert "Verify your email first" in html
    assert 'disabled aria-disabled="true"' in html
    _user("ps_verified")
    client.post("/logout")
    _login(client, "ps_verified")
    html = client.get("/billing").get_data(as_text=True)
    assert "Verify your email first" not in html
