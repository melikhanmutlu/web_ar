"""A password change (self-service or admin reset) invalidates every existing
session and remember-me cookie except the browser that made the change."""

from flask import g

from app import app
from models import User, db


def _logged_in_client(remember=True):
    c = app.test_client()
    c.post('/login', data=dict(username='testuser', password='testpassword',
                               remember='y' if remember else ''))
    return c


def _is_logged_in(c):
    # The client fixture keeps one app context pushed, so every request shares
    # `g` and Flask-Login would reuse the user it cached on the last one.
    g.pop('_login_user', None)
    return c.get('/profile').status_code == 200


def _replay(cookie_name, value):
    c = app.test_client()
    c.set_cookie(cookie_name, value)
    return c


def test_stolen_cookies_die_when_password_changes(client, init_database):
    victim = _logged_in_client()
    stolen_remember = victim.get_cookie('remember_token').value
    stolen_session = victim.get_cookie('session').value
    assert _is_logged_in(_replay('remember_token', stolen_remember))

    resp = victim.post('/profile/password', data=dict(
        current_password='testpassword', new_password='NewPassw0rd!x',
        confirm_password='NewPassw0rd!x'))

    assert resp.status_code == 302
    assert _is_logged_in(victim)  # the browser that changed it stays signed in
    assert not _is_logged_in(_replay('remember_token', stolen_remember))
    assert not _is_logged_in(_replay('session', stolen_session))


def test_admin_password_reset_signs_user_out(client, init_database):
    victim = _logged_in_client(remember=False)
    assert _is_logged_in(victim)

    user = db.session.get(User, init_database.id)
    user.set_password('AdminChosen!123')
    db.session.commit()

    assert not _is_logged_in(victim)


def test_pre_versioning_cookie_still_loads_until_password_changes(client, init_database):
    from app import load_user
    user = db.session.get(User, init_database.id)
    user.session_version = 0  # what the migration gives existing accounts
    db.session.commit()
    assert load_user(str(init_database.id)) is not None
    user.set_password('another-pass-123')
    db.session.commit()
    assert load_user(str(init_database.id)) is None
    assert load_user('not-a-number') is None
