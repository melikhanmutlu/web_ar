"""Conversions in a short-lived child process (ConversionService(isolate=True))
and the quality report on GLBs that carry LINES primitives."""

import os
import subprocess
import sys

import numpy as np
import pytest
import trimesh

from services import conversion as conversion_module
from services.asset_quality import AssetQualityService
from services.conversion import ConversionService
from services.conversion_errors import UserFacingConversionError

STEP = os.path.join(os.path.dirname(__file__), "fixtures", "step", "assembly_colored.step")


def _payload(path, extension, tmp_path):
    return {
        "file_extension": extension,
        "temp_file_path": path,
        "original_filename": os.path.basename(path),
        "temp_dir": str(tmp_path),
        "compression": "none",
    }


def test_isolated_conversion_matches_in_process(tmp_path):
    steps = []
    isolated = ConversionService(AssetQualityService(), isolate=True).convert(
        _payload(STEP, ".step", tmp_path), str(tmp_path / "child.glb"),
        progress=lambda value, *_args, **_extra: steps.append(value),
    )
    inline = ConversionService(AssetQualityService()).convert(
        _payload(STEP, ".step", tmp_path), str(tmp_path / "inline.glb")
    )

    assert steps[0] == 48 and steps[-1] == 90
    assert isolated["dimensions_cm"] == inline["dimensions_cm"]
    assert isolated["asset_report"]["triangles"] == inline["asset_report"]["triangles"]
    assert isolated["converter"].original_dimensions is None
    assert os.path.getsize(tmp_path / "child.glb") > 0


def test_isolated_conversion_keeps_the_user_facing_error(tmp_path):
    bad = tmp_path / "bad.stp"
    bad.write_text("not a step file")
    with pytest.raises(RuntimeError, match="missing ISO-10303-21 header"):
        ConversionService(AssetQualityService(), isolate=True).convert(
            _payload(str(bad), ".stp", tmp_path), str(tmp_path / "out.glb")
        )


def test_a_child_that_dies_reports_a_clear_error(tmp_path, monkeypatch):
    real_popen = subprocess.Popen

    def dying_child(_command, **kwargs):  # e.g. OOM-killed mid-conversion
        return real_popen([sys.executable, "-c", "import os; os._exit(137)"], **kwargs)

    monkeypatch.setattr(conversion_module.subprocess, "Popen", dying_child)
    with pytest.raises(UserFacingConversionError, match="stopped unexpectedly"):
        ConversionService(AssetQualityService(), isolate=True).convert(
            _payload(STEP, ".step", tmp_path), str(tmp_path / "out.glb")
        )


def test_quality_report_counts_triangles_next_to_line_primitives(tmp_path):
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box())
    scene.add_geometry(trimesh.load_path(np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0]], dtype=float)))
    path = tmp_path / "lines.glb"
    scene.export(str(path))

    report = AssetQualityService().inspect(str(path))

    assert report["triangles"] == 12
    assert report["valid"] is True
