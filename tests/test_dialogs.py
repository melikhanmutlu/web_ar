"""Native alert/confirm/prompt are replaced by the shared arConfirm/arPrompt/arToast helpers."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
NATIVE = re.compile(r"(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\(")


def _files():
    for sub, exts in (("static/js", (".js",)), ("templates", (".html",))):
        for dirpath, _dirs, names in os.walk(os.path.join(ROOT, sub)):
            # vendored bundles are not ours
            for name in names:
                if name.endswith(exts) and not name.endswith(".min.js"):
                    yield os.path.join(dirpath, name)


def test_no_native_dialogs_left_in_app_code():
    offenders = []
    for path in _files():
        for no, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
            if NATIVE.search(line):
                offenders.append(f"{os.path.relpath(path, ROOT)}:{no}: {line.strip()[:80]}")
    assert not offenders, "\n".join(offenders)


def _security_head_js(client, html):
    match = re.search(r'<script src="([^"]*security-head\.js)"', html)
    assert match, "page must load the shared dialog helpers (security-head.js)"
    return client.get(match.group(1)).get_data(as_text=True)


def test_dialog_helpers_are_defined_app_wide(client):
    html = client.get("/login").get_data(as_text=True)
    js = _security_head_js(client, html)
    assert "window.arConfirm = function" in js
    assert "window.arPrompt = function" in js
    assert "window.arToast = function" in js
    # accessible modal contract
    assert "aria-modal" in js and "'alertdialog'" in js


def test_admin_pages_load_the_shared_dialog_helpers(client):
    from models import User, db

    admin = User(username="dlgadmin", email="dlgadmin@test.com", is_admin=True)
    admin.set_password("pw")
    db.session.add(admin)
    db.session.commit()
    client.post("/login", data={"username": "dlgadmin", "password": "pw"})
    for path in ("/admin/", "/admin/users", "/admin/settings"):
        response = client.get(path)
        assert response.status_code == 200, path
        html = response.get_data(as_text=True)
        assert "js/security-head.js" in html, path
        # security-head.js is loaded before admin.js so arToast/arConfirm exist when it runs
        assert html.index("js/security-head.js") < html.index("js/admin.js"), path


def test_admin_js_uses_shared_dialogs():
    text = open(os.path.join(ROOT, "static/js/admin.js"), encoding="utf-8").read()
    assert "window.arConfirm(" in text
    settings = open(os.path.join(ROOT, "templates/admin/settings.html"), encoding="utf-8").read()
    assert "data-confirm-submit" in settings
