"""Faz 6: script-src carries no 'unsafe-inline'.

Every page must therefore be free of inline ``on*=`` handlers and of inline
executable ``<script>`` blocks (those must be external files or carry the
per-request CSP nonce; JSON data blocks are not executed and are exempt).
The HTML-route walk is generated from ``app.url_map`` so a new page is covered
automatically.
"""

import os
import re
import uuid
from html.parser import HTMLParser

import pytest

from app import app, db
from models import User, UserModel

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA_SCRIPT_TYPES = {"application/json", "application/ld+json", "importmap", "speculationrules"}
INLINE_HANDLER = re.compile(r"""(?<![\w-])on[a-z]+\s*=""", re.I)


class _Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.problems = []
        self.nonces = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name, value in attrs.items():
            if name.startswith("on"):
                self.problems.append(f"inline handler {name}=... on <{tag}>")
            if name in ("href", "src", "action", "formaction") and (value or "").strip().lower().startswith("javascript:"):
                self.problems.append(f"javascript: URL on <{tag}>")
        if tag == "script" and "src" not in attrs:
            script_type = (attrs.get("type") or "").lower()
            if script_type in DATA_SCRIPT_TYPES:
                return
            if not attrs.get("nonce"):
                self.problems.append("inline <script> without a nonce")
            else:
                self.nonces.append(attrs["nonce"])


def _audit(response):
    parser = _Audit()
    parser.feed(response.get_data(as_text=True))
    problems = list(parser.problems)
    policy = response.headers.get("Content-Security-Policy", "")
    script_src = _script_src(policy)
    assert "'unsafe-inline'" not in script_src
    for nonce in parser.nonces:
        if f"'nonce-{nonce}'" not in script_src:
            problems.append("script nonce is not allowed by the CSP header")
    return problems


def _script_src(policy):
    for directive in policy.split(";"):
        directive = directive.strip()
        if directive.startswith("script-src"):
            return directive
    return ""


@pytest.fixture
def pages(client, tmp_path, monkeypatch):
    conv = tmp_path / "converted"
    conv.mkdir()
    monkeypatch.setitem(app.config, "CONVERTED_FOLDER", str(conv))
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    owner = User(username="cspowner", email="cspowner@test.com")
    owner.set_password("pw")
    admin = User(username="cspadmin", email="cspadmin@test.com", is_admin=True)
    admin.set_password("pw")
    db.session.add_all([owner, admin])
    db.session.commit()
    model_id = str(uuid.uuid4())
    folder = conv / model_id
    folder.mkdir()
    (folder / "model.glb").write_bytes(b"glTF")
    db.session.add(UserModel(id=model_id, filename=str(folder / "model.glb"), file_size=4,
                             file_type="glb", user_id=owner.id, visibility="public",
                             display_name="CSP model"))
    db.session.commit()
    return {"model_id": model_id}


def _get_urls(model_id):
    adapter = app.url_map.bind("localhost")
    urls = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or rule.endpoint == "static":
            continue
        values = {}
        for arg in rule.arguments:
            values[arg] = model_id if arg in {"model_id", "unique_id", "left_id", "right_id"} else "1"
        try:
            urls.append((rule.endpoint, adapter.build(rule.endpoint, values, method="GET")))
        except Exception:
            continue
    return urls


def _login(client, username):
    client.get("/logout")
    client.post("/login", data={"username": username, "password": "pw"})


@pytest.mark.parametrize("actor", ["anonymous", "cspowner", "cspadmin"])
def test_every_html_route_has_no_inline_handlers_or_unnonced_scripts(client, pages, actor):
    if actor != "anonymous":
        _login(client, actor)
    failures = []
    rendered = 0
    for endpoint, url in _get_urls(pages["model_id"]):
        if url.startswith("/logout"):
            continue
        response = client.get(url)
        if response.status_code >= 500 or response.mimetype != "text/html":
            continue
        rendered += 1
        for problem in _audit(response):
            failures.append(f"{url} ({endpoint}): {problem}")
    assert rendered >= 15, "route walk rendered suspiciously few HTML pages"
    assert not failures, "\n".join(failures)


def test_templates_have_no_inline_handlers_or_unnonced_scripts_in_source():
    """Catches branches the route walk can't reach (error pages, conditionals)."""
    problems = []
    for dirpath, _dirs, names in os.walk(os.path.join(ROOT, "templates")):
        for name in names:
            if not name.endswith(".html"):
                continue
            path = os.path.join(dirpath, name)
            text = open(path, encoding="utf-8").read()
            rel = os.path.relpath(path, ROOT)
            for match in re.finditer(r"<[a-zA-Z][^<>]*?\son[a-z]+\s*=", text):
                problems.append(f"{rel}: inline handler near {match.group(0)[:60]!r}")
            for match in re.finditer(r"<script\b([^>]*)>", text):
                attrs = match.group(1)
                if "src=" in attrs or "nonce=" in attrs:
                    continue
                if re.search(r"""type\s*=\s*["'](application/(ld\+)?json|importmap)""", attrs):
                    continue
                problems.append(f"{rel}: inline <script> without nonce")
    assert not problems, "\n".join(problems)


def test_js_does_not_build_inline_handler_markup():
    problems = []
    for dirpath, _dirs, names in os.walk(os.path.join(ROOT, "static", "js")):
        for name in names:
            if not name.endswith(".js") or ".min." in name:
                continue
            path = os.path.join(dirpath, name)
            for no, line in enumerate(open(path, encoding="utf-8"), 1):
                if re.search(r"""\son(click|change|input|submit|error|load|key\w+|mouse\w+|drag\w+|drop)=\\?["']""", line):
                    problems.append(f"{os.path.relpath(path, ROOT)}:{no}")
    assert not problems, "\n".join(problems)


def test_script_src_has_no_unsafe_inline_and_no_unused_hosts(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    script_src = _script_src(policy)
    assert "'unsafe-inline'" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert "'wasm-unsafe-eval'" in script_src
    assert "'nonce-" in script_src  # base head bootstrap script uses the nonce
    for host in ("ajax.googleapis.com", "cdnjs.cloudflare.com", "aframe.io", "cdn.rawgit.com",
                 "fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in policy


def test_nonce_is_unique_per_request(client):
    def nonce():
        return re.search(r"'nonce-([^']+)'", client.get("/").headers["Content-Security-Policy"]).group(1)

    assert nonce() != nonce()


def test_vr_route_alone_gets_unsafe_eval(client, pages):
    vr = client.get(f"/vr/{pages['model_id']}")
    assert vr.status_code == 200
    vr_script_src = _script_src(vr.headers["Content-Security-Policy"])
    assert "'unsafe-eval'" in vr_script_src
    assert "'unsafe-inline'" not in vr_script_src
    view = client.get(f"/view/{pages['model_id']}")
    assert "'unsafe-eval'" not in _script_src(view.headers["Content-Security-Policy"])
