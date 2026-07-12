"""Sequential-edit consistency for the model-mutation pipeline.

Covers the audit findings around cumulative, order-independent results:
- opacity-only material edits must not homogenize per-material colors
- material-only saves must preserve a previously saved transform (geometry)
- version restore must roll bounds/file_size/cumulative_scale back with the GLB
- /apply_modifications must refuse meshopt-compressed models like save does
"""

import json
import os
import uuid

import pytest
import trimesh
from pygltflib import GLTF2

from app import app, db
from models import ModelVersion, UserModel
from tests.test_viewer_page import make_two_material_model


def _material_colors(glb_path):
    gltf = GLTF2().load(glb_path)
    return [list(m.pbrMetallicRoughness.baseColorFactor) for m in gltf.materials]


def test_opacity_only_edit_preserves_per_material_colors(client):
    """A roughness/opacity-only tweak used to still send `color` (mat[0]'s),
    wiping every other material's color. The backend now supports an
    opacity-only payload that keeps each material's own RGB."""
    model_id, glb_path = make_two_material_model(user_id=None)
    colors_before = _material_colors(glb_path)
    assert colors_before[0][:3] != colors_before[1][:3]  # genuinely different

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"material": {"opacity": 0.5}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()

    colors_after = _material_colors(glb_path)
    # RGB per material unchanged, alpha updated on both
    assert colors_after[0][:3] == pytest.approx(colors_before[0][:3])
    assert colors_after[1][:3] == pytest.approx(colors_before[1][:3])
    assert colors_after[0][3] == pytest.approx(0.5)
    assert colors_after[1][3] == pytest.approx(0.5)


def test_metalness_only_edit_preserves_colors(client):
    model_id, glb_path = make_two_material_model(user_id=None)
    colors_before = _material_colors(glb_path)

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"material": {"metalness": 0.9}},
    })
    assert resp.get_json()["success"] is True

    colors_after = _material_colors(glb_path)
    assert colors_after[0] == pytest.approx(colors_before[0])
    assert colors_after[1] == pytest.approx(colors_before[1])
    gltf = GLTF2().load(glb_path)
    assert gltf.materials[0].pbrMetallicRoughness.metallicFactor == pytest.approx(0.9)
    assert gltf.materials[1].pbrMetallicRoughness.metallicFactor == pytest.approx(0.9)


def test_material_only_save_preserves_previous_scale(client):
    """Scale x2 save, then a metalness-only save: the second save must
    operate on the already-scaled GLB, not shrink it back."""
    model_id, glb_path = make_two_material_model(user_id=None)

    def measured_max_extent():
        scene = trimesh.load(glb_path, force="scene")
        return float(max(scene.bounds[1] - scene.bounds[0]))

    size_orig = measured_max_extent()

    r1 = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"transform": {"scale": 2.0, "rotation": {"x": 0, "y": 0, "z": 0}}},
    })
    assert r1.get_json()["success"] is True
    assert measured_max_extent() == pytest.approx(size_orig * 2.0, rel=1e-3)

    r2 = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"material": {"metalness": 0.7}},
    })
    assert r2.get_json()["success"] is True
    assert measured_max_extent() == pytest.approx(size_orig * 2.0, rel=1e-3)

    model = db.session.get(UserModel, model_id)
    assert model.cumulative_scale == pytest.approx(2.0)


def test_two_sequential_scales_compound(client):
    model_id, glb_path = make_two_material_model(user_id=None)
    scene = trimesh.load(glb_path, force="scene")
    size_orig = float(max(scene.bounds[1] - scene.bounds[0]))

    for factor in (2.0, 1.5):
        resp = client.post("/save_modifications", json={
            "model_id": model_id,
            "modifications": {"transform": {"scale": factor, "rotation": {"x": 0, "y": 0, "z": 0}}},
        })
        assert resp.get_json()["success"] is True

    scene = trimesh.load(glb_path, force="scene")
    assert float(max(scene.bounds[1] - scene.bounds[0])) == pytest.approx(size_orig * 3.0, rel=1e-3)
    model = db.session.get(UserModel, model_id)
    assert model.cumulative_scale == pytest.approx(3.0)
    # file_size is maintained on every save now
    assert model.file_size == os.path.getsize(glb_path)


def test_restore_rolls_back_bounds_file_size_and_cumulative_scale(client):
    """Scale x2 (creates v1 snapshot of the ORIGINAL via create_version at
    upload? No — versions are created per operation), then restore the
    pre-scale version: the GLB, bounds JSON, cumulative_scale and file_size
    must all return to the original state together."""
    from version_manager import create_version, restore_version

    model_id, glb_path = make_two_material_model(user_id=None)
    scene = trimesh.load(glb_path, force="scene")
    size_orig = float(max(scene.bounds[1] - scene.bounds[0]))

    # Baseline version (what upload would create)
    assert create_version(model_id, "upload", None, "baseline") is not None

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"transform": {"scale": 2.0, "rotation": {"x": 0, "y": 0, "z": 0}}},
    })
    assert resp.get_json()["success"] is True
    model = db.session.get(UserModel, model_id)
    assert model.cumulative_scale == pytest.approx(2.0)
    bounds_scaled = json.loads(model.bounds)

    assert restore_version(model_id, 1) is True

    db.session.expire_all()
    model = db.session.get(UserModel, model_id)

    # GLB physically restored
    scene = trimesh.load(glb_path, force="scene")
    assert float(max(scene.bounds[1] - scene.bounds[0])) == pytest.approx(size_orig, rel=1e-3)
    # DB metadata restored consistently with it
    bounds_restored = json.loads(model.bounds)
    assert bounds_restored["max"] == pytest.approx(bounds_scaled["max"] / 2.0, rel=1e-2)
    assert model.cumulative_scale == pytest.approx(1.0)
    assert model.file_size == os.path.getsize(glb_path)


def test_apply_modifications_refuses_meshopt_like_save_does(client, monkeypatch):
    model_id, _ = make_two_material_model(user_id=None)

    import blueprints.model_editing  # noqa: F401  (route module)
    import converters.glb_optimizer as glb_optimizer_module
    monkeypatch.setattr(glb_optimizer_module, "glb_requires_meshopt", lambda path: True)

    resp = client.post("/apply_modifications", json={
        "model_id": model_id,
        "modifications": {"transform": {"scale": 2.0}},
    })
    data = resp.get_json()
    assert resp.status_code == 400
    assert data["success"] is False
    assert "cannot be modified" in data["error"]
