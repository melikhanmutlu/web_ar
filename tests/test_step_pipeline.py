"""STEP assemblies through the whole upload pipeline and the slicer.

The converter makes an assembly layer-ready; these tests make sure nothing
downstream (pivot centring, quality pass, compression, persistent slicing)
merges the parts back together or drops the layer list.
"""

import os
from pathlib import Path

import pytest
import trimesh
from pygltflib import GLTF2

from converters import glb_optimizer
from converters.layers import EXTRAS_KEY
from mesh_slicer import get_mesh_bounds, slice_mesh
from services.asset_quality import AssetQualityService
from services.conversion import ConversionService

UNICODE = os.path.join(os.path.dirname(__file__), "fixtures", "step", "assembly_unicode.step")
PART_NAMES = ["Gövde", "Şaft", "Kapak ü", "Ünite-Ç", "Cıvata", "Cıvata", "Cıvata", "Cıvata"]
LAYER_NAMES = ["Gövde", "Şaft", "Kapak ü", "Ünite-Ç", "Cıvata"]
LOCAL_GLTF_TRANSFORM = Path(__file__).resolve().parent.parent / "node_modules" / ".bin" / "gltf-transform"


def _run_pipeline(tmp_path, compression):
    output = tmp_path / "model.glb"
    payload = {
        "file_extension": ".step",
        "temp_file_path": UNICODE,
        "original_filename": "assembly_unicode.step",
        "temp_dir": str(tmp_path),
        "compression": compression,
    }
    result = ConversionService(AssetQualityService()).convert(payload, str(output))
    return output, result


def _layer_names(glb):
    gltf = GLTF2.load(str(glb))
    return [layer["name"] for layer in (gltf.scenes[gltf.scene or 0].extras or {}).get(EXTRAS_KEY, [])]


def test_pipeline_keeps_parts_layers_and_centres_the_assembly(tmp_path):
    output, result = _run_pipeline(tmp_path, "none")

    gltf = GLTF2.load(str(output))
    assert [n.name for n in gltf.nodes if n.mesh is not None] == PART_NAMES
    assert _layer_names(output) == LAYER_NAMES
    assert result["dimensions_cm"] == pytest.approx({"x": 3.6, "y": 5.8, "z": 2.0, "max": 5.8}, abs=0.01)
    # The slicer's server-side bounds must match the viewer's centred model.
    centre = get_mesh_bounds(str(output))["center"]
    assert [centre["x"], centre["y"], centre["z"]] == pytest.approx([0, 0, 0], abs=1e-6)


@pytest.mark.skipif(not LOCAL_GLTF_TRANSFORM.exists(), reason="gltf-transform (npm install) not available")
def test_draco_compression_keeps_every_part_and_material(tmp_path, monkeypatch):
    monkeypatch.setattr(glb_optimizer, "_resolve_gltf_transform", lambda: [str(LOCAL_GLTF_TRANSFORM)])
    output, _ = _run_pipeline(tmp_path, "draco")

    gltf = GLTF2.load(str(output))
    assert "KHR_draco_mesh_compression" in (gltf.extensionsUsed or [])
    assert [n.name for n in gltf.nodes if n.mesh is not None] == PART_NAMES
    assert sorted(m.name for m in gltf.materials) == sorted(LAYER_NAMES)
    assert _layer_names(output) == LAYER_NAMES


def test_persistent_slice_keeps_surviving_layers_and_caps_the_cut(tmp_path):
    source, _ = _run_pipeline(tmp_path, "none")
    sliced = tmp_path / "sliced.glb"

    # The assembly spans x = -0.018..0.018 m; keeping x > -0.008 m cuts two of
    # the four bolts away entirely and slices through the other parts.
    assert slice_mesh(str(source), str(sliced), [-0.008, 0, 0], [1, 0, 0], "positive")

    gltf = GLTF2.load(str(sliced))
    assert sum(1 for n in gltf.nodes if n.mesh is not None) == 6
    assert _layer_names(sliced) == LAYER_NAMES
    # every cut solid is closed again: the section faces are filled
    scene = trimesh.load(str(sliced), force="scene")
    assert all(geometry.is_watertight for geometry in scene.geometry.values())
