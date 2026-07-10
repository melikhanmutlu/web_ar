import shutil
from pathlib import Path
from types import SimpleNamespace

import trimesh

import app as app_module
from converters import glb_optimizer
from converters import lod_generator
from models import ConversionJob, ModelLOD, User, UserModel, db


def test_lod_generator_creates_smaller_valid_variants(monkeypatch):
    root = Path(".test-lods").resolve()
    root.mkdir(exist_ok=True)
    source = root / "model.glb"
    # A subdivided sphere makes the source materially larger than a triangle.
    trimesh.creation.icosphere(subdivisions=3).export(source)
    monkeypatch.setattr(lod_generator, "_resolve_gltfpack", lambda: ["gltfpack"])

    def fake_run(args, **kwargs):
        destination = Path(args[args.index("-o") + 1])
        triangle = trimesh.Trimesh(
            vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]]
        )
        triangle.export(destination)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(lod_generator.subprocess, "run", fake_run)
    outputs = lod_generator.generate_lods(source, root / "out", ratios=[0.5, 0.2])
    assert [item["level"] for item in outputs] == [1, 2]
    assert all(item["file_size"] < source.stat().st_size for item in outputs)
    shutil.rmtree(root)


def test_lod_api_queues_job_and_returns_manifest(client, monkeypatch):
    owner = User(username="lodowner", email="lod@example.com")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model = UserModel(
        id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        filename="unused.glb", user_id=owner.id,
    )
    db.session.add(model)
    db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    response = client.post(f"/api/models/{model.id}/lods", json={
        "ratios": [0.6, 0.3], "meshopt": True,
    })
    assert response.status_code == 202
    job = db.session.get(ConversionJob, response.get_json()["job_id"])
    assert job.job_type == "lod"
    assert job.payload["ratios"] == [0.6, 0.3]
    assert response.get_json()["status_token"]

    db.session.add(ModelLOD(
        model_id=model.id, level=1, ratio=0.6,
        filename="converted/model_lod1.glb", file_size=123,
    ))
    db.session.commit()
    manifest = client.get(f"/api/models/{model.id}/lods").get_json()["lods"]
    assert manifest[0]["url"].endswith("/model_lod1.glb")


def test_meshopt_can_be_forced_per_upload(monkeypatch):
    root = Path(".test-optimize.glb").resolve()
    root.write_bytes(b"x" * 100)
    monkeypatch.setattr(glb_optimizer, "_resolve_gltfpack", lambda: ["gltfpack"])

    def fake_run(args, **kwargs):
        Path(str(root) + ".opt.glb").write_bytes(b"y" * 20)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(glb_optimizer.subprocess, "run", fake_run)
    assert glb_optimizer.optimize_glb(str(root), enabled=True)
    assert root.stat().st_size == 20
    assert not glb_optimizer.optimize_glb(str(root), enabled=False)
    root.unlink(missing_ok=True)


def test_draco_can_be_selected_per_upload(monkeypatch):
    root = Path(".test-draco.glb").resolve()
    root.write_bytes(b"x" * 100)
    monkeypatch.setattr(glb_optimizer, "_resolve_gltf_transform", lambda: ["gltf-transform"])
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        Path(str(root) + ".opt.glb").write_bytes(b"z" * 25)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(glb_optimizer.subprocess, "run", fake_run)
    assert glb_optimizer.optimize_glb(str(root), enabled=True, mode="draco")
    assert captured["args"][-2:] == ["--compress", "draco"]
    root.unlink(missing_ok=True)
