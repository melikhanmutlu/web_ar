"""Email preferences: opt-outs for optional mail, signed one-click unsubscribe,
List-Unsubscribe headers and the multipart HTML emails."""
from datetime import timedelta

import pytest

import services.email as email_service
from models import LifecycleEmail, User, db
from services import email_preferences as prefs
from services import lifecycle_emails as lifecycle
from services import weekly_report
from services.email import send_email
from services.time_utils import datetime


class _FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, message):
        _FakeSMTP.sent.append(message)


@pytest.fixture
def smtp(client, monkeypatch):
    _FakeSMTP.sent = []
    client.application.config.update(
        EMAIL_NOTIFICATIONS_ENABLED=True, SMTP_HOST="smtp.test", SMTP_PORT=587,
        SMTP_USERNAME="", SMTP_PASSWORD="", SMTP_USE_TLS=False,
        SMTP_FROM_EMAIL="noreply@arvision.test",
    )
    monkeypatch.setattr(email_service.smtplib, "SMTP", _FakeSMTP)
    return _FakeSMTP


def _user(name, **kw):
    user = User(username=name, email=f"{name}@test.com", **kw)
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, name):
    client.post("/login", data={"username": name, "password": "testpassword123"})


# ---- multipart / headers ---------------------------------------------------

def test_email_is_multipart_with_html_and_same_wording(smtp):
    assert send_email("a@test.com", "Hello", "Line one\nhttps://x.test/a?b=1&c=2\n\nSecond <b>para</b>")
    msg = smtp.sent[0]
    assert msg.is_multipart()
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    assert "Line one" in plain and "Second <b>para</b>" in plain
    assert 'href="https://x.test/a?b=1&amp;c=2"' in html
    assert "Second &lt;b&gt;para&lt;/b&gt;" in html  # untrusted text is escaped
    assert "List-Unsubscribe" not in msg and "nsubscribe" not in html


def test_unsubscribe_footer_and_headers(smtp):
    url = "https://site.test/unsubscribe/tok"
    assert send_email("a@test.com", "Hi", "Body", unsubscribe_url=url)
    msg = smtp.sent[0]
    assert msg["List-Unsubscribe"] == f"<{url}>"
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert url in msg.get_body(preferencelist=("plain",)).get_content()
    assert f'href="{url}"' in msg.get_body(preferencelist=("html",)).get_content()


def test_transactional_senders_have_no_unsubscribe(client, smtp):
    from services.email_verification import send_verification
    user = _user("txn")
    with client.application.test_request_context():
        send_verification(user)
    msg = smtp.sent[0]
    assert "List-Unsubscribe" not in msg
    assert "nsubscribe" not in msg.get_body(preferencelist=("plain",)).get_content()


# ---- token + route ---------------------------------------------------------

def test_unsubscribe_link_turns_category_off(client):
    user = _user("unsub1")
    token = prefs.unsubscribe_url(user, "onboarding").rsplit("/", 1)[1]
    # GET (what a link scanner does) only asks for confirmation.
    r = client.get(f"/unsubscribe/{token}")
    assert r.status_code == 200 and "Unsubscribe?" in r.get_data(as_text=True)
    db.session.refresh(user)
    assert user.email_onboarding is True
    r = client.post(f"/unsubscribe/{token}")
    assert r.status_code == 200 and "Unsubscribed" in r.get_data(as_text=True)
    db.session.refresh(user)
    assert user.email_onboarding is False
    assert user.email_renewal is True  # other categories untouched
    # RFC 8058 one-click POST works without a CSRF token or session
    client.application.config["WTF_CSRF_ENABLED"] = True
    try:
        assert client.post(f"/unsubscribe/{prefs.unsubscribe_url(user, 'renewal').rsplit('/', 1)[1]}").status_code == 200
    finally:
        client.application.config["WTF_CSRF_ENABLED"] = False
    db.session.refresh(user)
    assert user.email_renewal is False


def test_tampered_token_rejected(client):
    user = _user("unsub2")
    token = prefs.unsubscribe_url(user, "onboarding").rsplit("/", 1)[1]
    assert client.get(f"/unsubscribe/{token}x").status_code == 400
    assert client.get("/unsubscribe/garbage").status_code == 400
    # a verify-email token (different salt) is not accepted
    from services.email_verification import make_token
    assert client.get(f"/unsubscribe/{make_token(user, user.email)}").status_code == 400
    db.session.refresh(user)
    assert user.email_onboarding is True


# ---- profile toggles -------------------------------------------------------

def test_profile_toggle_roundtrip(client):
    user = _user("prof1")
    _login(client, "prof1")
    html = client.get("/profile").get_data(as_text=True)
    assert "Email preferences" in html and "Onboarding tips" in html
    assert "Weekly growth report" not in html  # admins only
    client.post("/profile/email-preferences", data={"email_renewal": "on"})
    db.session.refresh(user)
    assert (user.email_onboarding, user.email_renewal) == (False, True)
    assert user.email_weekly_report is True  # not offered to non-admins: untouched


# ---- senders respect the flags --------------------------------------------

def _capture(monkeypatch, module):
    sent = []
    monkeypatch.setattr(module, "send_email", lambda to, subj, body, **kw: sent.append((to, kw)) or True)
    return sent


def test_renewal_reminder_skipped_when_opted_out_and_carries_link(client, monkeypatch):
    sent = _capture(monkeypatch, lifecycle)
    out = _user("ren_out", plan="pro", email_renewal=False)
    out.plan_expires_at = datetime.utcnow() + timedelta(days=5)
    inn = _user("ren_in", plan="pro")
    inn.plan_expires_at = datetime.utcnow() + timedelta(days=5)
    db.session.commit()
    assert lifecycle.run_renewal_sweep() == 1
    assert [to for to, _ in sent] == ["ren_in@test.com"]
    assert "/unsubscribe/" in sent[0][1]["unsubscribe_url"]
    assert LifecycleEmail.query.filter_by(user_id=out.id).count() == 0


def test_onboarding_skipped_when_opted_out(client, monkeypatch):
    sent = _capture(monkeypatch, lifecycle)
    _user("ob_out", email_onboarding=False)
    _user("ob_in")
    assert lifecycle.run_onboarding_sweep() == 1
    assert [to for to, _ in sent] == ["ob_in@test.com"]


def test_renewal_opt_out_does_not_block_onboarding(client, monkeypatch):
    sent = _capture(monkeypatch, lifecycle)
    _user("ob_ren_out", email_renewal=False)
    assert lifecycle.run_onboarding_sweep() == 1


def test_weekly_report_skips_opted_out_admin(client, monkeypatch):
    sent = _capture(monkeypatch, weekly_report)
    _user("wr_in", is_admin=True)
    _user("wr_out", is_admin=True, email_weekly_report=False)
    monday = datetime.utcnow() - timedelta(days=datetime.utcnow().weekday())
    assert weekly_report.send_weekly_report(now=monday) is True
    assert [to for to, _ in sent] == ["wr_in@test.com"]
    assert "/unsubscribe/" in sent[0][1]["unsubscribe_url"]


def test_plan_expiry_notice_respects_renewal_flag(client, monkeypatch):
    import worker
    sent = []
    monkeypatch.setattr(worker, "send_email", lambda to, subj, body, **kw: sent.append(to) or True)
    for name, flag in (("exp_in", True), ("exp_out", False)):
        user = _user(name, plan="pro", email_renewal=flag)
        user.plan_expires_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()
    worker.expire_stale_plans()
    assert sent == ["exp_in@test.com"]
