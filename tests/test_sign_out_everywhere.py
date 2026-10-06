"""Profile "Sign out of all devices": other sessions die, this one stays."""
from flask import g


def _is_logged_in(c):
    # The client fixture keeps one app context pushed, so Flask-Login would
    # reuse the user cached on `g` by the previous request.
    g.pop("_login_user", None)
    return c.get("/profile").status_code == 200


def _login(c):
    return c.post("/login", data={"username": "testuser", "password": "testpassword"})


def test_button_rendered(client, init_database):
    _login(client)
    html = client.get("/profile").get_data(as_text=True)
    assert "/profile/sign-out-everywhere" in html


def test_other_sessions_die_current_stays(client, init_database):
    other = client.application.test_client()
    _login(client)
    _login(other)
    assert client.get("/profile").status_code == 200
    assert other.get("/profile").status_code == 200

    r = client.post("/profile/sign-out-everywhere")
    assert r.status_code == 302
    assert _is_logged_in(client)  # current browser stays
    assert not _is_logged_in(other)  # the other device is signed out


def test_remember_me_cookie_of_other_device_dies(client, init_database):
    other = client.application.test_client()
    other.post("/login", data={"username": "testuser", "password": "testpassword", "remember": "y"})
    _login(client)
    client.post("/profile/sign-out-everywhere")
    other.delete_cookie("session")  # keep only the remember-me cookie
    assert not _is_logged_in(other)


def test_requires_login(client):
    assert client.post("/profile/sign-out-everywhere").status_code == 302
