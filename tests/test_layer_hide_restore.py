"""P3D-20: hiding a layer detaches it from the scene but keeps it in the file,
flagged in the node extras so it can be restored."""

import os
import uuid

import trimesh
from pygltflib import GLTF2

from app import app, db
from glb_modifier import (
    HIDDEN_LAYER_EXTRAS_KEY, _iter_gltf_mesh_nodes, count_hidden_layers, modify_glb,
)
from models import UserModel


def _two_part_glb(path):
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=(1, 1, 1)), node_name="PartA", geom_name="GeomA")
    box_b = trimesh.creation.box(extents=(1, 1, 1))
    box_b.apply_translation((3, 0, 0))
    scene.add_geometry(box_b, node_name="PartB", geom_name="GeomB")
    scene.export(str(path), file_type="glb")


def _visible_names(path):
    gltf = GLTF2().load(str(path))
    return sorted(node.name for _, node in _iter_gltf_mesh_nodes(gltf))


def test_hidden_layer_is_flagged_and_restorable(tmp_path):
    source, hidden, restored = tmp_path / "in.glb", tmp_path / "hidden.glb", tmp_path / "restored.glb"
    _two_part_glb(source)
    assert _visible_names(source) == ["PartA", "PartB"]

    assert modify_glb(str(source), str(hidden), {"layers": {"hidden": [{"name": "PartA", "occurrence": 0}]}})
    assert _visible_names(hidden) == ["PartB"]
    gltf = GLTF2().load(str(hidden))
    assert len(gltf.meshes) == 2, "hidden geometry stays in the file"
    flagged = [n for n in gltf.nodes if isinstance(n.extras, dict) and HIDDEN_LAYER_EXTRAS_KEY in n.extras]
    assert [n.name for n in flagged] == ["PartA"]
    assert count_hidden_layers(str(hidden)) == 1
    assert count_hidden_layers(str(source)) == 0

    assert modify_glb(str(hidden), str(restored), {"layers": {"restore_hidden": True}})
    assert _visible_names(restored) == ["PartA", "PartB"]
    assert count_hidden_layers(str(restored)) == 0


def test_viewer_offers_restore_and_save_modifications_restores(client):
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    _two_part_glb(glb_path)
    db.session.add(UserModel(id=model_id, filename=glb_path, file_type="glb", file_size=1,
                             user_id=None, cumulative_scale=1.0, visibility="public"))
    db.session.commit()

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"layers": {"hidden": [{"name": "PartB", "occurrence": 0}]}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()
    assert _visible_names(glb_path) == ["PartA"]
    body = client.get(f"/view/{model_id}").get_data(as_text=True)
    assert "Restore 1 hidden layer" in body
    assert "stay inside the saved file" in body

    resp = client.post("/save_modifications", json={
        "model_id": model_id, "modifications": {"layers": {"restore_hidden": True}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()
    assert _visible_names(glb_path) == ["PartA", "PartB"]
    assert "Restore 1 hidden layer" not in client.get(f"/view/{model_id}").get_data(as_text=True)
