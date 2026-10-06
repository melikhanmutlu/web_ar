"""SEC-15/19/20/21/22/28/30 low-severity hardening."""

import os

import pytest
import trimesh

from app import app, db
from models import ModelVersion, MaterialPreset, User, UserModel


def _owner_with_model(client, name="lowowner", visibility="private"):
    owner = User(username=name, email=f"{name}@test.com", plan="business")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model_id = f"low-{name}"
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb = os.path.join(model_dir, "model.glb")
    with open(glb, "wb") as f:
        f.write(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
    db.session.add(UserModel(id=model_id, filename=glb, file_type="glb", user_id=owner.id,
                             visibility=visibility, file_size=os.path.getsize(glb)))
    db.session.commit()
    client.post("/login", data={"username": name, "password": "password"})
    return model_id


@pytest.mark.parametrize("field,value,ok", [
    ("camera_orbit", "30deg 70deg auto", True),
    ("camera_orbit", "0.5rad 1.2rad 2.5m", True),
    ("camera_orbit", "auto", True),
    ("camera_orbit", "<script>alert(1)</script>", False),
    ("camera_orbit", "30deg 70deg auto; x", False),
    ("camera_orbit", "1 2 3 4", False),
    ("field_of_view", "24deg", True),
    ("field_of_view", "24deg 30deg", False),
    ("field_of_view", "x", False),
])
def test_camera_settings_validated(client, field, value, ok):
    model_id = _owner_with_model(client)
    resp = client.patch(f"/api/models/{model_id}/viewer-settings", json={field: value})
    assert resp.status_code == (200 if ok else 400), resp.get_json()


def test_missing_version_is_404_not_500(client):
    model_id = _owner_with_model(client)
    assert client.delete(f"/api/versions/{model_id}/delete/99").status_code == 404
    assert client.post(f"/api/versions/{model_id}/restore/99").status_code == 404


def test_html_pages_send_frame_and_opener_headers_but_embed_stays_frameable(client):
    model_id = _owner_with_model(client, name="lowpub", visibility="public")
    home = client.get("/")
    assert home.headers["X-Frame-Options"] == "SAMEORIGIN"
    assert home.headers["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"
    embed = client.get(f"/embed/{model_id}")
    assert "X-Frame-Options" not in embed.headers
    assert "frame-ancestors *" in embed.headers["Content-Security-Policy"]


def test_embed_default_frame_ancestors_is_configurable(client, monkeypatch):
    model_id = _owner_with_model(client, name="lowpub2", visibility="public")
    monkeypatch.setenv("EMBED_DEFAULT_FRAME_ANCESTORS", "'self' https://partner.example")
    csp = client.get(f"/embed/{model_id}").headers["Content-Security-Policy"]
    assert "frame-ancestors 'self' https://partner.example" in csp


def test_material_preset_requires_valid_name_and_color(client):
    _owner_with_model(client, name="lowpreset")
    assert client.post("/api/material-presets", json={"name": None, "color": "#ffffff"}).status_code == 400
    assert client.post("/api/material-presets", json={"name": "ok", "color": None}).status_code == 400
    assert client.post("/api/material-presets", json={"name": "ok", "color": "#112233",
                                                      "organization_id": "abc"}).status_code == 400
    assert client.post("/api/material-presets", json={"name": "ok", "color": "#112233"}).status_code == 201
    assert MaterialPreset.query.count() == 1


def test_hotspot_text_fields_are_clamped(client):
    model_id = _owner_with_model(client, name="lowhot")
    resp = client.post(f"/api/models/{model_id}/hotspots", json={
        "id": "h" * 200, "title": "t" * 500, "description": "d" * 5000,
        "position": {"x": 0, "y": 0, "z": 0},
    })
    assert resp.status_code == 201, resp.get_json()
    hotspot = resp.get_json()["hotspot"]
    assert len(hotspot["title"]) == 200
    assert len(hotspot["description"]) <= 2000


def test_proxy_hops_env_defaults_to_one():
    # Documented knob (PROXY_FIX_X_FOR); default keeps the single-proxy behaviour.
    assert "PROXY_FIX_X_FOR" not in os.environ
    import app as app_module
    assert app_module._PROXY_HOPS == 1
