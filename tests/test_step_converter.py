"""Tests for the STEP -> GLB converter (cascadio/OpenCASCADE backed).

Fixture: tests/fixtures/featuretype.step is the MIT-licensed sample part from
the trimesh repository (a 5" x 2.5" machined plate), used because STEP files
cannot be generated with the libraries available in this project.
"""

import os

import numpy as np
import pytest
import trimesh

from converters.step_converter import STEPConverter

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "featuretype.step")

# Known real-world size of the fixture part in meters (5" x 2.5" x 1.375").
EXPECTED_EXTENTS = np.array([0.127, 0.0635, 0.034925])


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


def test_convert_with_color_applies_vertex_colors(tmp_path):
    output = tmp_path / "model.glb"
    converter = STEPConverter()
    assert converter.convert(FIXTURE, str(output), color="#FF0000") is True

    scene = trimesh.load(str(output))
    mesh = list(scene.geometry.values())[0]
    colors = np.asarray(mesh.visual.to_color().vertex_colors if hasattr(
        mesh.visual, "to_color") else mesh.visual.vertex_colors)
    # Pure red survives sRGB->linear conversion as (255, 0, 0)
    assert colors[:, 0].max() == 255
    assert colors[:, 1].max() == 0
    assert colors[:, 2].max() == 0


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
