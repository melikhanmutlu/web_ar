"""Route-inventory authorization test (OPS-21).

Walks ``app.url_map`` and, for every route that takes a model id in its URL,
calls it as an anonymous visitor and as a different logged-in user against a
PRIVATE model owned by someone else. It asserts that none of them returns a 2xx
response, never echoes the model's data, and leaves the model untouched.

Because it is generated from the URL map, a newly added ``<model_id>`` route
is covered automatically; a route that is intentionally reachable on a private
model must be added to ``INTENTIONALLY_OPEN`` below with a justification.
"""

import os
import uuid

import pytest

from app import app, db
from models import ModelHotspot, ModelShareLink, ModelVersion, User, UserModel

MARKER = "PRIVATE-MARKER-7f3a9c"
MODEL_ARG_NAMES = {"model_id", "unique_id", "left_id", "right_id"}
SKIP_METHODS = {"HEAD", "OPTIONS"}

# (endpoint, METHOD) pairs that may legitimately answer 2xx for a stranger on a
# private model, with the reason. Keep this list short and justified.
INTENTIONALLY_OPEN = {
    # (none today)
}

# Routes whose model-id argument is NOT a user-model id (or that are handled by
# the dedicated tests in tests/test_file_serving.py). Listed so that a new,
# unexpected route can't silently dodge the inventory.
EXCLUDED_ENDPOINTS = set()

# Body-carried model ids (no <model_id> in the URL). These are exercised by
# test_body_addressed_model_routes_deny_strangers.
BODY_ROUTES = [
    ("models_crud.move_model", "POST"),
    ("models_crud.move_selected_models", "POST"),
    ("models_crud.delete_selected_models", "POST"),
    ("models_crud.restore_selected_models", "POST"),
    ("models_crud.bulk_update_visibility", "POST"),
    ("models_crud.bulk_add_tags", "POST"),
]


def _path_value(arg, converter_name, ids):
    if arg in MODEL_ARG_NAMES:
        return ids["model"]
    if arg == "fmt":
        return "stl"
    if arg == "filename":
        return "model.glb"
    if arg == "hotspot_id":
        return "h1"
    if converter_name == "IntegerConverter":
        return "1"
    return "1"


def _inventory():
    """[(rule, endpoint, method)] for every model-id-taking route."""
    rows = []
    for rule in app.url_map.iter_rules():
        if not (rule.arguments & MODEL_ARG_NAMES):
            continue
        if rule.endpoint in EXCLUDED_ENDPOINTS or rule.endpoint == "static":
            continue
        for method in sorted(rule.methods - SKIP_METHODS):
            rows.append((rule, rule.endpoint, method))
    return rows


def _build_url(rule, ids):
    values = {}
    for arg, conv in rule._converters.items():
        values[arg] = _path_value(arg, type(conv).__name__, ids)
    adapter = app.url_map.bind("localhost")
    return adapter.build(rule.endpoint, values, method="GET" if "GET" in rule.methods else None)


def _login(client, username):
    return client.post("/login", data={"username": username, "password": "pw"})


@pytest.fixture
def private_model(client, tmp_path, monkeypatch):
    conv = tmp_path / "converted"
    conv.mkdir()
    monkeypatch.setitem(app.config, "CONVERTED_FOLDER", str(conv))
    monkeypatch.setitem(app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    owner = User(username="owner", email="owner@test.com")
    owner.set_password("pw")
    stranger = User(username="stranger", email="stranger@test.com")
    stranger.set_password("pw")
    db.session.add_all([owner, stranger])
    db.session.commit()

    mid = str(uuid.uuid4())
    d = conv / mid
    d.mkdir()
    for name in ("model.glb", "model.usdz", "model_backup_1.glb", "modified_1.glb"):
        (d / name).write_bytes(b"glTF" + MARKER.encode())
    model = UserModel(
        id=mid, filename=str(d / "model.glb"), file_size=10, file_type="glb",
        user_id=owner.id, visibility="private", description=MARKER,
        display_name=MARKER, source_filename=f"{MARKER}.stl", tags="secret",
    )
    db.session.add(model)
    db.session.flush()
    db.session.add(ModelHotspot(model_id=mid, hotspot_id="h1", title=MARKER,
                                position_x=0, position_y=0, position_z=0))
    db.session.add(ModelVersion(model_id=mid, version_number=1, filename="v1.glb",
                                operation_type="upload"))
    db.session.commit()
    return type("P", (), dict(id=mid, owner=owner, stranger=stranger, dir=d))


def _snapshot(model_id):
    db.session.expire_all()
    m = db.session.get(UserModel, model_id)
    return dict(
        exists=m is not None,
        deleted=m.deleted_at if m else None,
        visibility=m.visibility if m else None,
        user_id=m.user_id if m else None,
        organization_id=m.organization_id if m else None,
        folder_id=m.folder_id if m else None,
        tags=m.tags if m else None,
        description=m.description if m else None,
        hotspots=ModelHotspot.query.filter_by(model_id=model_id).count(),
        versions=ModelVersion.query.filter_by(model_id=model_id).count(),
        share_links=ModelShareLink.query.filter_by(model_id=model_id).count(),
        files=sorted(os.listdir(os.path.dirname(m.filename))) if m else [],
        like_count=getattr(m, "like_count", None) if m else None,
    )


def _call(client, method, url):
    kwargs = {"json": {}} if method in {"POST", "PUT", "PATCH", "DELETE"} else {}
    return client.open(url, method=method, **kwargs)


def test_inventory_is_not_vacuous():
    rows = _inventory()
    endpoints = {endpoint for _, endpoint, _ in rows}
    # Sanity: the walk must see the core model routes in several blueprints.
    for expected in ("viewer.view_model", "models_crud.delete_model",
                     "hotspots.get_hotspots", "versions.get_versions",
                     "model_files.serve_converted_file", "sharing.create_model_share_link",
                     "api_tokens.api_v1_delete_model", "admin.purge_model"):
        assert expected in endpoints, f"{expected} missing from the route inventory"
    assert len(rows) >= 60


@pytest.mark.parametrize("actor", ["anonymous", "stranger"])
def test_no_model_route_serves_a_private_model_to_non_authorised_users(
        client, private_model, actor):
    before = _snapshot(private_model.id)
    ids = {"model": private_model.id}
    if actor == "stranger":
        _login(client, "stranger")

    failures = []
    for rule, endpoint, method in _inventory():
        url = _build_url(rule, ids)
        resp = _call(client, method, url)
        # A 5xx is an unhandled error, not an authorization decision.
        if resp.status_code >= 500:
            failures.append(f"{method} {url} ({endpoint}) -> {resp.status_code} (server error)")
            continue
        if MARKER.encode() in resp.get_data():
            failures.append(f"{method} {url} ({endpoint}) leaked private model data")
        if 200 <= resp.status_code < 300 and (endpoint, method) not in INTENTIONALLY_OPEN:
            failures.append(f"{method} {url} ({endpoint}) -> {resp.status_code}")

    assert not failures, "Authorization regressions:\n" + "\n".join(failures)
    assert _snapshot(private_model.id) == before, "a denied request modified the model"


def test_owner_can_still_reach_the_same_private_model(client, private_model):
    """Guards against the matrix passing only because everything is broken."""
    _login(client, "owner")
    for url in (f"/api/models/{private_model.id}/hotspots",
                f"/api/versions/{private_model.id}",
                f"/converted_files/{private_model.id}/model.glb"):
        assert client.get(url).status_code == 200, url


@pytest.mark.parametrize("actor", ["anonymous", "stranger"])
def test_body_addressed_model_routes_deny_strangers(client, private_model, actor):
    before = _snapshot(private_model.id)
    if actor == "stranger":
        _login(client, "stranger")
    payloads = {
        "models_crud.move_model": {"model_id": private_model.id, "folder_id": None},
        "models_crud.move_selected_models": {"model_ids": [private_model.id]},
        "models_crud.delete_selected_models": {"model_ids": [private_model.id]},
        "models_crud.restore_selected_models": {"model_ids": [private_model.id]},
        "models_crud.bulk_update_visibility": {"model_ids": [private_model.id],
                                               "visibility": "public"},
        "models_crud.bulk_add_tags": {"model_ids": [private_model.id], "tags": ["pwn"]},
    }
    covered = {endpoint for endpoint, _ in BODY_ROUTES}
    assert covered == set(payloads)
    rules = {r.endpoint: r for r in app.url_map.iter_rules()}
    for endpoint, method in BODY_ROUTES:
        resp = client.open(rules[endpoint].rule, method=method, json=payloads[endpoint])
        assert resp.status_code < 500, endpoint
        data = resp.get_json(silent=True) or {}
        # Either an HTTP denial/redirect, or an explicit success:false body.
        assert not (200 <= resp.status_code < 300 and data.get("success") is True), endpoint
        assert MARKER.encode() not in resp.get_data(), endpoint
    assert _snapshot(private_model.id) == before
