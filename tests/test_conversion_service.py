from pathlib import Path

import trimesh

from services import AssetQualityService, ConversionService


def test_conversion_service_handles_glb_postprocessing_and_report(monkeypatch):
    root = Path(".test-conversion-service").resolve()
    root.mkdir(exist_ok=True)
    source = root / "source.glb"
    output = root / "output.glb"
    trimesh.creation.box(extents=[2, 1, 1]).export(source)
    service = ConversionService(AssetQualityService())
    stages = []
    result = service.convert({
        "file_extension": ".glb",
        "temp_file_path": str(source),
        "temp_dir": str(root),
        "original_filename": "source.glb",
        "max_dimension": 1.0,
        "compression": "none",
        "use_color": False,
    }, str(output), progress=lambda progress, stage, detail: stages.append(stage))
    assert output.exists()
    assert result["file_size"] == output.stat().st_size
    assert result["asset_report"]["valid"] is True
    assert result["asset_report"]["triangles"] == 12
    assert "Preparing GLB" in stages
    output.unlink(); source.unlink(); root.rmdir()


def test_conversion_service_rejects_unknown_format():
    service = ConversionService(AssetQualityService())
    try:
        service.convert({
            "file_extension": ".exe", "temp_file_path": "none",
            "original_filename": "bad.exe",
        }, "output.glb")
    except RuntimeError as exc:
        assert "Unsupported file format" in str(exc)
    else:
        raise AssertionError("Unsupported input was accepted")
