"""Faz 4 (ADM-29 + settings): free AI trial count and sales booking URL are
editable from the admin settings form."""

from models import User, db
from site_settings import get_setting, setting_int


def _admin(client):
    u = User(username="faz4adm", email="faz4adm@test.com", is_admin=True)
    u.set_password("testpassword")
    db.session.add(u)
    db.session.commit()
    client.post("/login", data={"username": "faz4adm", "password": "testpassword"})


def test_free_ai_trial_count_editable_and_zero_allowed(client):
    _admin(client)
    html = client.get("/admin/settings?tab=ai").get_data(as_text=True)
    assert 'name="free_ai_trial_count"' in html
    assert "but not the Free trial" in html
    r = client.post("/admin/settings?tab=ai", data={"ai_monthly_limit": "0", "free_ai_trial_count": "0"})
    assert r.status_code == 302
    assert setting_int("free_ai_trial_count", 3) == 0
    client.post("/admin/settings?tab=ai", data={"ai_monthly_limit": "0", "free_ai_trial_count": "-1"})
    assert setting_int("free_ai_trial_count", 3) == 0  # rejected, unchanged


def test_calcom_url_must_be_https(client):
    _admin(client)
    client.post("/admin/settings?tab=general", data={"calcom_url": "javascript:alert(1)"})
    assert not get_setting("calcom_url")
    client.post("/admin/settings?tab=general", data={"calcom_url": "https://cal.com/acme"})
    assert get_setting("calcom_url") == "https://cal.com/acme"
    assert "https://cal.com/acme" in client.get("/contact-sales").get_data(as_text=True)
