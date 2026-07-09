"""Rotation baking (glb_modifier.apply_transform_modifications) must match
model-viewer's live `orientation` preview: intrinsic YXZ, right-handed.

The old euler_to_rotation_matrix used inverted sin signs ("clockwise"),
which is the exact INVERSE of model-viewer's convention — every saved
rotation came out mirrored relative to what the preview showed. It also
never rotated NORMAL vectors, so baked-rotated models kept pre-rotation
lighting.
"""

import os
import tempfile

import numpy as np
import pytest
import trimesh
from scipy.spatial.transform import Rotation as R

from glb_modifier import modify_glb


def _marker_mesh():
    """Long bar along +X with an asymmetric bump at the +X end."""
    bar = trimesh.creation.box(extents=(2.0, 0.2, 0.2))
    bump = trimesh.creation.box(extents=(0.2, 0.6, 0.2))
    bump.apply_translation([0.9, 0.3, 0])
    return trimesh.util.concatenate([bar, bump])


def _bake(mesh, rotation):
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in.glb")
        dst = os.path.join(d, "out.glb")
        trimesh.Scene(mesh).export(src)
        assert modify_glb(src, dst, {"transform": {"rotation": rotation}})
        return trimesh.load(dst, force="mesh")


def test_positive_yaw_matches_model_viewer_direction():
    """model-viewer +90° yaw (about +Y, right-handed) maps +X to -Z. The bump
    that started at +X must end up on the NEGATIVE Z side — the old matrix
    sent it to +Z (mirrored)."""
    out = _bake(_marker_mesh(), {"x": 0, "y": 90, "z": 0})
    bump_verts = out.vertices[out.vertices[:, 1] > 0.25]
    assert bump_verts[:, 2].mean() < -0.5, (
        f"bump ended at Z={bump_verts[:, 2].mean():.2f} — rotation direction is "
        "mirrored relative to the model-viewer preview"
    )


def test_combined_rotation_matches_intrinsic_yxz():
    """Baked vertices must equal scipy's intrinsic-YXZ rotation about the
    model center for a combined multi-axis rotation."""
    mesh = _marker_mesh()
    rot = {"x": 30.0, "y": 45.0, "z": 15.0}
    original = mesh.vertices.copy()
    # Pivot used by apply_transform_modifications: model center (bbox center
    # per calculate_model_center — verify against both bbox and mean; the
    # implementation uses accessor min/max midpoint = bbox center).
    center = (original.min(axis=0) + original.max(axis=0)) / 2.0

    out = _bake(mesh, rot)
    expected = R.from_euler(
        "YXZ", [np.radians(rot["y"]), np.radians(rot["x"]), np.radians(rot["z"])]
    ).apply(original - center) + center

    # trimesh may reorder vertices on load — compare as point sets via
    # nearest-neighbour distances.
    from scipy.spatial import cKDTree
    d, _ = cKDTree(expected).query(out.vertices)
    assert float(d.max()) < 1e-4, f"max vertex deviation {d.max():.6f}"


def test_normals_are_rotated_with_geometry():
    """After a 90° yaw the +X face's stored NORMAL must point to -Z and stay
    unit length. The old code baked rotated positions but left the NORMAL
    accessor untouched, so lighting stayed pre-rotation. Read the accessor
    bytes directly — trimesh would silently recompute normals on load."""
    import struct
    from pygltflib import GLTF2

    def read_normals(path):
        gltf = GLTF2().load(path)
        prim = gltf.meshes[0].primitives[0]
        assert prim.attributes.NORMAL is not None
        acc = gltf.accessors[prim.attributes.NORMAL]
        bv = gltf.bufferViews[acc.bufferView]
        blob = gltf.binary_blob()
        off = (bv.byteOffset or 0) + (acc.byteOffset or 0)
        stride = bv.byteStride or 12
        return np.array([
            struct.unpack_from('fff', blob, off + i * stride) for i in range(acc.count)
        ])

    box = trimesh.creation.box(extents=(1.0, 1.0, 1.0))
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "in.glb")
        dst = os.path.join(d, "out.glb")
        trimesh.Scene(box).export(src, include_normals=True)
        before = read_normals(src)
        assert modify_glb(src, dst, {"transform": {"rotation": {"x": 0, "y": 90, "z": 0}}})
        after = read_normals(dst)

    assert np.allclose(np.linalg.norm(after, axis=1), 1.0, atol=1e-3)
    # modify_glb edits accessors in place, so vertex order is preserved:
    # every stored normal must equal R @ original (R = +90° yaw, intrinsic YXZ).
    expected = before @ R.from_euler("YXZ", [np.radians(90), 0, 0]).as_matrix().T
    assert np.allclose(after, expected, atol=1e-4), (
        "NORMAL accessor does not match the rotation applied to POSITION"
    )
    # Sanity: the rotation actually changed the data (guards against a
    # trivially-passing identity comparison).
    assert not np.allclose(after, before, atol=1e-4)


# ---------------------------------------------------------------------------
# Scale baking (same vertex loop) — shared accessors and atomicity
# ---------------------------------------------------------------------------


def _extent_x(gltf):
    import struct
    blob = gltf.binary_blob()
    acc = gltf.accessors[gltf.meshes[0].primitives[0].attributes.POSITION]
    bv = gltf.bufferViews[acc.bufferView]
    off = (bv.byteOffset or 0) + (acc.byteOffset or 0)
    stride = bv.byteStride or 12
    xs = [struct.unpack_from("fff", blob, off + i * stride)[0] for i in range(acc.count)]
    return max(xs) - min(xs)


def test_scale_applies_once_to_shared_position_accessor():
    """Primitives commonly share one POSITION accessor (per-material splits).
    The old loop transformed per primitive, so shared vertex data was scaled
    once per referencing primitive — 0.1 became 0.01 for shared parts while
    unshared parts got 0.1, visibly breaking the model."""
    import copy
    from pygltflib import GLTF2
    from glb_modifier import apply_transform_modifications

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "shared.glb")
        trimesh.Scene([trimesh.creation.box(extents=(2, 2, 2))]).export(path)
        gltf = GLTF2().load(path)
        gltf.meshes[0].primitives.append(copy.deepcopy(gltf.meshes[0].primitives[0]))

        gltf = apply_transform_modifications(gltf, {"scale": 0.1})
        assert _extent_x(gltf) == pytest.approx(0.2, rel=1e-4), (
            "shared POSITION accessor was transformed once per primitive"
        )


def test_scale_updates_position_min_max():
    """Viewers frame/place the model from POSITION min/max — the bake must
    keep them in sync with the transformed geometry."""
    from pygltflib import GLTF2
    from glb_modifier import apply_transform_modifications

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "bounds.glb")
        trimesh.Scene([trimesh.creation.box(extents=(2, 2, 2))]).export(path)
        gltf = GLTF2().load(path)
        gltf = apply_transform_modifications(gltf, {"scale": 0.1})
        acc = gltf.accessors[gltf.meshes[0].primitives[0].attributes.POSITION]
        assert acc.min == pytest.approx([-0.1, -0.1, -0.1], abs=1e-6)
        assert acc.max == pytest.approx([0.1, 0.1, 0.1], abs=1e-6)


def test_transform_is_all_or_nothing_on_unreadable_accessor():
    """One unreadable POSITION accessor (Draco/sparse: bufferView=None) used
    to abort the loop midway AFTER earlier meshes were already written —
    saving a model with some parts scaled and others not. The bake must
    fail as a whole, leaving every buffer untouched."""
    from pygltflib import GLTF2
    from glb_modifier import apply_transform_modifications

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "twomesh.glb")
        b1 = trimesh.creation.box(extents=(2, 2, 2))
        b2 = trimesh.creation.box(extents=(2, 2, 2))
        b2.apply_translation([5, 0, 0])
        trimesh.Scene({"a": b1, "b": b2}).export(path)
        gltf = GLTF2().load(path)
        gltf.accessors[gltf.meshes[1].primitives[0].attributes.POSITION].bufferView = None

        with pytest.raises(ValueError):
            apply_transform_modifications(gltf, {"scale": 0.1})
        assert _extent_x(gltf) == pytest.approx(2.0, rel=1e-4), (
            "a failed bake must not leave earlier meshes already transformed"
        )


# ---------------------------------------------------------------------------
# Node-positioned (multi-part) models — the transform must apply in WORLD
# space. Baking into local vertices while node offsets stayed put shrank
# each part in place and tore the model apart.
# ---------------------------------------------------------------------------


def _noded_two_part_glb(path):
    """Two identical boxes positioned by a node translation (trimesh dedupes
    identical geometry, so they also SHARE vertex accessors)."""
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=(2, 2, 2)), node_name="a", geom_name="ga")
    scene.add_geometry(
        trimesh.creation.box(extents=(2, 2, 2)), node_name="b", geom_name="gb",
        transform=trimesh.transformations.translation_matrix([5, 0, 0]),
    )
    scene.export(path)


def _world_extents(gltf, path):
    gltf.save(path)
    merged = trimesh.load(path, force="scene").dump(concatenate=True)
    return merged.bounds[1] - merged.bounds[0]


def test_scale_shrinks_node_positioned_parts_together():
    from pygltflib import GLTF2
    from glb_modifier import apply_transform_modifications

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "noded.glb")
        _noded_two_part_glb(path)
        gltf = GLTF2().load(path)
        gltf = apply_transform_modifications(gltf, {"scale": 0.1})
        ext = _world_extents(gltf, os.path.join(d, "out.glb"))
        # Node offset must scale with the parts: 7 -> 0.7 world span, not 5.2.
        assert ext == pytest.approx([0.7, 0.2, 0.2], abs=1e-3)


def test_rotation_turns_node_positioned_model_as_one_piece():
    from pygltflib import GLTF2
    from glb_modifier import apply_transform_modifications

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "noded.glb")
        _noded_two_part_glb(path)
        gltf = GLTF2().load(path)
        gltf = apply_transform_modifications(gltf, {"rotation": {"x": 0, "y": 90, "z": 0}})
        ext = _world_extents(gltf, os.path.join(d, "out.glb"))
        # The whole model turns about the world center: x-span becomes z-span.
        assert ext == pytest.approx([2.0, 2.0, 7.0], abs=1e-3)


def test_scale_on_mesh_instanced_by_two_nodes():
    """One mesh referenced by two nodes at different positions: vertex data
    can't satisfy both — the bake must give the second node its own copy."""
    from pygltflib import GLTF2, Node
    from glb_modifier import apply_transform_modifications

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "inst.glb")
        trimesh.Scene([trimesh.creation.box(extents=(2, 2, 2))]).export(path)
        gltf = GLTF2().load(path)
        mesh_node = next(i for i, n in enumerate(gltf.nodes) if n.mesh is not None)
        gltf.nodes.append(Node(mesh=gltf.nodes[mesh_node].mesh, translation=[5, 0, 0]))
        root = next(i for i, n in enumerate(gltf.nodes) if n.children)
        gltf.nodes[root].children.append(len(gltf.nodes) - 1)

        gltf = apply_transform_modifications(gltf, {"scale": 0.1})
        ext = _world_extents(gltf, os.path.join(d, "out.glb"))
        assert ext == pytest.approx([0.7, 0.2, 0.2], abs=1e-3)


def test_scale_under_rotated_node_is_exact():
    """A part whose node carries a rotation: the local-space change is a full
    conjugation (W⁻¹·M·W), not just a scaled offset."""
    from pygltflib import GLTF2
    from glb_modifier import apply_transform_modifications
    from scipy.spatial import cKDTree

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "rotnode.glb")
        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=(2, 1, 1)), node_name="a", geom_name="ga")
        t = trimesh.transformations.rotation_matrix(np.radians(90), [0, 1, 0])
        t[:3, 3] = [5, 0, 0]
        scene.add_geometry(trimesh.creation.box(extents=(2, 1, 1)), node_name="b", geom_name="gb", transform=t)
        scene.export(path)

        before = trimesh.load(path, force="scene").dump(concatenate=True)
        gltf = GLTF2().load(path)
        gltf = apply_transform_modifications(gltf, {"scale": 0.5})
        out = os.path.join(d, "out.glb")
        gltf.save(out)
        after = trimesh.load(out, force="scene").dump(concatenate=True)

        center = (before.bounds[0] + before.bounds[1]) / 2
        expected = center + 0.5 * (before.vertices - center)
        dist, _ = cKDTree(expected).query(after.vertices)
        assert float(dist.max()) < 1e-4
