"""Version comparison (Faz 4: "Sürüm karşılaştırma")."""

import os
import uuid

import trimesh

from app import app, db
from models import UserModel
from version_manager import create_version


def make_model_with_two_versions(user_id=None):
    model_id = "vc-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")

    box = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(box).export(file_type="glb"))

    model = UserModel(id=model_id, filename=f"{model_id}/model.glb",
                      file_type="glb", user_id=user_id, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()

    v1 = create_version(model_id, "upload", comment="initial")

    bigger_box = trimesh.creation.box(extents=(0.2, 0.1, 0.1))
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(bigger_box).export(file_type="glb"))
    v2 = create_version(model_id, "transform", comment="scaled up")

    return model_id, v1.version_number, v2.version_number


def test_compare_returns_dimension_and_geometry_deltas(client):
    model_id, v1, v2 = make_model_with_two_versions(user_id=None)

    resp = client.get(f"/api/versions/{model_id}/compare/{v1}/{v2}")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["version_a"]["version_number"] == v1
    assert body["version_b"]["version_number"] == v2
    # Width doubled (0.1m -> 0.2m = 10cm -> 20cm), so the delta is positive.
    assert body["diff"]["dimensions"]["x"] > 0


def test_compare_missing_version_404s(client):
    model_id, v1, _ = make_model_with_two_versions(user_id=None)
    resp = client.get(f"/api/versions/{model_id}/compare/{v1}/999")
    assert resp.status_code == 404


def test_compare_respects_view_permission(client):
    from models import User

    owner = User(username="vc-owner", email="vc-owner@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()

    model_id, v1, v2 = make_model_with_two_versions(user_id=owner.id)
    UserModel.query.get(model_id).visibility = "private"
    db.session.commit()

    resp = client.get(f"/api/versions/{model_id}/compare/{v1}/{v2}")
    assert resp.status_code == 403
