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
