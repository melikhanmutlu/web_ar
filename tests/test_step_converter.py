"""Tests for the STEP -> GLB converter (cascadio/OpenCASCADE backed).

Fixtures (STEP files cannot be generated with the libraries in this project):
* tests/fixtures/featuretype.step — the MIT-licensed sample part from the
  trimesh repository (a 5" x 2.5" machined plate, 1.375" thick along STEP Z).
* tests/fixtures/step/ — small assemblies from the academicar project:
  coloured / uncoloured 3-part assemblies, a plain box, and an assembly with
  ISO 10303-21 escaped (Turkish) part names and one bolt placed 4 times.
"""

import os
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from pygltflib import GLTF2

from converters.layers import EXTRAS_KEY
from converters.step_converter import STEPConverter

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "featuretype.step")
STEP_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "step")
COLORED = os.path.join(STEP_DIR, "assembly_colored.step")
SAME_COLOR = os.path.join(STEP_DIR, "assembly_same_color.step")
UNICODE = os.path.join(STEP_DIR, "assembly_unicode.step")
BOX = os.path.join(STEP_DIR, "box_plain.stp")

# Known real-world size of the fixture plate in meters, Y-up: STEP's Z
# (thickness, 1.375") becomes glTF Y so the plate lies flat — on the AR floor
# too — instead of standing on its edge.
EXPECTED_EXTENTS = np.array([0.127, 0.034925, 0.0635])


def _convert(source, tmp_path, **kwargs):
    converter = STEPConverter()
    output = tmp_path / "model.glb"
    return converter, output, converter.convert(str(source), str(output), **kwargs)


def _extents(glb):
    return np.ptp(trimesh.load(str(glb), force="scene").bounds, axis=0)


def test_validate_accepts_step_fixture():
    converter = STEPConverter()
    assert converter.validate(FIXTURE) is True


def test_validate_rejects_non_step_content(tmp_path):
    bad = tmp_path / "fake.step"
    bad.write_text("this is not a STEP file")
    converter = STEPConverter()
    assert converter.validate(str(bad)) is False


def test_validate_rejects_wrong_extension(tmp_path):
    wrong = tmp_path / "model.stl"
    wrong.write_text("ISO-10303-21;")
    converter = STEPConverter()
    assert converter.validate(str(wrong)) is False


def test_convert_produces_glb_in_meters(tmp_path):
    output = tmp_path / "model.glb"
    converter = STEPConverter()
    assert converter.convert(FIXTURE, str(output)) is True
    assert output.exists()

    scene = trimesh.load(str(output))
    # STEP units (inches here) must land in meters in the GLB
    assert np.allclose(scene.extents, EXPECTED_EXTENTS, rtol=0.01)


def test_color_applies_when_step_has_no_colours(tmp_path):
    converter, output, ok = _convert(BOX, tmp_path, color="#B87333")

    assert ok, converter.errors
    factors = [m.pbrMetallicRoughness.baseColorFactor for m in GLTF2.load(str(output)).materials]
    assert factors and all(f == pytest.approx([0.4793, 0.1714, 0.0331, 1.0], abs=1e-3) for f in factors)


def test_own_step_colours_win_over_the_picker(tmp_path):
    converter, output, ok = _convert(COLORED, tmp_path, color="#00FF00")

    assert ok, converter.errors
    factors = {m.name: m.pbrMetallicRoughness.baseColorFactor[:3] for m in GLTF2.load(str(output)).materials}
    assert factors["Housing"] == pytest.approx([1.0, 0.0, 0.0], abs=0.02)
    assert factors["Cap"] == pytest.approx([0.0, 0.0, 1.0], abs=0.02)


def test_convert_with_max_dimension_scales(tmp_path):
    output = tmp_path / "model.glb"
    converter = STEPConverter()
    converter.set_max_dimension(0.05)  # 5 cm
    assert converter.convert(FIXTURE, str(output)) is True

    scene = trimesh.load(str(output))
    assert max(scene.extents) == pytest.approx(0.05, rel=0.01)


def test_convert_fails_cleanly_on_invalid_file(tmp_path):
    bad = tmp_path / "broken.step"
    bad.write_text("ISO-10303-21;\ngarbage that is not parseable")
    output = tmp_path / "model.glb"
    converter = STEPConverter()
    assert converter.convert(str(bad), str(output)) is False
    assert not output.exists()
    assert converter.errors


def test_convert_retries_coarser_tessellation_when_over_limit(tmp_path, monkeypatch):
    """A model too complex at default tessellation quality must be retried
    with coarser tolerances instead of bouncing the upload — STEP is B-rep,
    so triangle count is a conversion-time choice. The fixture yields ~8.3k
    faces at default quality and ~2.9k at the first coarser step."""
    import converters.step_converter as sc

    monkeypatch.setattr(sc, "MAX_MESH_FACES", 5000)
    output = tmp_path / "model.glb"
    converter = STEPConverter()
    assert converter.convert(FIXTURE, str(output)) is True

    faces, verts = sc._glb_complexity(str(output))
    assert faces <= 5000, "kept a tessellation above the complexity limit"
    # Units/geometry must survive the coarsening (still the same real part).
    scene = trimesh.load(str(output))
    assert np.allclose(scene.extents, EXPECTED_EXTENTS, rtol=0.05)


def test_convert_fails_when_even_coarsest_tessellation_too_complex(tmp_path, monkeypatch):
    import converters.step_converter as sc

    monkeypatch.setattr(sc, "MAX_MESH_FACES", 100)
    output = tmp_path / "model.glb"
    converter = STEPConverter()
    assert converter.convert(FIXTURE, str(output)) is False
    assert not output.exists()
    assert any("too complex" in e.lower() for e in converter.errors)


# --- assemblies: parts stay separate, named and layer-ready -----------------

def test_colored_assembly_keeps_part_names_colours_and_layers(tmp_path):
    converter, output, ok = _convert(COLORED, tmp_path)

    assert ok, converter.errors
    gltf = GLTF2.load(str(output))
    assert [n.name for n in gltf.nodes if n.mesh is not None] == ["Housing", "Shaft", "Cap"]
    assert [l["name"] for l in converter.layers] == ["Housing", "Shaft", "Cap"]
    assert [l["color"] for l in converter.layers] == ["#ff0000", "#00cb00", "#0000ff"]
    # the layer list rides along in the GLB for the viewer's Layers panel
    assert gltf.scenes[gltf.scene].extras[EXTRAS_KEY] == converter.layers


def test_assembly_is_y_up_in_metres_and_centred(tmp_path):
    _, output, ok = _convert(COLORED, tmp_path)

    assert ok
    # 20 x 20 x 45 mm, tallest axis (STEP Z) must end up on glTF Y.
    assert _extents(output) == pytest.approx([0.020, 0.045, 0.020], abs=1e-4)
    bounds = trimesh.load(str(output), force="scene").bounds
    assert (bounds[0] + bounds[1]) / 2 == pytest.approx([0, 0, 0], abs=1e-6)


def test_assembly_label_names_resolved_and_repeats_form_one_layer(tmp_path):
    converter, output, ok = _convert(UNICODE, tmp_path)

    assert ok, converter.errors
    gltf = GLTF2.load(str(output))
    names = [n.name for n in gltf.nodes if n.mesh is not None]
    # OCAF labels ("=>[0:1:1:4]") are replaced by the real (escaped) part names
    assert names == ["Gövde", "Şaft", "Kapak ü", "Ünite-Ç", "Cıvata", "Cıvata", "Cıvata", "Cıvata"]
    assert [(l["name"], l.get("count")) for l in converter.layers] == [
        ("Gövde", None), ("Şaft", None), ("Kapak ü", None), ("Ünite-Ç", None), ("Cıvata", 4),
    ]
    # one uniquely named material per layer, shared by all four bolts
    assert sorted(m.name for m in gltf.materials) == sorted(["Gövde", "Şaft", "Kapak ü", "Ünite-Ç", "Cıvata"])


def test_uncoloured_assembly_gets_one_default_material_per_part(tmp_path):
    converter, output, ok = _convert(SAME_COLOR, tmp_path)

    assert ok, converter.errors
    materials = GLTF2.load(str(output)).materials
    assert [m.name for m in materials] == ["Housing", "Shaft", "Cap"]
    assert all(m.pbrMetallicRoughness.baseColorFactor == pytest.approx([0.6038] * 3 + [1.0]) for m in materials)


def test_single_part_has_no_layers(tmp_path):
    converter, output, ok = _convert(BOX, tmp_path)

    assert ok, converter.errors
    assert converter.layers == []
    assert EXTRAS_KEY not in (GLTF2.load(str(output)).scenes[0].extras or {})


def test_uppercase_extension_accepted(tmp_path):
    source = tmp_path / "BOX.STP"
    with open(BOX, "rb") as handle:
        source.write_bytes(handle.read())

    converter, _, ok = _convert(source, tmp_path)

    assert ok, converter.errors


# --- OpenCASCADE runs in a child process ------------------------------------

def test_cascadio_runs_in_a_child_process(tmp_path, monkeypatch):
    import converters.step_converter as sc

    calls = []
    real_run = subprocess.run

    def spy(command, **kwargs):
        calls.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(sc.subprocess, "run", spy)
    converter, _, ok = _convert(COLORED, tmp_path)

    assert ok, converter.errors
    assert calls and calls[0][1:3] == ["-m", "converters.step_cli"]


def test_child_process_crash_fails_cleanly(tmp_path, monkeypatch):
    import converters.step_converter as sc

    # e.g. OpenCASCADE segfaulting on a hostile file: the worker survives
    monkeypatch.setattr(sc.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=-11, stderr="Segmentation fault"))
    converter, output, ok = _convert(COLORED, tmp_path)

    assert ok is False
    assert not output.exists()
    assert any("STEP conversion failed" in e for e in converter.errors)


def test_every_attempt_timing_out_fails_cleanly(tmp_path, monkeypatch):
    import converters.step_converter as sc

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(sc.subprocess, "run", timeout)
    converter, output, ok = _convert(COLORED, tmp_path)

    assert ok is False
    assert not output.exists()
    assert any("timed out" in e for e in converter.errors)
    assert not list(tmp_path.glob("*.step.*"))  # no work file left behind
