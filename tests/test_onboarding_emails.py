"""Onboarding / activation email sequence (growth F3.1)."""

import uuid
from datetime import timedelta

from app import db
from models import LifecycleEmail, ModelShareLink, User, UserModel
from services.time_utils import datetime
import services.lifecycle_emails as lifecycle


def _user(username, created_days_ago=0):
    user = User(username=username, email=f"{username}@test.com")
    user.set_password("testpassword123")
    user.created_at = datetime.utcnow() - timedelta(days=created_days_ago)
    db.session.add(user)
    db.session.commit()
    return user


def _model(user, share_count=0, visibility="unlisted"):
    model = UserModel(id=str(uuid.uuid4()), filename="m/model.glb", user_id=user.id,
                      share_count=share_count, visibility=visibility)
    db.session.add(model)
    db.session.commit()
    return model


def _capture(monkeypatch, result=True):
    sent = []
    monkeypatch.setattr(lifecycle, "send_email",
                        lambda to, subj, body: (sent.append((to, subj)) or result))
    return sent


def test_welcome_sent_to_new_signup_once(client, monkeypatch):
    sent = _capture(monkeypatch)
    user = _user("ob_new", created_days_ago=0)
    assert lifecycle.run_onboarding_sweep() == 1
    assert lifecycle.run_onboarding_sweep() == 0  # dedupe
    assert "Welcome" in sent[0][1]
    assert [r.kind for r in LifecycleEmail.query.filter_by(user_id=user.id)] == ["onboard_welcome"]


def test_share_nudge_only_when_uploaded_not_shared(client, monkeypatch):
    _capture(monkeypatch)
    uploaded = _user("ob_upl", created_days_ago=1)
    _model(uploaded)  # uploaded, not shared
    shared = _user("ob_shared", created_days_ago=1)
    _model(shared, share_count=3)  # already shared -> no nudge

    assert lifecycle.run_onboarding_sweep() == 1
    kinds = [r.kind for r in LifecycleEmail.query.filter_by(user_id=uploaded.id)]
    assert kinds == ["onboard_share"]
    assert LifecycleEmail.query.filter_by(user_id=shared.id).count() == 0


def test_share_nudge_skipped_when_share_link_exists(client, monkeypatch):
    _capture(monkeypatch)
    user = _user("ob_link", created_days_ago=1)
    model = _model(user)
    db.session.add(ModelShareLink(model_id=model.id, token_digest="d" * 64))
    db.session.commit()
    assert lifecycle.run_onboarding_sweep() == 0


def test_upload_nudge_only_when_never_uploaded(client, monkeypatch):
    _capture(monkeypatch)
    empty = _user("ob_empty", created_days_ago=2)
    has_model = _user("ob_has", created_days_ago=2)
    _model(has_model)

    assert lifecycle.run_onboarding_sweep() == 1
    assert [r.kind for r in LifecycleEmail.query.filter_by(user_id=empty.id)] == ["onboard_upload"]
    assert LifecycleEmail.query.filter_by(user_id=has_model.id).count() == 0


def test_one_lifecycle_email_per_user_per_day(client, monkeypatch):
    _capture(monkeypatch)
    user = _user("ob_cap", created_days_ago=0)
    # Simulate an email already sent today (e.g. a renewal reminder).
    db.session.add(LifecycleEmail(user_id=user.id, kind="renewal_t7", dedupe_key="x"))
    db.session.commit()
    assert lifecycle.run_onboarding_sweep() == 0  # daily cap blocks the welcome


def test_failed_delivery_is_retried(client, monkeypatch):
    _capture(monkeypatch, result=False)
    _user("ob_retry", created_days_ago=0)
    assert lifecycle.run_onboarding_sweep() == 0
    assert LifecycleEmail.query.count() == 0
    _capture(monkeypatch, result=True)
    assert lifecycle.run_onboarding_sweep() == 1
