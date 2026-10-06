"""Admin is granted only via ADMIN_EMAILS, and nobody can rename into one."""
from models import User, db


def _login(client):
    client.post('/login', data=dict(username='testuser', password='testpassword'))


def test_no_admin_email_is_hardcoded(monkeypatch):
    from config import admin_emails
    monkeypatch.delenv('ADMIN_EMAILS', raising=False)
    assert admin_emails() == []
    monkeypatch.setenv('ADMIN_EMAILS', ' Boss@Example.com , ,ops@example.com')
    assert admin_emails() == ['Boss@Example.com', 'ops@example.com']


def test_profile_cannot_switch_to_admin_email(client, init_database, monkeypatch):
    monkeypatch.setenv('ADMIN_EMAILS', 'boss@example.com')
    _login(client)

    resp = client.post('/profile/update', data=dict(username='testuser', email='BOSS@example.com'))

    assert resp.status_code == 200
    assert b'This email address is reserved.' in resp.data
    assert db.session.get(User, init_database.id).email == 'test@test.com'


def test_profile_update_to_other_email_still_works(client, init_database, monkeypatch):
    monkeypatch.setenv('ADMIN_EMAILS', 'boss@example.com')
    _login(client)

    resp = client.post('/profile/update', data=dict(username='testuser', email='new@example.com'))

    assert resp.status_code == 302
    assert db.session.get(User, init_database.id).email == 'new@example.com'


def test_admin_can_keep_own_listed_email(client, init_database, monkeypatch):
    monkeypatch.setenv('ADMIN_EMAILS', 'test@test.com')
    _login(client)

    resp = client.post('/profile/update', data=dict(username='renamed', email='test@test.com'))

    assert resp.status_code == 302
    assert db.session.get(User, init_database.id).username == 'renamed'
