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


def _make_vertex_colored_glb(path, rgba=(200, 50, 50, 255), uniform=False):
    """Real per-vertex colours (R/G constant, B varies along x) as COLOR_0, no
    materials. `uniform=True` writes one flat colour, which the slicer treats
    as a material colour rather than per-vertex data."""
    box = trimesh.creation.box(extents=(1, 1, 1)).subdivide()
    vertex_colors = np.tile(rgba, (len(box.vertices), 1)).astype(np.uint8)
    if not uniform:
        vertex_colors[:, 2] = np.clip((box.vertices[:, 0] + 0.5) * 200, 0, 255).astype(np.uint8)
    box.visual = trimesh.visual.ColorVisuals(vertex_colors=vertex_colors)
    trimesh.Scene([box]).export(path, file_type="glb")


def _first_color0(gltf):
    """(first vertex color, material index) of the first COLOR_0 primitive."""
    import struct as _struct
    blob = gltf.binary_blob()
    for mesh in gltf.meshes:
        for prim in mesh.primitives:
            c = getattr(prim.attributes, "COLOR_0", None)
            if c is None:
                continue
            acc = gltf.accessors[c]
            bv = gltf.bufferViews[acc.bufferView]
            off = (bv.byteOffset or 0) + (acc.byteOffset or 0)
            n = 4 if acc.type == "VEC4" else 3
            if acc.componentType == 5121:  # UNSIGNED_BYTE
                return tuple(blob[off + i] for i in range(n)), prim.material
            if acc.componentType == 5126:  # FLOAT
                return _struct.unpack_from(f"<{n}f", blob, off), prim.material
    return None, None


def test_slice_preserves_vertex_color_without_double_tinting():
    """STL-sourced models carry color as vertex colors only (no material) —
    that's how they render correctly pre-slice. _inject_materials used to
    force-assign every colorless primitive a synthetic material promoted
    FROM that same vertex color, and since glTF multiplies COLOR_0 by
    baseColorFactor, the result was the color squared (crushed towards
    black) instead of preserved."""
    in_path = f"/tmp/test_slice_vc_in_{uuid.uuid4().hex}.glb"
    out_path = f"/tmp/test_slice_vc_out_{uuid.uuid4().hex}.glb"
    _make_vertex_colored_glb(in_path)
    try:
        result = ms.slice_mesh(in_path, out_path, [0, 0, 0], [1, 0, 0], keep_side="positive")
        assert result is True

        gltf = GLTF2().load(out_path)
        color, material = _first_color0(gltf)
        assert color is not None, "sliced GLB lost its COLOR_0 vertex colors"
        assert color[:2] == (200, 50)
        assert material is None, (
            "primitive has both COLOR_0 and the material promoted from that "
            "same color — glTF will multiply them, crushing it towards black"
        )
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                os.remove(p)


def test_slice_keeps_color_through_real_upload_pipeline():
    """The bug as actually deployed: the upload pipeline runs finalize_glb,
    which assigns a neutral WHITE material to the STL converter's
    vertex-colored GLB. trimesh loads that combo as TextureVisuals with the
    colors hidden in vertex_attributes['color'] (NOT a ColorVisuals), so the
    slicer used to take the plain geometric path and drop COLOR_0 entirely —
    every sliced STL model came back gray. Colors must survive the full
    convert → finalize → slice → finalize → slice-again flow."""
    from converters.glb_quality import finalize_glb

    path = f"/tmp/test_slice_pipeline_{uuid.uuid4().hex}.glb"
    _make_vertex_colored_glb(path)
    try:
        finalize_glb(path)  # what upload does before the model reaches disk
        color, material = _first_color0(GLTF2().load(path))
        assert color[:2] == (200, 50) and material is not None

        # First slice (the /slice_model flow: slice + finalize).
        assert ms.slice_mesh(path, path, [0, 0, 0], [1, 0, 0], "positive") is True
        finalize_glb(path)
        gltf = GLTF2().load(path)
        color, material = _first_color0(gltf)
        assert color is not None, "slice dropped COLOR_0 — model renders gray"
        assert color[:2] == (200, 50)
        if material is not None:
            base = gltf.materials[material].pbrMetallicRoughness.baseColorFactor
            assert base == pytest.approx([1.0, 1.0, 1.0, 1.0]), (
                "linked material must stay neutral white so it doesn't tint COLOR_0"
            )

        # Slicing the already-sliced model again must not degrade either.
        assert ms.slice_mesh(path, path, [0, 0, 0], [0, 1, 0], "positive") is True
        finalize_glb(path)
        color, _ = _first_color0(GLTF2().load(path))
        assert color is not None and color[:2] == (200, 50)
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_slice_keeps_user_edited_material_multiplying_color0():
    """A model whose material color was edited in the viewer (baseColorFactor
    set while COLOR_0 remains) rendered as material × COLOR_0 before the
    slice — the same material must stay linked after it."""
    from converters.glb_quality import finalize_glb

    path = f"/tmp/test_slice_edited_{uuid.uuid4().hex}.glb"
    _make_vertex_colored_glb(path)
    try:
        finalize_glb(path)
        gltf = GLTF2().load(path)
        gltf.materials[0].pbrMetallicRoughness.baseColorFactor = [0.1, 0.2, 0.9, 1.0]
        gltf.save(path)

        assert ms.slice_mesh(path, path, [0, 0, 0], [1, 0, 0], "positive") is True
        gltf = GLTF2().load(path)
        color, material = _first_color0(gltf)
        assert color is not None and color[:2] == (200, 50)
        assert material is not None, "user-edited material lost its primitive link"
        base = gltf.materials[material].pbrMetallicRoughness.baseColorFactor
        # trimesh round-trips the factor through 8-bit, so allow quantization.
        assert base == pytest.approx([0.1, 0.2, 0.9, 1.0], abs=0.01)
    finally:
        if os.path.exists(path):
            os.remove(path)


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


# ---- STL slicing: flat colour must clip, not face-mask (P3D-03) ----------

def _box_slice_extent_x(path, origin_x=0.02):
    out = f"/tmp/test_slice_stl_out_{uuid.uuid4().hex}.glb"
    try:
        assert ms.slice_mesh(path, out, [origin_x, 0, 0], [1, 0, 0], "positive") is True
        scene = trimesh.load(out, force="scene")
        return float(scene.extents[0]), GLTF2().load(out)
    finally:
        if os.path.exists(out):
            os.remove(out)


def _convert_box_stl(tmp_path):
    from converters.stl_converter import STLConverter

    stl = tmp_path / "box.stl"
    trimesh.creation.box(extents=(10, 2, 5)).export(str(stl))
    out = tmp_path / "box.glb"
    conv = STLConverter()
    conv.set_source_unit("cm")
    assert conv.convert(str(stl), str(out)) is True
    return out


def test_stl_converter_stores_colour_as_material_not_vertex_colours(tmp_path):
    out = _convert_box_stl(tmp_path)
    gltf = GLTF2().load(str(out))
    prim = gltf.meshes[0].primitives[0]
    assert getattr(prim.attributes, "COLOR_0", None) is None
    assert getattr(prim.attributes, "TEXCOORD_0", None) is None
    assert gltf.materials[prim.material].pbrMetallicRoughness.baseColorFactor[0] < 1.0


def test_stl_box_sliced_keeps_thickness_new_conversion(tmp_path):
    """10x2x5 cm box cut at x=2 cm keeps the 3 cm slab (used to leave a
    0-thickness face)."""
    out = _convert_box_stl(tmp_path)
    # centred box spans x in [-0.05, 0.05] m; cut at x=+0.02 keeps [0.02, 0.05]
    extent, _ = _box_slice_extent_x(str(out))
    assert extent == pytest.approx(0.03, abs=1e-4)


def _uniform_grey_box():
    box = trimesh.creation.box(extents=(0.10, 0.02, 0.05))
    box.visual = trimesh.visual.ColorVisuals(
        vertex_colors=np.tile([154, 154, 154, 255], (len(box.vertices), 1)).astype(np.uint8))
    return box


def test_already_converted_stl_with_uniform_color0_clips():
    """Models converted before the fix carry one uniform grey COLOR_0."""
    path = f"/tmp/test_slice_old_stl_{uuid.uuid4().hex}.glb"
    trimesh.Scene([_uniform_grey_box()]).export(path, file_type="glb")
    try:
        extent, gltf = _box_slice_extent_x(path)
        assert extent == pytest.approx(0.03, abs=1e-4)
        prim = gltf.meshes[0].primitives[0]
        assert getattr(prim.attributes, "COLOR_0", None) is None  # flattened into the material
        base = gltf.materials[prim.material].pbrMetallicRoughness.baseColorFactor
        assert base[0] == pytest.approx(154 / 255, abs=0.01)
    finally:
        os.remove(path)


def test_uniform_color_slice_has_section_cap():
    flat = ms._flatten_uniform_color(_uniform_grey_box())
    result = ms._slice_single_mesh(flat, np.array([0.02, 0, 0]), np.array([1.0, 0, 0]))
    assert result.is_watertight


def test_real_vertex_colors_clip_and_interpolate_at_the_cut():
    box = trimesh.creation.box(extents=(1, 1, 1)).subdivide()
    colors = np.zeros((len(box.vertices), 4), dtype=np.uint8)
    colors[:, 0] = np.clip((box.vertices[:, 0] + 0.5) * 255, 0, 255).astype(np.uint8)
    colors[:, 3] = 255
    box.visual = trimesh.visual.ColorVisuals(vertex_colors=colors)
    result = ms._slice_single_mesh(box, np.array([0.2, 0, 0]), np.array([1.0, 0, 0]))
    assert result.bounds[0][0] == pytest.approx(0.2, abs=1e-6)  # clipped, not stepped
    vc = result.visual.vertex_colors
    cut = np.isclose(result.vertices[:, 0], 0.2, atol=1e-6)
    assert cut.any()
    assert vc[cut][:, 0].astype(int) == pytest.approx(int(0.7 * 255), abs=2)  # interpolated


def test_multi_material_glb_keeps_all_parts_when_sliced(tmp_path):
    scene = trimesh.Scene()
    for i, rgba in enumerate(([255, 0, 0, 255], [0, 0, 255, 255])):
        b = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
        b.apply_translation([0.3 * i, 0, 0])
        b.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            name=f"m{i}", baseColorFactor=rgba))
        scene.add_geometry(b, node_name=f"p{i}")
    src = tmp_path / "in.glb"
    scene.export(str(src))
    # trimesh leaves UV-less primitives unlinked; link them as a real file would.
    source = GLTF2().load(str(src))
    for i, gltf_mesh in enumerate(source.meshes):
        gltf_mesh.primitives[0].material = i
    source.save(str(src))
    out = tmp_path / "out.glb"
    assert ms.slice_mesh(str(src), str(out), [-1, 0, 0], [1, 0, 0], "positive") is True
    gltf = GLTF2().load(str(out))
    assert len(gltf.materials) == 2
    links = [p.material for m in gltf.meshes for p in m.primitives]
    assert None not in links and len(set(links)) == 2, "each part must stay linked to its own material"
    assert len(trimesh.load(str(out), force="scene").geometry) == 2


def test_slice_refuses_animated_models(tmp_path):
    from pygltflib import Animation

    src = tmp_path / "anim.glb"
    trimesh.creation.box().export(str(src))
    gltf = GLTF2().load(str(src))
    gltf.animations = [Animation(name="spin")]
    gltf.save(str(src))
    assert ms.slicing_unsupported_reason(str(src))
    result = ms.slice_mesh_multi(str(src), str(tmp_path / "o.glb"), [
        {"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}])
    assert result.get("unsupported")


def test_slice_route_refuses_animated_model_with_422(client):
    from pygltflib import Animation

    model_id = "test-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.box().export(glb_path)
    gltf = GLTF2().load(glb_path)
    gltf.animations = [Animation(name="spin")]
    gltf.save(glb_path)
    db.session.add(UserModel(id=model_id, filename=glb_path, file_type="glb", file_size=1, user_id=None))
    db.session.commit()
    before = os.path.getsize(glb_path)

    resp = client.post("/slice_model", json={"model_id": model_id, "planes": [
        {"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0], "keep_side": "positive"}]})
    assert resp.status_code == 422
    assert "animat" in resp.get_json()["error"].lower()
    assert os.path.getsize(glb_path) == before


def _gradient_box(subdivide=True):
    box = trimesh.creation.box(extents=(1, 1, 1))
    if subdivide:
        box = box.subdivide()
    colors = np.zeros((len(box.vertices), 4), dtype=np.uint8)
    colors[:, 1] = np.clip((box.vertices[:, 1] + 0.5) * 255, 0, 255).astype(np.uint8)
    colors[:, 3] = 255
    box.visual = trimesh.visual.ColorVisuals(vertex_colors=colors)
    return box


def test_real_vertex_color_slice_has_section_cap():
    result = ms._slice_single_mesh(_gradient_box(), np.array([0.2, 0, 0]), np.array([1.0, 0, 0]))
    assert result.bounds[0][0] == pytest.approx(0.2, abs=1e-6)
    # The cap has its own (flat-coloured) vertices; geometrically the shell is closed.
    geo = trimesh.Trimesh(result.vertices.copy(), result.faces.copy(), process=True)
    assert geo.is_watertight, "vertex-colour slice should be capped, not an open shell"
    vc = result.visual.vertex_colors
    assert len(vc) == len(result.vertices)


def test_vertex_color_cap_uses_mean_boundary_colour():
    result = ms._slice_single_mesh(_gradient_box(), np.array([0.2, 0, 0]), np.array([1.0, 0, 0]))
    on_plane = np.isclose(result.vertices[:, 0], 0.2, atol=1e-6)
    normals = trimesh.Trimesh(result.vertices, result.faces, process=False).face_normals
    cap_idx = [i for i, f in enumerate(result.faces)
               if on_plane[f].all() and normals[i][0] < -0.99]
    assert cap_idx
    cap_colors = result.visual.vertex_colors[np.unique(result.faces[cap_idx])]
    # gradient is symmetric around the cut -> mean green ~ 127, one flat colour
    assert np.all(cap_colors == cap_colors[0])
    assert int(cap_colors[0][1]) == pytest.approx(127, abs=3)
    # side walls keep their gradient (not flattened)
    assert result.visual.vertex_colors[:, 1].max() - result.visual.vertex_colors[:, 1].min() > 200
