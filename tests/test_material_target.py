"""Per-material targeting in glb_modifier (UIA-11)."""
import pytest

pytest.importorskip("pygltflib")
from pygltflib import GLTF2, Material, PbrMetallicRoughness

from glb_modifier import apply_material_modifications, modify_glb


def _gltf_with_three_materials():
    gltf = GLTF2()
    gltf.materials = [
        Material(pbrMetallicRoughness=PbrMetallicRoughness(baseColorFactor=c, metallicFactor=0.0))
        for c in ([1, 0, 0, 1], [0, 1, 0, 1], [0, 0, 1, 1])
    ]
    return gltf


def test_no_target_applies_to_all_materials():
    gltf = apply_material_modifications(_gltf_with_three_materials(), {"metalness": 0.9})
    assert [m.pbrMetallicRoughness.metallicFactor for m in gltf.materials] == [0.9, 0.9, 0.9]


def test_target_limits_edit_to_one_material():
    gltf = apply_material_modifications(
        _gltf_with_three_materials(), {"target": 1, "color": [1, 1, 0], "opacity": 1.0, "metalness": 0.5}
    )
    assert gltf.materials[1].pbrMetallicRoughness.baseColorFactor == [1, 1, 0, 1.0]
    assert gltf.materials[1].pbrMetallicRoughness.metallicFactor == 0.5
    assert gltf.materials[0].pbrMetallicRoughness.baseColorFactor == [1, 0, 0, 1]
    assert gltf.materials[2].pbrMetallicRoughness.metallicFactor == 0.0


def test_modify_glb_material_targets_list(tmp_path):
    src, dst = tmp_path / "in.glb", tmp_path / "out.glb"
    _gltf_with_three_materials().save(str(src))
    modify_glb(str(src), str(dst), {"material_targets": [
        {"target": 0, "metalness": 0.2},
        {"target": 2, "metalness": 0.8},
        {"metalness": 1.0},  # no target -> ignored in the list form
    ]})
    out = GLTF2().load(str(dst))
    assert [round(m.pbrMetallicRoughness.metallicFactor, 2) for m in out.materials] == [0.2, 0.0, 0.8]
