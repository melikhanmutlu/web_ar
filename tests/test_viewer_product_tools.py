import shutil
from pathlib import Path

import trimesh

import app as app_module
from models import MaterialPreset, ModelVersion, User, UserModel, db


def _owner(client):
    user = User(username="toolowner", email="tools@example.com")
    user.set_password("password")
    db.session.add(user); db.session.commit()
    client.post("/login", data={"username": user.username, "password": "password"})
    return user


def _model_file(model_id, scene=None):
    directory = Path(app_module.app.config["CONVERTED_FOLDER"]) / model_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "model.glb"
    (scene or trimesh.Scene(trimesh.creation.box())).export(path)
    return path, directory


def test_material_library_and_application(client):
    owner = _owner(client)
    model_id = "10101010-1010-1010-1010-101010101010"
    path, directory = _model_file(model_id)
    model = UserModel(id=model_id, filename=str(path), user_id=owner.id)
    db.session.add(model); db.session.commit()
    listed = client.get("/api/material-presets").get_json()["presets"]
    assert any(item["id"] == "system:steel" for item in listed)
    created = client.post("/api/material-presets", json={
        "name": "Brand Red", "color": "#cc1122", "metalness": 0.2,
        "roughness": 0.6, "opacity": 1,
    })
    assert created.status_code == 201
    preset_id = created.get_json()["id"]
    applied = client.post(
        f"/api/models/{model_id}/material-preset", json={"preset_id": preset_id}
    )
    assert applied.status_code == 200
    assert ModelVersion.query.filter_by(model_id=model_id, operation_type="material").count() == 1
    assert client.delete(f"/api/material-presets/{preset_id}").status_code == 200
    shutil.rmtree(directory)


def test_model_comparison_and_exploded_asset(client):
    owner = _owner(client)
    left_id = "20202020-2020-2020-2020-202020202020"
    right_id = "30303030-3030-3030-3030-303030303030"
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(), node_name="body")
    second = trimesh.creation.icosphere(subdivisions=1, radius=0.3)
    second.apply_translation([1.5, 0, 0])
    scene.add_geometry(second, node_name="detail")
    left_path, left_dir = _model_file(left_id, scene)
    right_path, right_dir = _model_file(right_id)
    db.session.add_all([
        UserModel(id=left_id, filename=str(left_path), user_id=owner.id, display_name="Left"),
        UserModel(id=right_id, filename=str(right_path), user_id=owner.id, display_name="Right"),
    ]); db.session.commit()
    compared = client.get(f"/compare/{left_id}/{right_id}")
    assert compared.status_code == 200
    assert "Sync cameras" in compared.get_data(as_text=True)
    exploded = client.post(f"/api/models/{left_id}/exploded", json={"factor": 0.4})
    assert exploded.status_code == 200
    assert (left_dir / "model_exploded.glb").exists()
    assert client.get(f"/api/models/{left_id}/exploded").get_json()["ready"] is True
    shutil.rmtree(left_dir); shutil.rmtree(right_dir)
