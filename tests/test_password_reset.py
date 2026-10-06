"""Self-service password reset (UIP-02)."""
import re
from unittest.mock import patch

from flask import g

from models import User, db
from services import password_reset
from services.email_verification import make_token as make_verify_token


def test_login_links_to_forgot_password(client):
    html = client.get('/login').get_data(as_text=True)
    assert 'href="/forgot-password"' in html
    assert client.get('/forgot-password').status_code == 200


def test_forgot_password_same_response_for_known_and_unknown(client, init_database):
    with patch('services.password_reset.send_email', return_value=True) as sent:
        known = client.post('/forgot-password', data={'email': 'test@test.com'})
        unknown = client.post('/forgot-password', data={'email': 'nobody@test.com'})
    assert known.status_code == unknown.status_code == 200
    pick = lambda r: re.search(r'id="forgot-notice"[^>]*>(.*?)</p>', r.get_data(as_text=True), re.S).group(1)
    assert pick(known) == pick(unknown)
    assert 'If an account exists' in pick(known)
    assert sent.call_count == 1
    assert sent.call_args[0][0] == 'test@test.com'
    assert '/reset-password/' in sent.call_args[0][2]


def test_forgot_password_logs_link_when_smtp_unconfigured(client, init_database):
    with patch.object(password_reset, 'logger') as log:
        client.post('/forgot-password', data={'email': 'TEST@test.com'})
    assert log.info.called
    assert any('/reset-password/' in str(c.args[-1]) for c in log.info.call_args_list)


def test_reset_flow_sets_password_logs_in_and_token_is_single_use(client, init_database):
    token = password_reset.make_token(init_database)
    assert client.get(f'/reset-password/{token}').status_code == 200
    r = client.post(f'/reset-password/{token}', data={'password': 'brandnewpass1', 'confirm_password': 'brandnewpass1'})
    assert r.status_code == 302
    assert client.get('/profile').status_code == 200  # logged in
    assert User.query.filter_by(username='testuser').first().check_password('brandnewpass1')
    # replay is rejected
    assert client.get(f'/reset-password/{token}').status_code == 400
    r2 = client.post(f'/reset-password/{token}', data={'password': 'otherpass123', 'confirm_password': 'otherpass123'})
    assert r2.status_code == 400
    assert User.query.filter_by(username='testuser').first().check_password('brandnewpass1')


def test_reset_invalidates_other_sessions(client, init_database):
    other = client.application.test_client()
    other.post('/login', data={'username': 'testuser', 'password': 'testpassword'})
    g.pop('_login_user', None)  # the client fixture shares one app context
    assert other.get('/profile').status_code == 200
    token = password_reset.make_token(init_database)
    client.post(f'/reset-password/{token}', data={'password': 'brandnewpass1', 'confirm_password': 'brandnewpass1'})
    g.pop('_login_user', None)
    assert other.get('/profile').status_code == 302  # bounced to login


def test_password_change_elsewhere_kills_link(client, init_database):
    token = password_reset.make_token(init_database)
    init_database.set_password('changedelsewhere1')
    db.session.commit()
    assert client.get(f'/reset-password/{token}').status_code == 400


def test_expired_token_rejected(client, init_database):
    token = password_reset.make_token(init_database)
    with patch.object(password_reset, 'MAX_AGE_SECONDS', -1):
        r = client.get(f'/reset-password/{token}')
    assert r.status_code == 400 and 'expired' in r.get_data(as_text=True)


def test_email_verification_token_is_not_a_reset_token(client, init_database):
    bad = make_verify_token(init_database, init_database.email)
    assert client.get(f'/reset-password/{bad}').status_code == 400
    assert client.get('/reset-password/garbage').status_code == 400


def test_reset_mismatched_confirm_shows_aria_error(client, init_database):
    token = password_reset.make_token(init_database)
    r = client.post(f'/reset-password/{token}', data={'password': 'brandnewpass1', 'confirm_password': 'different123'})
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert 'aria-describedby="confirm_password-error"' in html
    assert not User.query.filter_by(username='testuser').first().check_password('brandnewpass1')


def test_inactive_user_gets_no_email(client, init_database):
    init_database.is_active_flag = False
    db.session.commit()
    with patch('services.password_reset.send_email') as sent:
        client.post('/forgot-password', data={'email': 'test@test.com'})
    assert not sent.called


def test_forgot_password_post_is_rate_limited(client):
    from app import limiter
    limiter.enabled = True
    try:
        limiter.reset()
        codes = [client.post('/forgot-password', data={'email': f'a{i}@x.com'}).status_code for i in range(7)]
    finally:
        limiter.enabled = False
    assert 429 in codes and codes[:5] == [200] * 5
