"""Overhauled admin settings: new tabs, new consumed settings, system status."""
from datetime import datetime

from models import User, UserModel, WorkerHeartbeat, db
import site_settings


def _admin(client):
    user = User(username="setadmin", email="setadmin@test.com", is_admin=True)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": user.username, "password": "password"})
    return user


def test_all_settings_tabs_render(client):
    _admin(client)
    for tab in ("general", "users", "ai", "uploads", "plans", "system"):
        assert client.get(f"/admin/settings?tab={tab}").status_code == 200, tab


def test_system_tab_shows_workers_and_raw_settings(client):
    _admin(client)
    db.session.add(WorkerHeartbeat(
        worker_id="host:42", hostname="host", process_id=42,
        last_seen_at=datetime.utcnow(),
    ))
    db.session.commit()
    site_settings.set_setting("announcement_text", "hello world")
    page = client.get("/admin/settings?tab=system").get_data(as_text=True)
    assert "host:42" in page          # workers table
    assert "announcement_text" in page  # raw settings table
    assert "integrations" in page
    assert "runtime config" in page


def test_default_new_user_plan_saved_and_consumed(client):
    _admin(client)
    resp = client.post("/admin/settings?tab=users", data={
        "registration_enabled": "on",
        "default_new_user_plan": "pro",
    })
    assert resp.status_code == 302
    client.post("/logout")

    client.post("/register", data={
        "username": "newbie", "email": "newbie@test.com",
        "password": "Password123!", "confirm_password": "Password123!",
    })
    created = User.query.filter_by(username="newbie").first()
    assert created is not None
    assert created.plan == "pro"


def test_unknown_default_plan_is_rejected(client):
    _admin(client)
    client.post("/admin/settings?tab=users", data={
        "registration_enabled": "on",
        "default_new_user_plan": "bogus-plan",
    })
    assert site_settings.get_setting("default_new_user_plan") is None


def test_seo_index_override_controls_view_robots(client):
    admin = _admin(client)
    model = UserModel(
        id="9a9a9a9a-9a9a-9a9a-9a9a-9a9a9a9a9a9a",
        filename="unused.glb", user_id=admin.id, visibility="public",
    )
    db.session.add(model)
    db.session.commit()

    # Default env is off -> noindex.
    from blueprints.viewer import _seo_robots_for_model_page
    assert _seo_robots_for_model_page(is_canonical=True) == "noindex, follow"

    # Admin turns indexing on via settings.
    resp = client.post("/admin/settings?tab=general", data={
        "seo_index_model_pages": "on", "announcement_text": "",
    })
    assert resp.status_code == 302
    site_settings.invalidate_cache()
    assert _seo_robots_for_model_page(is_canonical=True) == "index, follow"
    # Embed/VR stay noindex regardless.
    assert _seo_robots_for_model_page(is_canonical=False) == "noindex, follow"


def test_system_tab_post_is_a_noop(client):
    _admin(client)
    resp = client.post("/admin/settings?tab=system", data={"anything": "x"})
    assert resp.status_code == 302
