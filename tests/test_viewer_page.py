"""Viewer page (view.html) audit fixes.

Covers: multi-material preservation on transform-only saves, can_edit
gating of the edit UI, the public read-only dimensions endpoint, and the
/api/model-info route converter (UUID string ids, not int).
"""

import os
import uuid

import numpy as np
import pytest
import trimesh
from pygltflib import GLTF2

import app as app_module
from app import app, db
from models import User, UserModel


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_user(username, email):
    u = User(username=username, email=email)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def make_two_material_model(user_id=None):
    """A GLB with two boxes carrying two DIFFERENT materials."""
    model_id = "test-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")

    box_a = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    box_a.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            name="matA", baseColorFactor=[1.0, 0.0, 0.0, 1.0], metallicFactor=0.1, roughnessFactor=0.2)
    )
    box_b = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    box_b.apply_translation([0.3, 0, 0])
    box_b.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            name="matB", baseColorFactor=[0.0, 0.0, 1.0, 1.0], metallicFactor=0.9, roughnessFactor=0.8)
    )
    scene = trimesh.Scene()
    scene.add_geometry(box_a, node_name="a")
    scene.add_geometry(box_b, node_name="b")
    scene.export(glb_path)

    # view_model parses filename as a real path under CONVERTED_FOLDER —
    # store the full path exactly like the upload pipeline does.
    model = UserModel(id=model_id, filename=glb_path,
                      file_type="glb", file_size=1000, user_id=user_id,
                      cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()
    return model_id, glb_path


def make_sized_box_model(extent, user_id=None):
    """A single-box GLB whose largest side is exactly `extent` meters —
    for exercising the AR scale-plausibility warning at its boundaries."""
    model_id = "test-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")

    box = trimesh.creation.box(extents=(extent, extent, extent))
    scene = trimesh.Scene()
    scene.add_geometry(box, node_name="a")
    scene.export(glb_path)

    model = UserModel(id=model_id, filename=glb_path,
                      file_type="glb", file_size=1000, user_id=user_id,
                      cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()
    return model_id, glb_path


@pytest.fixture(autouse=True)
def _no_usdz(monkeypatch):
    monkeypatch.setattr(app_module, "refresh_usdz_after_edit", lambda *a, **k: None)


def test_transform_only_save_preserves_all_materials(client):
    """A /save_modifications payload WITHOUT a material block (what the
    frontend now sends when material controls were never touched) must
    leave every material in the GLB untouched."""
    model_id, glb_path = make_two_material_model(user_id=None)

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"transform": {"scale": 2.0}},
    })
    body = resp.get_json()
    assert resp.status_code == 200 and body["success"], body

    gltf = GLTF2().load(glb_path)
    assert len(gltf.materials) == 2
    all_colors = {tuple(round(c, 2) for c in m.pbrMetallicRoughness.baseColorFactor)
                  for m in gltf.materials}
    assert (1.0, 0.0, 0.0, 1.0) in all_colors, "material A's red was lost"
    assert (0.0, 0.0, 1.0, 1.0) in all_colors, "material B's blue was lost"

    # And the transform really did apply.
    scene = trimesh.load(glb_path, force="scene")
    assert float(max(scene.extents)) > 0.5  # 0.4 span * 2.0 scale


def test_save_with_material_block_still_applies(client):
    """When the user DID touch material controls, the material block is
    sent and applied (to all materials — the documented existing behavior)."""
    model_id, glb_path = make_two_material_model(user_id=None)

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"material": {"color": [0.0, 1.0, 0.0], "metalness": 0.5,
                                        "roughness": 0.5, "opacity": 1.0}},
    })
    body = resp.get_json()
    assert resp.status_code == 200 and body["success"], body

    gltf = GLTF2().load(glb_path)
    for m in gltf.materials:
        assert tuple(round(c, 2) for c in m.pbrMetallicRoughness.baseColorFactor[:3]) == (0.0, 1.0, 0.0)


def test_edit_ui_hidden_from_non_owner(client):
    """A user-owned model viewed by another (anonymous) visitor must not
    render the Save bar / slicer Apply / annotation actions / hotspot
    add button — the backend would 403 all of them anyway."""
    owner = make_user("owner1", "owner1@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)

    resp = client.get(f"/view/{model_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="saveChanges"' not in body
    assert 'id="slicerApply"' not in body
    assert 'id="saveCameraView"' not in body
    assert 'id="toggleHotspotMode"' not in body
    assert 'id="clearAnnotations"' not in body
    assert 'id="undoButton"' not in body
    assert 'id="redoButton"' not in body
    assert "canEdit: false" in body


def test_edit_ui_rendered_for_anonymous_model(client):
    """Anonymous models (user_id None) are editable by anyone by design —
    the edit UI must stay visible."""
    model_id, _ = make_two_material_model(user_id=None)

    resp = client.get(f"/view/{model_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'id="saveChanges"' in body
    assert 'id="slicerApply"' in body
    assert 'id="undoButton"' in body
    assert 'id="redoButton"' in body
    assert "canEdit: true" in body


def test_edit_ui_rendered_for_owner(client):
    owner = make_user("owner2", "owner2@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)
    login(client, "owner2", "testpassword123")

    resp = client.get(f"/view/{model_id}")
    body = resp.get_data(as_text=True)
    assert 'id="saveChanges"' in body
    assert "canEdit: true" in body


def test_ar_placement_setting_reflected_in_model_viewer_tag(client):
    owner = make_user("owner-ar", "owner-ar@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)
    login(client, "owner-ar", "testpassword123")

    model = db.session.get(UserModel, model_id)
    model.viewer_settings = {"ar_placement": "ceiling"}
    db.session.commit()

    resp = client.get(f"/view/{model_id}")
    body = resp.get_data(as_text=True)
    assert 'ar-placement="ceiling"' in body


def test_ar_error_feedback_elements_rendered(client):
    """The AR modal must expose a title/message pair the JS can rewrite per
    failure reason (unsupported device / iOS USDZ still converting / AR
    session failed, e.g. denied camera permission) instead of always
    showing a single generic message."""
    owner = make_user("owner-ar-err", "owner-ar-err@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)
    login(client, "owner-ar-err", "testpassword123")

    body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert 'id="arModalTitle"' in body
    assert 'id="arModalMessage"' in body


def test_dimensions_endpoint_public(client):
    """/get_model_dimensions is read-only data already shown publicly on the
    page — a non-owner (anonymous) request must not 403."""
    owner = make_user("owner3", "owner3@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)

    resp = client.get(f"/get_model_dimensions/{model_id}")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


def test_dimensions_endpoint_no_scale_warning_for_plausible_model(client):
    model_id, _ = make_sized_box_model(extent=0.5)  # 50cm — plainly plausible
    body = client.get(f"/get_model_dimensions/{model_id}").get_json()
    assert body["scale_warning"] is None


def test_dimensions_endpoint_warns_on_implausibly_tiny_model(client):
    """A model whose largest side is a few millimeters looks like a
    mm-mistaken-for-m unit bug once dropped into AR at real scale."""
    model_id, _ = make_sized_box_model(extent=0.005)  # 5mm
    body = client.get(f"/get_model_dimensions/{model_id}").get_json()
    assert body["scale_warning"] is not None
    assert "cm" in body["scale_warning"]


def test_dimensions_endpoint_warns_on_implausibly_huge_model(client):
    model_id, _ = make_sized_box_model(extent=50)  # 50m
    body = client.get(f"/get_model_dimensions/{model_id}").get_json()
    assert body["scale_warning"] is not None
    assert "m —" in body["scale_warning"]


def test_analytics_panel_rendered_for_owner_only(client):
    owner = make_user("owner-analytics", "owner-analytics@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)

    anon_body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert 'id="analyticsContainer"' not in anon_body
    assert "js/viewer/analytics-panel.js" not in anon_body

    login(client, "owner-analytics", "testpassword123")
    owner_body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert 'id="analyticsContainer"' in owner_body
    assert "js/viewer/analytics-panel.js" in owner_body


def test_embed_panel_rendered_for_owner_only(client):
    owner = make_user("owner-embed", "owner-embed@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)

    anon_body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert 'id="embedContainer"' not in anon_body
    assert "js/viewer/embed-panel.js" not in anon_body

    login(client, "owner-embed", "testpassword123")
    owner_body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert 'id="embedContainer"' in owner_body
    assert "js/viewer/embed-panel.js" in owner_body


def test_model_info_route_accepts_uuid_ids(client):
    """/api/model-info used <int:model_id> while ids are UUID strings, so it
    could never match. It must at least route now (401/302 for anonymous —
    it's login-protected — rather than 404-by-no-route)."""
    owner = make_user("owner4", "owner4@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)

    resp = client.get(f"/api/model-info/{model_id}")
    assert resp.status_code in (302, 401)  # login redirect, not a routing 404

    login(client, "owner4", "testpassword123")
    resp = client.get(f"/api/model-info/{model_id}")
    assert resp.status_code == 200
