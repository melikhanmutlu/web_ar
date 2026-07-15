"""Regression coverage for FBX texture recovery when FBX2glTF omits images."""

from pathlib import Path

import trimesh
from PIL import Image
from pygltflib import GLTF2

from converters.fbx_converter import FBXConverter


def test_recovers_probe_texture_when_fbx2gltf_has_no_images(tmp_path):
    """A texture-less GLB must still use the probe's extracted source map.

    FBX2glTF occasionally emits a material but no ``images`` entry. The old
    early return made that state permanently untextured, even though the FBX
    probe had already found the texture next to the uploaded source.
    """
    glb_path = tmp_path / "model.glb"
    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[1.0, 1.0, 1.0, 1.0]
        )
    )
    gltf = GLTF2().load_from_bytes(trimesh.Scene([mesh]).export(file_type="glb"))
    gltf.materials[0].name = "VehiclePaint"
    gltf.save(glb_path)
    assert not (GLTF2().load(glb_path).images or [])

    texture_path = tmp_path / "paint.png"
    Image.new("RGB", (2, 2), (30, 120, 220)).save(texture_path)
    fbx_path = tmp_path / "vehicle.fbx"
    fbx_path.write_bytes(b"placeholder")

    converter = FBXConverter.__new__(FBXConverter)
    converter.log_operation = lambda *args, **kwargs: None
    # The names differ in the same way they often do between Assimp and
    # FBX2glTF, so this also verifies namespace-tolerant matching.
    converter._fbx_material_textures = {"Material::VehiclePaint": "paint.png"}

    converter._embed_external_textures(str(glb_path), str(fbx_path))

    repaired = GLTF2().load(glb_path)
    pbr = repaired.materials[0].pbrMetallicRoughness
    assert pbr.baseColorTexture is not None
    texture = repaired.textures[pbr.baseColorTexture.index]
    image = repaired.images[texture.source]
    assert image.uri and image.uri.startswith("data:image/png;base64,")
