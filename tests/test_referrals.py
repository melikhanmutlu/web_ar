"""Referral program (growth F3.2): code generation, double-sided credit
grants, self-referral / unknown-code guards, and the monthly reward cap."""

from datetime import timedelta

from app import db
from models import User
from services import referrals
from services.time_utils import datetime


def _user(username, credits=0):
    user = User(username=username, email=f"{username}@test.com", ai_credit_balance=credits)
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def test_code_is_generated_once_and_stable(client):
    user = _user("ref_code")
    code1 = referrals.get_or_create_code(user)
    code2 = referrals.get_or_create_code(user)
    assert code1 and code1 == code2
    assert referrals.referral_link(user).endswith(f"ref={code1}")


def test_apply_referral_credits_both_sides(client):
    referrer = _user("ref_r", credits=0)
    code = referrals.get_or_create_code(referrer)
    invitee = _user("ref_i", credits=0)

    result = referrals.apply_referral(invitee, code)
    db.session.commit()
    assert result.id == referrer.id
    assert db.session.get(User, invitee.id).referred_by_id == referrer.id
    assert db.session.get(User, invitee.id).ai_credit_balance == referrals.INVITEE_CREDITS
    assert db.session.get(User, referrer.id).ai_credit_balance == referrals.REFERRER_CREDITS


def test_unknown_code_is_noop(client):
    invitee = _user("ref_unknown", credits=0)
    assert referrals.apply_referral(invitee, "doesnotexist") is None
    assert db.session.get(User, invitee.id).referred_by_id is None
    assert db.session.get(User, invitee.id).ai_credit_balance == 0


def test_self_referral_is_blocked(client):
    user = _user("ref_self", credits=0)
    code = referrals.get_or_create_code(user)
    assert referrals.apply_referral(user, code) is None
    assert db.session.get(User, user.id).ai_credit_balance == 0


def test_monthly_reward_cap_limits_referrer_only(client, monkeypatch):
    monkeypatch.setattr(referrals, "MONTHLY_REWARD_CAP", 2)
    referrer = _user("ref_cap", credits=0)
    code = referrals.get_or_create_code(referrer)

    # First two referrals reward the referrer; the third does not (cap=2).
    for i in range(3):
        invitee = _user(f"ref_cap_i{i}", credits=0)
        referrals.apply_referral(invitee, code)
        db.session.commit()
        # The invitee always gets their bonus regardless of the cap.
        assert db.session.get(User, invitee.id).ai_credit_balance == referrals.INVITEE_CREDITS

    assert db.session.get(User, referrer.id).ai_credit_balance == 2 * referrals.REFERRER_CREDITS


def test_registration_with_ref_links_and_credits(client):
    referrer = _user("ref_reg", credits=0)
    code = referrals.get_or_create_code(referrer)

    resp = client.post(f"/register?ref={code}", data={
        "username": "newbie", "email": "newbie@test.com",
        "password": "password123", "confirm_password": "password123",
    }, follow_redirects=True)
    assert resp.status_code == 200
    newbie = User.query.filter_by(username="newbie").first()
    assert newbie is not None
    assert newbie.referred_by_id == referrer.id
    assert newbie.ai_credit_balance == referrals.INVITEE_CREDITS
    assert db.session.get(User, referrer.id).ai_credit_balance == referrals.REFERRER_CREDITS
