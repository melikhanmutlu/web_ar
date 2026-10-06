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
    assert "Remove hidden layers permanently" in body
    assert "stay inside the saved file" in body

    resp = client.post("/save_modifications", json={
        "model_id": model_id, "modifications": {"layers": {"restore_hidden": True}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()
    assert _visible_names(glb_path) == ["PartA", "PartB"]
    assert "Restore 1 hidden layer" not in client.get(f"/view/{model_id}").get_data(as_text=True)


def _blob_size(path):
    gltf = GLTF2().load(str(path))
    return len(gltf.binary_blob() or b"")


def test_purge_hidden_layers_removes_geometry_from_the_file(tmp_path):
    source, hidden, purged = tmp_path / "in.glb", tmp_path / "hidden.glb", tmp_path / "purged.glb"
    _two_part_glb(source)
    assert modify_glb(str(source), str(hidden), {"layers": {"hidden": [{"name": "PartA", "occurrence": 0}]}})
    assert modify_glb(str(hidden), str(purged), {"layers": {"purge_hidden": True}})

    gltf = GLTF2().load(str(purged))
    assert [n.name for n in gltf.nodes] == ["world", "PartB"]
    assert len(gltf.meshes) == 1
    assert len(gltf.accessors) < len(GLTF2().load(str(hidden)).accessors)
    assert _blob_size(purged) < _blob_size(hidden)
    assert count_hidden_layers(str(purged)) == 0
    assert _visible_names(purged) == ["PartB"]
    # Still a valid, loadable model with only PartB's geometry.
    loaded = trimesh.load(str(purged), force="scene")
    assert sum(len(g.faces) for g in loaded.geometry.values()) == 12
    # Nothing left to restore.
    restored = tmp_path / "restored.glb"
    assert modify_glb(str(purged), str(restored), {"layers": {"restore_hidden": True}})
    assert _visible_names(restored) == ["PartB"]


def test_purge_hidden_layers_keeps_shared_mesh_used_by_visible_node(tmp_path):
    from pygltflib import Node
    source, hidden, purged = tmp_path / "in.glb", tmp_path / "hidden.glb", tmp_path / "purged.glb"
    _two_part_glb(source)
    gltf = GLTF2().load(str(source))
    gltf.nodes.append(Node(name="PartA_copy", mesh=gltf.nodes[1].mesh))
    gltf.scenes[0].nodes.append(len(gltf.nodes) - 1)
    gltf.save(str(source))
    assert modify_glb(str(source), str(hidden), {"layers": {"hidden": [{"name": "PartA", "occurrence": 0}]}})
    assert modify_glb(str(hidden), str(purged), {"layers": {"purge_hidden": True}})
    assert _visible_names(purged) == ["PartA_copy", "PartB"]
    assert len(GLTF2().load(str(purged)).meshes) == 2


def test_purge_hidden_via_save_modifications_versions_and_counts(client):
    from models import ModelVersion
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    _two_part_glb(glb_path)
    db.session.add(UserModel(id=model_id, filename=glb_path, file_type="glb", file_size=1,
                             user_id=None, cumulative_scale=1.0, visibility="public",
                             vertices=999, faces=999))
    db.session.commit()
    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"layers": {"hidden": [{"name": "PartB", "occurrence": 0}]}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()
    db.session.expire_all()
    version_before = db.session.get(UserModel, model_id).asset_version or 0
    versions_before = ModelVersion.query.filter_by(model_id=model_id).count()

    resp = client.post("/save_modifications", json={
        "model_id": model_id, "modifications": {"layers": {"purge_hidden": True}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()
    db.session.expire_all()
    model = db.session.get(UserModel, model_id)
    assert (model.asset_version or 0) > version_before
    assert ModelVersion.query.filter_by(model_id=model_id).count() == versions_before + 1
    assert model.faces == 12
    assert len(GLTF2().load(glb_path).meshes) == 1
    assert "Restore 1 hidden layer" not in client.get(f"/view/{model_id}").get_data(as_text=True)
