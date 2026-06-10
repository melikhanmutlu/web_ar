"""Regression tests for the FBX pipeline's alpha/transparency handling.

Covers the texture-visibility bugs in the FBX → GLB path:
- bogus FBX TransparencyFactor arriving as baseColorFactor alpha < 1
- cutout (foliage) textures needing MASK instead of OPAQUE
- solid-color application tinting/darkening textured materials
- "Save & Apply" clobbering MASK cutouts back to OPAQUE
"""

import io

import numpy as np
import pytest
import trimesh
from PIL import Image as PILImage
from pygltflib import GLTF2

from converters.fbx_converter import _analyze_alpha_channel, fix_material_transparency
from glb_modifier import apply_material_modifications


def _png_bytes(alpha_pattern):
    img = PILImage.new("RGBA", (8, 8), (120, 200, 80, 255))
    px = img.load()
    for x, y, a in alpha_pattern:
        px[x, y] = (120, 200, 80, a)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


OPAQUE_PNG = _png_bytes([])
CUTOUT_PNG = _png_bytes([(0, 0, 0), (1, 1, 0), (2, 2, 0)])
GRADUAL_PNG = _png_bytes([(x, y, 128) for x in range(8) for y in range(4)])


def _textured_gltf(tex_png, factor_alpha=1.0, alpha_mode=None, name="mat"):
    mesh = trimesh.creation.box()
    uv = np.zeros((len(mesh.vertices), 2))
    material = trimesh.visual.material.PBRMaterial(
        baseColorTexture=PILImage.open(io.BytesIO(tex_png))
    )
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    gltf = GLTF2().load_from_bytes(trimesh.Scene([mesh]).export(file_type="glb"))
    mat = gltf.materials[0]
    mat.name = name
    factor = mat.pbrMetallicRoughness.baseColorFactor or [1, 1, 1, 1]
    mat.pbrMetallicRoughness.baseColorFactor = [factor[0], factor[1], factor[2], factor_alpha]
    mat.alphaMode = alpha_mode
    return gltf


def _plain_gltf():
    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(baseColorFactor=[1.0, 1.0, 1.0, 1.0])
    )
    return GLTF2().load_from_bytes(trimesh.Scene([mesh]).export(file_type="glb"))


class TestAnalyzeAlphaChannel:
    def test_opaque_image_has_no_transparency(self):
        assert _analyze_alpha_channel(OPAQUE_PNG) == (False, False)

    def test_cutout_image_is_binary(self):
        assert _analyze_alpha_channel(CUTOUT_PNG) == (True, True)

    def test_gradual_alpha_is_not_binary(self):
        has_alpha, mostly_binary = _analyze_alpha_channel(GRADUAL_PNG)
        assert has_alpha and not mostly_binary


class TestFixMaterialTransparency:
    def test_cutout_texture_with_bogus_factor_alpha(self):
        """The invisible-foliage bug: cutout texture + factor alpha 0."""
        gltf = _textured_gltf(CUTOUT_PNG, factor_alpha=0.0, alpha_mode="OPAQUE")
        assert fix_material_transparency(gltf) is True
        mat = gltf.materials[0]
        assert mat.alphaMode == "MASK"
        assert mat.alphaCutoff == 0.5
        assert mat.doubleSided is True
        assert mat.pbrMetallicRoughness.baseColorFactor[3] == 1.0

    def test_bogus_factor_alpha_without_texture_alpha_is_clamped(self):
        """FBX opacity import quirk: clamp to opaque instead of going BLEND."""
        gltf = _textured_gltf(OPAQUE_PNG, factor_alpha=0.0, alpha_mode="OPAQUE")
        fix_material_transparency(gltf)
        mat = gltf.materials[0]
        assert (mat.alphaMode or "OPAQUE") == "OPAQUE"
        assert mat.pbrMetallicRoughness.baseColorFactor[3] == 1.0

    def test_gradual_alpha_texture_gets_blend(self):
        gltf = _textured_gltf(GRADUAL_PNG)
        fix_material_transparency(gltf)
        assert gltf.materials[0].alphaMode == "BLEND"

    def test_deliberate_blend_glass_is_untouched(self):
        gltf = _textured_gltf(OPAQUE_PNG, factor_alpha=0.5, alpha_mode="BLEND")
        fix_material_transparency(gltf)
        mat = gltf.materials[0]
        assert mat.alphaMode == "BLEND"
        assert mat.pbrMetallicRoughness.baseColorFactor[3] == pytest.approx(0.5)

    def test_invisible_blend_material_is_rescued(self):
        gltf = _textured_gltf(OPAQUE_PNG, factor_alpha=0.01, alpha_mode="BLEND")
        fix_material_transparency(gltf)
        mat = gltf.materials[0]
        assert mat.alphaMode == "OPAQUE"
        assert mat.pbrMetallicRoughness.baseColorFactor[3] == 1.0

    def test_idempotent(self):
        gltf = _textured_gltf(CUTOUT_PNG, factor_alpha=0.0, alpha_mode="OPAQUE")
        fix_material_transparency(gltf)
        assert fix_material_transparency(gltf) is False


class TestApplyMaterialModifications:
    def test_color_does_not_tint_textured_material(self):
        gltf = _textured_gltf(OPAQUE_PNG, name="body")
        original = list(gltf.materials[0].pbrMetallicRoughness.baseColorFactor)
        apply_material_modifications(gltf, {"color": "#FF0000", "opacity": 1.0})
        assert list(gltf.materials[0].pbrMetallicRoughness.baseColorFactor) == original

    def test_color_applies_to_untextured_material(self):
        gltf = _plain_gltf()
        apply_material_modifications(gltf, {"color": "#FF0000", "opacity": 1.0})
        factor = gltf.materials[0].pbrMetallicRoughness.baseColorFactor
        assert factor[0] == 1.0 and factor[1] == 0.0 and factor[2] == 0.0

    def test_mask_cutout_survives_save_with_default_opacity(self):
        """'Save & Apply' used to flip MASK foliage back to OPAQUE."""
        gltf = _textured_gltf(CUTOUT_PNG, alpha_mode="MASK", name="leaves")
        apply_material_modifications(
            gltf, {"color": "#FF0000", "metalness": 0.1, "roughness": 0.9, "opacity": 1.0}
        )
        assert gltf.materials[0].alphaMode == "MASK"

    def test_opacity_on_textured_material_keeps_texture_colors(self):
        gltf = _textured_gltf(OPAQUE_PNG, name="body")
        rgb_before = list(gltf.materials[0].pbrMetallicRoughness.baseColorFactor)[:3]
        apply_material_modifications(gltf, {"color": "#FF0000", "opacity": 0.5})
        mat = gltf.materials[0]
        assert mat.alphaMode == "BLEND"
        assert mat.pbrMetallicRoughness.baseColorFactor[3] == pytest.approx(0.5)
        assert list(mat.pbrMetallicRoughness.baseColorFactor)[:3] == rgb_before

    def test_explicit_blend_returns_to_opaque_at_full_opacity(self):
        gltf = _plain_gltf()
        gltf.materials[0].alphaMode = "BLEND"
        apply_material_modifications(gltf, {"color": "#00FF00", "opacity": 1.0})
        assert gltf.materials[0].alphaMode == "OPAQUE"
