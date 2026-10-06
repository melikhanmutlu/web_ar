"""Referral program (growth F3.2): code generation, double-sided credit
grants, self-referral / unknown-code guards, and the monthly reward cap."""

from datetime import timedelta

from app import db
from models import User
from services import referrals
from services.time_utils import datetime


def _user(username, credits=0):
    user = User(username=username, email=f"{username}@test.com", ai_credit_balance=credits,
                email_verified_at=datetime.utcnow())
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


def test_monthly_reward_cap_limits_both_sides(client, monkeypatch):
    monkeypatch.setattr(referrals, "MONTHLY_REWARD_CAP", 2)
    referrer = _user("ref_cap", credits=0)
    code = referrals.get_or_create_code(referrer)

    # First two referrals reward both sides; past the cap (the third) neither
    # side is rewarded, so one referrer can't mint credits per throwaway account.
    for i in range(3):
        invitee = _user(f"ref_cap_i{i}", credits=0)
        referrals.apply_referral(invitee, code)
        db.session.commit()
        expected = referrals.INVITEE_CREDITS if i < 2 else 0
        assert db.session.get(User, invitee.id).ai_credit_balance == expected

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
    # Rewards wait for the new user's email verification.
    assert newbie.ai_credit_balance == 0
    assert db.session.get(User, referrer.id).ai_credit_balance == 0

    from services.email_verification import make_token
    client.get(f"/verify-email/{make_token(newbie, newbie.email)}")
    assert db.session.get(User, newbie.id).ai_credit_balance == referrals.INVITEE_CREDITS
    assert db.session.get(User, referrer.id).ai_credit_balance == referrals.REFERRER_CREDITS


def test_referral_rewards_skipped_until_verified_and_for_unverified_referrer(client):
    unverified_referrer = _user("ref_unv_r", credits=0)
    unverified_referrer.email_verified_at = None
    db.session.commit()
    code = referrals.get_or_create_code(unverified_referrer)
    invitee = _user("ref_unv_i", credits=0)
    invitee.email_verified_at = None
    db.session.commit()

    referrals.apply_referral(invitee, code)
    db.session.commit()
    assert db.session.get(User, invitee.id).ai_credit_balance == 0

    from services.email_verification import mark_verified
    mark_verified(invitee)
    db.session.commit()
    # Invitee is rewarded; the unverified referrer is skipped (no error).
    assert db.session.get(User, invitee.id).ai_credit_balance == referrals.INVITEE_CREDITS
    assert db.session.get(User, unverified_referrer.id).ai_credit_balance == 0


def test_alias_of_referrers_own_mailbox_is_not_a_referral(client):
    referrer = User(username="ref_alias_r", email="john.doe@gmail.com",
                    email_verified_at=datetime.utcnow())
    referrer.set_password("testpassword123")
    db.session.add(referrer)
    db.session.commit()
    code = referrals.get_or_create_code(referrer)
    sock = User(username="ref_alias_s", email="johndoe+farm1@googlemail.com",
                email_verified_at=datetime.utcnow())
    sock.set_password("testpassword123")
    db.session.add(sock)
    db.session.commit()
    assert referrals.apply_referral(sock, code) is None
    assert db.session.get(User, sock.id).referred_by_id is None
    assert db.session.get(User, sock.id).ai_credit_balance == 0
