"""Auth UX flows: visible inline errors, form re-render, next handling,
registration auto-login (UIP-01, UIP-13, UIP-14, UIP-19, UIP-20)."""
import re

from models import User


def _css():
    with open('static/css/arvision.css', encoding='utf-8') as f:
        return f.read()


def test_flash_sits_above_aurora_background():
    css = _css()
    m = re.search(r'\.av-flash\s*\{([^}]*)\}', css)
    assert m and 'position: relative' in m.group(1) and 'z-index: 10' in m.group(1)
    aurora = re.search(r'\.aurora-bg\s*\{[^}]*z-index:\s*(\d+)', css, re.S)
    assert aurora and int(aurora.group(1)) < 10


def test_failed_login_rerenders_form_with_inline_alert(client, init_database):
    r = client.post('/login?next=/pricing', data=dict(username='testuser', password='nope'))
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'role="alert"' in html and 'id="login-error"' in html
    assert 'Invalid username/email or password' in html
    assert 'value="testuser"' in html  # username kept
    assert 'action="/login?next=/pricing"' in html  # next kept
    assert 'aria-invalid="true"' in html and 'aria-describedby="login-error"' in html


def test_failed_login_message_does_not_reveal_account_existence(client, init_database):
    a = client.post('/login', data=dict(username='testuser', password='nope')).get_data(as_text=True)
    b = client.post('/login', data=dict(username='ghost', password='nope')).get_data(as_text=True)
    pick = lambda h: re.search(r'id="login-error"[^>]*>(.*?)</p>', h, re.S).group(1)
    assert pick(a) == pick(b)


def test_flash_markup_has_no_duplicate_ids_and_error_not_autodismissed(client, init_database):
    with client.session_transaction() as s:
        s['_flashes'] = [('error', 'one'), ('success', 'two')]
    html = client.get('/login').get_data(as_text=True)
    assert 'id="flash-message"' not in html
    assert html.count('<button data-flash-close') == 2
    assert 'data-flash-category="error"' in html
    # the auto-dismiss script lives in site.js (inline scripts are blocked by the CSP)
    site_js = client.get('/static/js/site.js').get_data(as_text=True)
    assert ':not([data-flash-category="error"])' in site_js


def test_register_field_errors_are_aria_linked(client, init_database):
    r = client.post('/register', data=dict(username='ab', email='x@y.com', password='longenough1',
                                           confirm_password='longenough1'))
    html = r.get_data(as_text=True)
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="username-error"' in html
    assert 'id="username-error"' in html


def test_register_logs_in_and_honours_safe_next(client):
    r = client.post('/register?next=/billing', data=dict(
        username='newbie', email='newbie@example.com', password='password123',
        confirm_password='password123'))
    assert r.status_code == 302 and r.headers['Location'].endswith('/billing')
    assert client.get('/profile').status_code == 200  # logged in


def test_register_rejects_unsafe_next(client):
    r = client.post('/register?next=//evil.com', data=dict(
        username='newbie2', email='newbie2@example.com', password='password123',
        confirm_password='password123'))
    assert r.status_code == 302 and 'evil.com' not in r.headers['Location']


def test_logged_in_user_visiting_login_goes_to_safe_next(client, init_database):
    client.post('/login', data=dict(username='testuser', password='testpassword'))
    r = client.get('/login?next=/billing')
    assert r.status_code == 302 and r.headers['Location'].endswith('/billing')
    r = client.get('/login?next=https://evil.com')
    assert 'evil.com' not in r.headers['Location']


def test_pricing_cta_for_anonymous_carries_next(client):
    html = client.get('/pricing').get_data(as_text=True)
    assert re.search(r'href="/login\?next=(/billing|%2Fbilling)[^"]*"', html)
