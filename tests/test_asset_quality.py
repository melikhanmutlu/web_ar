from pathlib import Path

import trimesh

from models import UserModel, db
from services import AssetQualityService


def test_asset_quality_report_contains_geometry_material_and_budgets():
    path = Path("test-quality.glb").resolve()
    trimesh.creation.box().export(path)
    service = AssetQualityService(warning_triangles=5, warning_bytes=1)
    report = service.inspect(path)
    assert report["vertices"] == 8
    assert report["triangles"] == 12
    assert report["meshes"] >= 1
    assert report["budgets"]["warning_triangles"] == 5
    assert len(report["warnings"]) >= 2
    path.unlink(missing_ok=True)


def test_validation_api_returns_persisted_report(client):
    model = UserModel(
        id="77777777-7777-7777-7777-777777777777",
        filename="unused.glb",
        validation_report={"valid": True, "triangles": 42, "warnings": []},
    )
    db.session.add(model)
    db.session.commit()
    response = client.get(f"/api/models/{model.id}/validation")
    assert response.status_code == 200
    assert response.get_json()["report"]["triangles"] == 42
