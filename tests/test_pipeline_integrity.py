"""Faz 1 data-integrity tests for the conversion pipeline: size limit, units,
corrupt input, glTF/OBJ staging."""
import io
import json
import os
import struct
import uuid
import zipfile

import pytest
import trimesh
from pygltflib import (
    GLTF2, Accessor, Animation, AnimationChannel, AnimationChannelTarget,
    AnimationSampler, BufferView, Scene,
)

import app as app_module
from services import upload_pipeline
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
    mid = upload_pipeline._run_upload_pipeline(payload)
    model = app_module.db.session.get(UserModel, mid)
    return model, model.filename


@pytest.fixture(autouse=True)
def _no_background_jobs(monkeypatch):
    monkeypatch.setattr(upload_pipeline, "_enqueue_internal_job", lambda *a, **k: None)


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


# --- units: default cm everywhere, auto prefers mm > cm > m ----------------

def test_auto_detect_prefers_mm_then_cm_then_m():
    from converters.base_converter import BaseConverter
    detect = BaseConverter.auto_detect_unit
    assert detect(100.0)[0] == "mm"      # typical 100 mm part
    assert detect(50.0)[0] == "mm"
    assert detect(1500.0)[0] == "mm"
    assert detect(20.0)[0] == "cm"       # only plausible as cm
    assert detect(0.5)[0] == "m"         # only plausible as metres
    assert detect(2.0)[0] == "m"
    assert detect(100000.0)[0] == "mm"   # huge -> mm fallback


@pytest.mark.parametrize("fname,builder", [("u.stl", box_stl), ("u.obj", box_obj)])
def test_default_unit_is_cm_and_auto_is_explicit(client, tmp_path, fname, builder):
    data = builder([100, 50, 20])
    model, glb = run_pipeline(tmp_path, fname, data)  # no source_unit -> cm
    assert glb_extents_m(glb).max() == pytest.approx(1.0, abs=1e-3)
    model, glb = run_pipeline(tmp_path, fname, data, source_unit="auto")
    assert glb_extents_m(glb).max() == pytest.approx(0.1, abs=1e-3)  # auto -> mm


def test_resolved_unit_reported_in_job_status(client, tmp_path):
    from models import ConversionJob, db
    from werkzeug.security import generate_password_hash
    payload = {
        "unique_id": "t-" + uuid.uuid4().hex[:10], "original_filename": "u.stl",
        "file_extension": ".stl", "source_unit": "auto", "compression": "none",
    }
    temp_dir = tmp_path / "s"
    temp_dir.mkdir()
    (temp_dir / "u.stl").write_bytes(box_stl([100, 50, 20]))
    payload.update(temp_dir=str(temp_dir), temp_file_path=str(temp_dir / "u.stl"))
    job = ConversionJob(id=payload["unique_id"], job_type="upload", status="processing",
                        payload=payload, status_token_hash=generate_password_hash("tok"))
    db.session.add(job)
    db.session.commit()
    upload_pipeline.run_conversion_job(job, allow_retry=False)
    r = client.get(f"/api/upload-jobs/{job.id}", headers={"X-Job-Status-Token": "tok"})
    body = r.get_json()
    assert body["status"] == "completed", body
    assert body["source_unit"] == "mm" and body["detected_unit"] == "mm"


# --- corrupt / degenerate input fails clearly -------------------------------

def _pipeline_error(tmp_path, filename, data, **opts):
    with pytest.raises(RuntimeError) as exc:
        run_pipeline(tmp_path, filename, data, **opts)
    return str(exc.value)


def test_corrupt_glb_is_rejected(client, tmp_path):
    hdr = struct.pack("<4sII", b"glTF", 2, 12 + 8 + 20)
    garbage = hdr + struct.pack("<II", 20, 0x4E4F534A) + b"not json at all!!!!!!"
    msg = _pipeline_error(tmp_path, "bad.glb", garbage)
    assert "corrupt" in msg.lower()
    assert UserModel.query.count() == 0


def test_truncated_glb_is_rejected(client, tmp_path):
    good = box_glb([1, 1, 1])
    msg = _pipeline_error(tmp_path, "cut.glb", good[: len(good) // 2])
    assert "corrupt" in msg.lower()


def test_glb_without_geometry_is_rejected(client, tmp_path):
    empty = tmp_path / "empty.glb"
    gltf = GLTF2()
    gltf.scenes = [Scene(nodes=[])]
    gltf.scene = 0
    gltf.save(str(empty))
    msg = _pipeline_error(tmp_path, "empty.glb", empty.read_bytes())
    assert "no 3d geometry" in msg.lower()


def test_degenerate_stl_is_a_failed_conversion(client, tmp_path):
    # One zero-area triangle with all vertices at the same point.
    tri = struct.pack("<12fH", *([0.0] * 12), 0)
    data = b"\0" * 80 + struct.pack("<I", 1) + tri
    msg = _pipeline_error(tmp_path, "degenerate.stl", data)
    assert "no usable geometry" in msg.lower() or "failed" in msg.lower()
    assert UserModel.query.count() == 0


def test_garbage_stl_error_is_friendly(client, tmp_path):
    msg = _pipeline_error(tmp_path, "garbage.stl", bytes(range(256)) * 8)
    assert "chardet" not in msg and "module" not in msg.lower()
    assert "/" not in msg


def test_sub_millimetre_model_keeps_dimensions(client, tmp_path):
    model, glb = run_pipeline(tmp_path, "tiny.stl", box_stl([0.5, 0.5, 0.5]), source_unit="mm")
    dims = json.loads(model.bounds)
    assert dims["max"] == pytest.approx(0.05, abs=1e-3)  # cm
    assert dims["extents"][0] > 0


def test_error_messages_never_leak_paths_or_modules():
    from services.conversion_errors import friendly_conversion_error, sanitize_error_message
    leaked = "[Errno 2] No such file or directory: '/srv/app/storage/temp/abc/gltf_buffer_0.bin'"
    msg = friendly_conversion_error(FileNotFoundError(leaked), ".gltf")
    assert "/srv" not in msg and "storage" not in msg
    assert "chardet" not in friendly_conversion_error(
        ModuleNotFoundError("No module named 'chardet'"), ".stl")
    assert "/srv/app" not in sanitize_error_message("failed reading /srv/app/storage/x.bin now")
    assert sanitize_error_message("see https://example.com/a/b ok") == "see https://example.com/a/b ok"


def test_job_error_is_sanitized(client):
    from models import ConversionJob, db
    from services import ConversionJobService
    job = ConversionJob(id=uuid.uuid4().hex[:8], job_type="upload", status="processing",
                        payload={}, attempts=1, max_attempts=1)
    db.session.add(job)
    db.session.commit()
    ConversionJobService(db).fail(job, RuntimeError("boom at /storage/temp/abc/model.bin"),
                                  allow_retry=False)
    assert "/storage" not in job.error and "model.bin" in job.error


# --- glTF buffers and OBJ textures are staged safely ------------------------

def _png_bytes(color=(200, 30, 30)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def _zip_upload(name, entries):
    from werkzeug.datastructures import FileStorage
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        for path, content in entries.items():
            archive.writestr(path, content)
    buf.seek(0)
    return FileStorage(stream=buf, filename=name)


def _file_upload(name, data):
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(data), filename=name)


def stage_and_convert(tmp_path, upload, **kwargs):
    from services import UploadStagingService
    service = UploadStagingService(tmp_path / "staging", max_uncompressed_bytes=50 * 1024 * 1024)
    (tmp_path / "staging").mkdir(exist_ok=True)
    job_id = "j-" + uuid.uuid4().hex[:8]
    staged = service.stage(job_id, upload, **kwargs)
    payload = {"unique_id": job_id, "compression": "none", **staged}
    mid = upload_pipeline._run_upload_pipeline(payload)
    model = app_module.db.session.get(UserModel, mid)
    return staged, model


def _gltf_files():
    """trimesh's own .gltf + .bin export (name -> bytes)."""
    scene = trimesh.Scene(trimesh.creation.box(extents=[0.2, 0.2, 0.2]))
    return dict(scene.export(file_type="gltf"))


def test_gltf_with_bin_in_zip_converts(client, tmp_path):
    files = _gltf_files()
    assert any(name.endswith(".bin") for name in files)
    gltf_name = next(n for n in files if n.endswith(".gltf"))
    staged, model = stage_and_convert(tmp_path, _zip_upload("m.zip", files))
    assert staged["file_extension"] == ".gltf"
    assert glb_extents_m(model.filename).max() == pytest.approx(0.2, abs=1e-3)
    assert gltf_name


def test_gltf_buffers_in_subfolder_are_flattened(client, tmp_path):
    files = _gltf_files()
    gltf_name = next(n for n in files if n.endswith(".gltf"))
    doc = json.loads(files[gltf_name])
    entries = {gltf_name: None}
    for buffer in doc["buffers"]:
        bin_name = buffer["uri"]
        buffer["uri"] = "My%20Buffers/" + bin_name
        entries["My Buffers/" + bin_name] = files[bin_name]
    entries[gltf_name] = json.dumps(doc)
    staged, model = stage_and_convert(tmp_path, _zip_upload("m.zip", entries))
    assert glb_extents_m(model.filename).max() == pytest.approx(0.2, abs=1e-3)


def test_single_gltf_with_external_bin_gives_clear_error(client, tmp_path):
    from services import UploadStagingError
    files = _gltf_files()
    gltf_name = next(n for n in files if n.endswith(".gltf"))
    with pytest.raises(UploadStagingError) as exc:
        stage_and_convert(tmp_path, _file_upload("m.gltf", files[gltf_name]))
    message = str(exc.value)
    assert "ZIP" in message and "/" not in message.replace("(or", "")
    assert "storage" not in message


def test_loose_gltf_and_bin_companions_convert(client, tmp_path):
    files = _gltf_files()
    gltf_name = next(n for n in files if n.endswith(".gltf"))
    bins = [_file_upload(n, files[n]) for n in files if n.endswith(".bin")]
    staged, model = stage_and_convert(
        tmp_path, _file_upload("m.gltf", files[gltf_name]), textures=bins,
    )
    assert glb_extents_m(model.filename).max() == pytest.approx(0.2, abs=1e-3)


def _animated_gltf_files():
    """A .gltf + .bins whose first node is animated (translation channel)."""
    import numpy as np

    files = _gltf_files()
    gltf_name = next(n for n in files if n.endswith(".gltf"))
    doc = json.loads(files[gltf_name])
    times = np.array([0.0, 1.0], dtype=np.float32).tobytes()
    moves = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float32).tobytes()
    doc["buffers"].append({"uri": "anim.bin", "byteLength": len(times) + len(moves)})
    buffer_index = len(doc["buffers"]) - 1
    doc["bufferViews"] += [
        {"buffer": buffer_index, "byteOffset": 0, "byteLength": len(times)},
        {"buffer": buffer_index, "byteOffset": len(times), "byteLength": len(moves)},
    ]
    view = len(doc["bufferViews"]) - 2
    doc["accessors"] += [
        {"bufferView": view, "componentType": 5126, "count": 2, "type": "SCALAR",
         "min": [0.0], "max": [1.0]},
        {"bufferView": view + 1, "componentType": 5126, "count": 2, "type": "VEC3"},
    ]
    doc["animations"] = [{
        "name": "slide",
        "samplers": [{"input": len(doc["accessors"]) - 2, "output": len(doc["accessors"]) - 1}],
        "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
    }]
    entries = {n: d for n, d in files.items() if n != gltf_name}
    entries[gltf_name] = json.dumps(doc)
    entries["anim.bin"] = times + moves
    return entries


def _gltf_transform_works():
    import shutil
    import subprocess
    from converters.glb_optimizer import _resolve_gltf_transform
    cmd = _resolve_gltf_transform()
    if not cmd or (cmd[0].endswith("npx") and not shutil.which("gltf-transform")
                   and not os.path.isdir(os.path.join(os.path.dirname(app_module.__file__),
                                                      "node_modules", "@gltf-transform"))):
        return False
    try:
        return subprocess.run(cmd + ["--version"], capture_output=True, timeout=60).returncode == 0
    except Exception:
        return False


@pytest.mark.skipif(not _gltf_transform_works(),
                    reason="gltf-transform unavailable; .gltf input falls back to trimesh, which drops animations")
def test_gltf_animations_survive_packing(client, tmp_path):
    from pygltflib import GLTF2

    staged, model = stage_and_convert(tmp_path, _zip_upload("anim.zip", _animated_gltf_files()))
    assert staged["file_extension"] == ".gltf"
    gltf = GLTF2().load(model.filename)
    assert len(gltf.animations or []) == 1
    assert gltf.animations[0].name == "slide"
    assert glb_extents_m(model.filename).max() == pytest.approx(0.2, abs=1e-3)


@pytest.mark.parametrize("uri", ["/etc/passwd", "../../outside.bin", "file:///etc/passwd", "http://x/y.bin"])
def test_gltf_unsafe_uris_are_rejected(client, tmp_path, uri):
    from services import UploadStagingError
    files = _gltf_files()
    gltf_name = next(n for n in files if n.endswith(".gltf"))
    doc = json.loads(files[gltf_name])
    doc["buffers"][0]["uri"] = uri
    entries = {gltf_name: json.dumps(doc)}
    with pytest.raises(UploadStagingError) as exc:
        stage_and_convert(tmp_path, _zip_upload("m.zip", entries))
    assert "not allowed" in str(exc.value)


OBJ_QUAD = "v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n" \
           "f 1/1 2/2 3/3\nf 1/1 3/3 4/4\n"


def _glb_images(path):
    return len(GLTF2().load(path).images or [])


def test_obj_zip_texture_in_subfolder_is_kept(client, tmp_path):
    entries = {
        "model/chair.obj": "mtllib chair.mtl\nusemtl wood\n" + OBJ_QUAD,
        "model/chair.mtl": "newmtl wood\nKd 1 1 1\nmap_Kd textures/wood.png\n",
        "model/textures/wood.png": _png_bytes(),
    }
    staged, model = stage_and_convert(tmp_path, _zip_upload("c.zip", entries))
    assert _glb_images(model.filename) == 1
    assert staged["staging_warnings"] == []


def test_obj_zip_texture_with_spaces_is_kept(client, tmp_path):
    entries = {
        "my chair.obj": "mtllib my chair.mtl\nusemtl wood\n" + OBJ_QUAD,
        "my chair.mtl": "newmtl wood\nKd 1 1 1\nmap_Kd -s 1 1 1 my wood texture.png\n",
        "my wood texture.png": _png_bytes(),
    }
    from services import UploadStagingService
    service = UploadStagingService(tmp_path / "st", max_uncompressed_bytes=10_000_000)
    (tmp_path / "st").mkdir()
    staged = service.stage("j-" + uuid.uuid4().hex[:8], _zip_upload("c.zip", entries))
    mtl = open(staged["mtl_path"]).read()
    assert "my wood texture" not in mtl and "my_wood_texture.png" in mtl
    assert "-s 1 1 1" in mtl
    assert "mtllib my_chair.mtl" in open(staged["temp_file_path"]).read()
    payload = {"unique_id": "t-" + uuid.uuid4().hex[:8], "compression": "none", **staged}
    model = app_module.db.session.get(UserModel, upload_pipeline._run_upload_pipeline(payload))
    assert _glb_images(model.filename) == 1


def test_obj_missing_texture_adds_warning(client, tmp_path):
    entries = {
        "c.obj": "mtllib c.mtl\nusemtl wood\n" + OBJ_QUAD,
        "c.mtl": "newmtl wood\nKd 0.5 0.5 0.5\nmap_Kd gone.png\n",
    }
    staged, model = stage_and_convert(tmp_path, _zip_upload("c.zip", entries))
    assert any("gone.png" in w for w in staged["staging_warnings"])
    assert any("gone.png" in w for w in model.validation_report["warnings"])


def test_obj_unsafe_texture_reference_is_rejected(client, tmp_path):
    entries = {
        "c.obj": "mtllib c.mtl\nusemtl wood\n" + OBJ_QUAD,
        "c.mtl": "newmtl wood\nKd 0.5 0.5 0.5\nmap_Kd ../../etc/passwd\n",
    }
    with pytest.raises(RuntimeError) as exc:
        stage_and_convert(tmp_path, _zip_upload("c.zip", entries))
    assert "not allowed" in str(exc.value) and "passwd" not in str(exc.value)


@pytest.mark.parametrize("unit", [None, "mm", "m", "auto"])
def test_obj_usemtl_before_vertices_keeps_mtl_colour(client, tmp_path, unit):
    obj = "mtllib c.mtl\nusemtl red\n" + OBJ_QUAD.replace("vt", "#vt")
    obj = obj.replace("f 1/1 2/2 3/3\nf 1/1 3/3 4/4", "f 1 2 3\nf 1 3 4")
    entries = {"c.obj": obj, "c.mtl": "newmtl red\nKd 1 0 0\n"}
    extra = {"source_unit": unit} if unit else {}
    from services import UploadStagingService
    service = UploadStagingService(tmp_path / "st", max_uncompressed_bytes=10_000_000)
    (tmp_path / "st").mkdir()
    staged = service.stage("j-" + uuid.uuid4().hex[:8], _zip_upload("c.zip", entries))
    payload = {"unique_id": "t-" + uuid.uuid4().hex[:8], "compression": "none", **staged, **extra}
    model = app_module.db.session.get(UserModel, upload_pipeline._run_upload_pipeline(payload))
    gltf = GLTF2().load(model.filename)
    primitive = gltf.meshes[0].primitives[0]
    material = gltf.materials[primitive.material]
    assert material.name == "red"
    assert material.pbrMetallicRoughness.baseColorFactor[:3] == [1.0, 0.0, 0.0]
