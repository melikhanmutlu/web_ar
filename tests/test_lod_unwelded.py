"""P3D-15: LODs must really reduce triangles on unwelded sources and must not
outlive the geometry they were made from."""

import os
import uuid

import numpy as np
import pytest
import trimesh

import app as app_module
from converters import glb_optimizer, lod_generator
from models import ModelLOD, UserModel, db


def _flat_shaded_sphere(path):
    """Fully unwelded, per-face-normal sphere: what STL-derived GLBs look like."""
    sphere = trimesh.creation.icosphere(subdivisions=5)
    vertices = sphere.vertices[sphere.faces].reshape(-1, 3)
    mesh = trimesh.Trimesh(vertices, np.arange(len(vertices)).reshape(-1, 3), process=False)
    mesh.vertex_normals = np.repeat(sphere.face_normals, 3, axis=0)
    mesh.export(path)
    return len(sphere.faces)


def test_lod_generator_reduces_triangles_on_unwelded_source(tmp_path):
    if glb_optimizer._resolve_gltfpack() is None:
        pytest.skip("gltfpack unavailable")
    source = tmp_path / "model.glb"
    source_triangles = _flat_shaded_sphere(source)
    ratios = [0.5, 0.25, 0.1]
    outputs = lod_generator.generate_lods(source, tmp_path / "out", ratios=ratios, meshopt=False)
    counts = [lod_generator._triangle_count(item["path"]) for item in outputs]
    assert len(counts) == 3
    for count, ratio in zip(counts, ratios):
        assert count <= source_triangles * ratio * 1.5, (counts, source_triangles)
    assert counts == sorted(counts, reverse=True)


def _model_with_lod():
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app_module.app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(glb_path)
    lod_path = os.path.join(model_dir, "model_lod1.glb")
    trimesh.creation.box().export(lod_path)
    db.session.add(UserModel(id=model_id, filename=glb_path, file_type="glb", file_size=10,
                             user_id=None, cumulative_scale=1.0))
    db.session.add(ModelLOD(model_id=model_id, level=1, ratio=0.5, filename=lod_path, file_size=10))
    db.session.commit()
    return model_id, lod_path


def test_save_modifications_invalidates_lods(client):
    model_id, lod_path = _model_with_lod()
    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"transform": {"scale": 2.0, "rotation": {"x": 0, "y": 0, "z": 0}}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()
    db.session.expire_all()
    assert ModelLOD.query.filter_by(model_id=model_id).count() == 0
    assert not os.path.exists(lod_path)


def test_restore_version_invalidates_lods(client):
    from version_manager import create_version, restore_version

    model_id, lod_path = _model_with_lod()
    assert create_version(model_id, "upload") is not None
    assert restore_version(model_id, 1)
    db.session.expire_all()
    assert ModelLOD.query.filter_by(model_id=model_id).count() == 0
    assert not os.path.exists(lod_path)
