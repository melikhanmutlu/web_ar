"""Coverage for mesh_slicer.py's material/UV preservation across a slice,
and for the previously-missing `scipy` dependency that silently disabled
capping for every single slice (trimesh's slice_plane imports
scipy.spatial.cKDTree unconditionally, even when cap=False)."""

import os
import uuid

import numpy as np
import pytest
import trimesh
from pygltflib import GLTF2

import mesh_slicer as ms
from app import app
from models import UserModel, db


@pytest.fixture
def textured_model_on_disk(client):
    """A model whose GLB already carries a distinctive PBR material (color /
    metalness / roughness), mirroring what /save_modifications bakes in
    before a later /slice_model call."""
    model_id = "test-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")

    box = trimesh.creation.box(extents=(0.2, 0.2, 0.2))
    uv = np.random.rand(len(box.vertices), 2)
    material = trimesh.visual.material.PBRMaterial(
        baseColorFactor=[0.2, 0.4, 0.6, 1.0],
        metallicFactor=0.3,
        roughnessFactor=0.7,
    )
    box.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    box.export(glb_path)

    model = UserModel(id=model_id, filename=f"{model_id}/model.glb",
                      file_type="glb", user_id=None, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()
    yield model_id
    import shutil
    shutil.rmtree(model_dir, ignore_errors=True)


def test_slice_preserves_material_properties(client, textured_model_on_disk):
    """A model with previously-edited material properties must keep them
    after a slice, not reset to defaults."""
    model_id = textured_model_on_disk
    resp = client.post("/slice_model", json={
        "model_id": model_id,
        "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}],
    })
    body = resp.get_json()
    assert resp.status_code == 200 and body["success"], body

    glb_path = os.path.join(app.config["CONVERTED_FOLDER"], model_id, "model.glb")
    gltf = GLTF2().load(glb_path)
    assert gltf.materials, "sliced GLB lost its materials entirely"
    pbr = gltf.materials[0].pbrMetallicRoughness
    assert pbr.baseColorFactor == pytest.approx([0.2, 0.4, 0.6, 1.0], abs=0.01)
    assert pbr.metallicFactor == pytest.approx(0.3, abs=0.01)
    assert pbr.roughnessFactor == pytest.approx(0.7, abs=0.01)
    # finalize_glb now runs post-slice too, so doubleSided is asserted defensively.
    assert gltf.materials[0].doubleSided is True

    # The face mask used to be tried first for any UV mesh, and it drops
    # (rather than clips) any triangle straddling the cut plane whole — on
    # this coarse box that silently reduced the whole half-box down to its
    # flat 2-triangle end cap. Confirm we get a real half-box, not that.
    scene = trimesh.load(glb_path, force="scene")
    mesh = trimesh.util.concatenate(list(scene.geometry.values()))
    assert len(mesh.vertices) > 4, "sliced model is missing geometry, not just the flat cut face"


def test_slice_textured_box_keeps_complete_geometry():
    """Direct unit-level regression test for the face-mask completeness bug:
    slicing a coarse UV-textured box must return a proper half-box (the walls
    clipped at the cut plane), not just its flat end cap."""
    box = trimesh.creation.box(extents=(0.2, 0.2, 0.2))
    uv = np.random.rand(len(box.vertices), 2)
    box.visual = trimesh.visual.TextureVisuals(
        uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorFactor=[0.2, 0.4, 0.6, 1.0])
    )
    result = ms._slice_single_mesh(box, np.array([0., 0., 0.]), np.array([1., 0., 0.]))
    assert result is not None
    assert len(result.vertices) > 4 and len(result.faces) > 2, (
        f"got only {len(result.vertices)} verts / {len(result.faces)} faces — "
        "looks like just the flat cap, not a full half-box"
    )
    assert getattr(result.visual, 'uv', None) is not None
    assert getattr(result.visual, 'material', None) is not None


def test_slice_caps_plain_mesh():
    """Regression test for the missing-scipy bug: a plain (untextured) mesh
    slice must come back capped/watertight, not an open hollow shell."""
    box = trimesh.creation.box(extents=(1, 1, 1))
    result = ms._slice_single_mesh(box, np.array([0., 0., 0.]), np.array([1., 0., 0.]))
    assert result is not None
    assert result.is_watertight, "plain-mesh slice should be capped (closed), not an open shell"


def test_slice_fallback_preserves_uv_and_material():
    """A mesh where the face mask can never keep a whole face (every
    triangle straddles the cut) must fall through to slice_plane without
    losing UV/material — _reattach_material used to clobber a UV that
    slice_plane(cap=False) had already correctly interpolated."""
    vertices = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
    faces = np.array([[0, 1, 2]])
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    uv = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    material = trimesh.visual.material.SimpleMaterial(diffuse=(200, 50, 50, 255))
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)

    # Sanity: confirm this geometry really can't be handled by the face mask.
    assert ms._facemask_slice(mesh, np.array([0., 0., 0.]), np.array([1., 0., 0.])) is None

    result = ms._slice_single_mesh(mesh, np.array([0., 0., 0.]), np.array([1., 0., 0.]))
    assert result is not None
    assert getattr(result.visual, 'uv', None) is not None
    assert getattr(result.visual, 'material', None) is not None
