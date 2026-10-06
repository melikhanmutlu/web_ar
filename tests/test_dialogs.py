"""Native alert/confirm/prompt are replaced by the shared arConfirm/arPrompt/arToast helpers."""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..")
NATIVE = re.compile(r"(?<![\w.$])(?:window\.)?(?:alert|confirm|prompt)\(")


def _files():
    for sub, exts in (("static/js", (".js",)), ("templates", (".html",))):
        for dirpath, _dirs, names in os.walk(os.path.join(ROOT, sub)):
            rel = os.path.relpath(dirpath, ROOT)
            # admin tooling keeps native dialogs; vendored bundles are not ours
            if rel.startswith(os.path.join("templates", "admin")):
                continue
            for name in names:
                if name.endswith(exts) and not name.endswith(".min.js") and name != "admin.js":
                    yield os.path.join(dirpath, name)


def test_no_native_dialogs_left_in_app_code():
    offenders = []
    for path in _files():
        for no, line in enumerate(open(path, encoding="utf-8", errors="ignore"), 1):
            if NATIVE.search(line):
                offenders.append(f"{os.path.relpath(path, ROOT)}:{no}: {line.strip()[:80]}")
    assert not offenders, "\n".join(offenders)


def test_dialog_helpers_are_defined_app_wide(client):
    html = client.get("/login").get_data(as_text=True)
    assert "window.arConfirm = function" in html
    assert "window.arPrompt = function" in html
    # accessible modal contract
    assert "aria-modal" in html and "'alertdialog'" in html
