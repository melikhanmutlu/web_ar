"""SEC-13: malformed / wrongly-typed JSON bodies must yield a 4xx, never a 500.

The sweep discovers every POST/PUT/PATCH/DELETE route whose view function
reads a JSON body and posts several hostile bodies at it as the model owner
(who gets past the auth guards, so the JSON handling is actually reached)."""

import inspect
import os
import re

import pytest
import trimesh

from app import app, db
from models import ModelHotspot, User, UserModel

# Routes that legitimately need signed/third-party payloads or are outside the
# user-facing JSON surface.
SKIP_ENDPOINTS = {
    "static",
    "billing.paytr_callback", "billing.lemonsqueezy_webhook",
    "ai_generation.meshy_webhook",
}

BODIES = [
    ("garbage", b"{not json", "application/json"),
    ("list", b"[1, 2, 3]", "application/json"),
    ("string", b'"hello"', "application/json"),
    ("null", b"null", "application/json"),
    ("number", b"123", "application/json"),
    ("wrong_types", b'{"title": null, "name": null, "model_id": null, "folder_id": "abc", '
                    b'"visible": "yes", "modifications": "x", "planes": "zz", "items": "x", '
                    b'"distance_cm": "Infinity", "orbit": null, "material": "x", "price": "abc", '
                    b'"model_ids": "x", "event_type": [], "metadata": "x", "body": null}',
     "application/json"),
]


def _reads_json(view):
    try:
        src = inspect.getsource(view)
    except (OSError, TypeError):
        return False
    return bool(re.search(r"get_json|request\.json\b|json_dict", src))


def _json_routes():
    routes = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        methods = (rule.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}
        view = app.view_functions.get(rule.endpoint)
        if not methods or view is None:
            continue
        target = inspect.unwrap(view)
        if not _reads_json(target):
            continue
        for method in sorted(methods):
            routes.append((rule.endpoint, rule.rule, method))
    return routes


JSON_ROUTES = _json_routes()


def _fill(rule, model_id, hotspot_id):
    def sub(match):
        name = match.group(2)
        conv = match.group(1) or ""
        if name == "model_id":
            return model_id
        if name == "hotspot_id":
            return hotspot_id
        if conv.startswith("int"):
            return "1"
        return "1"
    return re.sub(r"<(?:([a-z_]+)(?:\([^>]*\))?:)?([a-zA-Z_]+)>", sub, rule)


@pytest.fixture
def owner_client(client):
    owner = User(username="fuzzowner", email="fuzz@test.com", plan="business")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model_id = "fuzz-model-0001"
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb = os.path.join(model_dir, "model.glb")
    with open(glb, "wb") as f:
        f.write(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
    db.session.add(UserModel(id=model_id, filename=glb, file_type="glb", user_id=owner.id,
                             file_size=os.path.getsize(glb)))
    db.session.flush()
    hotspot = ModelHotspot(model_id=model_id, hotspot_id="h1", title="h", position_x=0, position_y=0, position_z=0,
                           normal_x=0, normal_y=1, normal_z=0)
    db.session.add(hotspot)
    db.session.commit()
    client.post("/login", data={"username": "fuzzowner", "password": "password"})
    return client, model_id, hotspot.hotspot_id


def test_json_route_sweep_found_routes():
    # Guard against the discovery silently matching nothing.
    assert len(JSON_ROUTES) >= 25


@pytest.mark.parametrize("endpoint,rule,method", JSON_ROUTES)
def test_invalid_json_never_500(owner_client, endpoint, rule, method, monkeypatch):
    monkeypatch.setitem(app.config, "PROPAGATE_EXCEPTIONS", False)
    import ai_generator
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    client, model_id, hotspot_id = owner_client
    url = _fill(rule, model_id, hotspot_id)
    failures = []
    for label, body, ctype in BODIES:
        resp = client.open(url, method=method, data=body, content_type=ctype)
        if resp.status_code >= 500:
            failures.append(f"{label}: {resp.status_code}")
    assert not failures, f"{method} {url} ({endpoint}): {failures}"
