"""Faz 1 data-integrity tests for the conversion pipeline: size limit, units,
corrupt input, glTF/OBJ staging."""
import io
import json
import os
import struct
import uuid

import pytest
import trimesh
from pygltflib import (
    GLTF2, Accessor, Animation, AnimationChannel, AnimationChannelTarget,
    AnimationSampler, BufferView,
)

import app as app_module
from models import UserModel


def run_pipeline(tmp_path, filename, data, extra_files=None, **opts):
    """Run _run_upload_pipeline on `data` and return (UserModel, glb_path)."""
    temp_dir = tmp_path / ("src-" + uuid.uuid4().hex[:6])
    temp_dir.mkdir()
    src = temp_dir / filename
    src.write_bytes(data)
    for name, blob in (extra_files or {}).items():
        target = temp_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    payload = {
        "unique_id": "t-" + uuid.uuid4().hex[:10],
        "original_filename": filename,
        "temp_file_path": str(src),
        "temp_dir": str(temp_dir),
        "file_extension": os.path.splitext(filename)[1].lower(),
        "compression": "none",
    }
    payload.update(opts)
    mid = app_module._run_upload_pipeline(payload)
    model = app_module.db.session.get(UserModel, mid)
    return model, model.filename


@pytest.fixture(autouse=True)
def _no_background_jobs(monkeypatch):
    monkeypatch.setattr(app_module, "_enqueue_internal_job", lambda *a, **k: None)


def glb_extents_m(path):
    scene = trimesh.load(path, force="scene")
    return scene.bounds[1] - scene.bounds[0]


def box_glb(extents):
    return trimesh.Scene(trimesh.creation.box(extents=extents)).export(file_type="glb")


def box_stl(extents):
    return trimesh.creation.box(extents=extents).export(file_type="stl")


def box_obj(extents):
    return trimesh.creation.box(extents=extents).export(file_type="obj").encode()


def db_max_cm(model):
    return json.loads(model.bounds)["max"]


# --- size limit: applied exactly once, shrink-only, DB matches file --------

def test_glb_limit_applied_once_and_db_matches_file(client, tmp_path):
    model, glb = run_pipeline(tmp_path, "big.glb", box_glb([1, 1, 1]), max_dimension=0.2)
    assert glb_extents_m(glb).max() == pytest.approx(0.2, abs=1e-4)
    assert db_max_cm(model) == pytest.approx(20.0, abs=0.05)


def test_glb_smaller_than_limit_is_untouched(client, tmp_path):
    model, glb = run_pipeline(tmp_path, "small.glb", box_glb([0.04, 0.04, 0.04]), max_dimension=0.2)
    assert glb_extents_m(glb).max() == pytest.approx(0.04, abs=1e-4)
    assert db_max_cm(model) == pytest.approx(4.0, abs=0.05)


def test_glb_limit_keeps_animations(client, tmp_path):
    src = tmp_path / "a.glb"
    src.write_bytes(box_glb([1, 1, 1]))
    gltf = GLTF2().load(str(src))
    blob = gltf.binary_blob()
    blob += b"\0" * ((-len(blob)) % 4)
    start = len(blob)
    blob += struct.pack("<2f", 0.0, 1.0) + struct.pack("<8f", 0, 0, 0, 1, 0, 0.7071, 0, 0.7071)
    gltf.set_binary_blob(blob)
    gltf.buffers[0].byteLength = len(blob)
    gltf.bufferViews += [BufferView(buffer=0, byteOffset=start, byteLength=8),
                         BufferView(buffer=0, byteOffset=start + 8, byteLength=32)]
    n = len(gltf.accessors)
    gltf.accessors += [
        Accessor(bufferView=len(gltf.bufferViews) - 2, componentType=5126, count=2,
                 type="SCALAR", min=[0.0], max=[1.0]),
        Accessor(bufferView=len(gltf.bufferViews) - 1, componentType=5126, count=2, type="VEC4"),
    ]
    gltf.animations = [Animation(
        samplers=[AnimationSampler(input=n, output=n + 1)],
        channels=[AnimationChannel(sampler=0, target=AnimationChannelTarget(node=0, path="rotation"))],
    )]
    gltf.save(str(src))
    model, glb = run_pipeline(tmp_path, "anim.glb", src.read_bytes(), max_dimension=0.2)
    assert len(GLTF2().load(glb).animations) == 1
    assert glb_extents_m(glb).max() == pytest.approx(0.2, abs=1e-3)


@pytest.mark.parametrize("fname,builder,unit,extent,expected_cm", [
    ("a.stl", box_stl, "cm", 4.0, 4.0),      # 4 cm box stays 4 cm (was 20 cm)
    ("a.stl", box_stl, "mm", 0.5, 0.05),     # 0.5 mm stays 0.5 mm (was 50 cm)
    ("a.obj", box_obj, "cm", 4.0, 4.0),
    ("a.obj", box_obj, "mm", 0.5, 0.05),
])
def test_limit_never_enlarges_stl_obj(client, tmp_path, fname, builder, unit, extent, expected_cm):
    model, glb = run_pipeline(tmp_path, fname, builder([extent] * 3),
                              source_unit=unit, max_dimension=0.5)
    assert glb_extents_m(glb).max() * 100 == pytest.approx(expected_cm, rel=0.02)


def test_limit_still_shrinks_stl(client, tmp_path):
    model, glb = run_pipeline(tmp_path, "b.stl", box_stl([100, 100, 100]),
                              source_unit="cm", max_dimension=0.2)
    assert glb_extents_m(glb).max() == pytest.approx(0.2, abs=1e-3)
    assert db_max_cm(model) == pytest.approx(20.0, abs=0.1)


def test_size_limit_server_range_matches_ui(client):
    for bad in ("5", "101", "0", "-3", "nan"):
        r = client.post("/api/uploads/batch", data={
            "files": [(io.BytesIO(b"solid x endsolid x"), "one.stl")],
            "useMaxDimension": "true", "maxDimension": bad,
        }, content_type="multipart/form-data")
        assert r.status_code == 400, bad
    ui = open(os.path.join(os.path.dirname(app_module.__file__), "templates/studio.html")).read()
    assert 'id="max-dimension"' in ui and 'min="10" max="100"' in ui


def test_legacy_endpoints_still_gone(client):
    assert client.post("/upload").status_code == 410
    assert client.post("/convert", json={}).status_code == 410
