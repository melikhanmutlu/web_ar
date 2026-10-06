"""Faz 4 accessibility shell: skip link, main landmark, contrast tokens."""
import os
import re

import pytest

CSS = os.path.join(os.path.dirname(__file__), "..", "static", "css", "arvision.css")
PAGES = ["/", "/pricing", "/features", "/login", "/register", "/discover", "/studio",
         "/developers", "/contact-sales", "/security"]


def _luminance(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _contrast(a, b):
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("path", PAGES)
def test_pages_have_skip_link_and_single_main_target(client, path):
    html = client.get(path, follow_redirects=True).get_data(as_text=True)
    assert 'class="skip-link" href="#main"' in html
    assert len(re.findall(r'<main id="main"', html)) == 1


def test_subtle_text_token_meets_aa_on_every_light_surface():
    css = open(CSS).read()
    token = re.search(r"--text-subtle:\s*(#[0-9a-fA-F]{6})", css).group(1)
    for surface in ("#ffffff", "#f6f7f9", "#eceef3", "#f1f2f5", "#f0f1f4"):
        assert _contrast(token, surface) >= 4.5, (token, surface)


def test_micro_font_floor_and_focus_ring_defined():
    css = open(CSS).read()
    assert re.search(r"--fs-micro:\s*12px", css)
    assert "html :focus-visible" in css
    # no UI microcopy is left below 12px
    assert not re.search(r"font-size:\s*(?:[0-9]|1[01])(?:\.\d+)?px", css)


def test_pricing_not_included_mark_is_a_labelled_dash(client):
    html = client.get("/pricing").get_data(as_text=True)
    assert "&times;" not in html
    assert 'aria-label="Not included">&mdash;</span>' in html


@pytest.mark.parametrize("path", ["/login", "/register", "/discover", "/studio"])
def test_auth_discover_studio_render_the_shared_footer(client, path):
    html = client.get(path).get_data(as_text=True)
    assert '<footer>' in html and 'footer-inner' in html


def test_dead_dark_theme_rules_are_gone():
    assert ".dark " not in open(CSS).read()


def _make_user(name):
    from models import User, db
    u = User(username=name, email=f"{name}@test.com")
    u.set_password("pw")
    db.session.add(u)
    db.session.commit()
    return u


def test_library_empty_state_points_to_studio_and_hides_filters(client):
    _make_user("emptylib")
    client.post("/login", data={"username": "emptylib", "password": "pw"})
    html = client.get("/my_models").get_data(as_text=True)
    assert "Upload your first model in Studio" in html
    assert 'href="/studio"' in html
    assert "library-tools hidden" in html
    assert "library-folder--trash" not in html  # no "Trash 0" card


def test_trash_cards_show_days_left_and_folder_cards_are_links(client):
    import uuid
    from models import Folder, UserModel, db
    from services.time_utils import datetime
    u = _make_user("trashy")
    f = Folder(name="Box", slug="box-1", user_id=u.id)
    m = UserModel(id=str(uuid.uuid4()), filename="x.glb", file_size=1, file_type="glb",
                  user_id=u.id, deleted_at=datetime.utcnow())
    db.session.add_all([f, m])
    db.session.commit()
    client.post("/login", data={"username": "trashy", "password": "pw"})
    trash = client.get("/my_models/trash").get_data(as_text=True)
    assert "Deleted forever in 30 days" in trash
    root = client.get("/my_models").get_data(as_text=True)
    assert f'class="library-folder-link" href="/my_models/{f.id}"' in root
    assert 'class="library-folder-link" href="/my_models/trash"' in root
