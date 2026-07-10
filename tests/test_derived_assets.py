import io
import shutil
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from pygltflib import GLTF2

import app as app_module
from converters.texture_upscale import upscale_embedded_textures
from models import ConversionJob, User, UserModel, db


def _textured_glb(path):
    mesh = trimesh.creation.box()
    uv = np.zeros((len(mesh.vertices), 2))
    uv[:, 0] = (mesh.vertices[:, 0] + 0.5)
    uv[:, 1] = (mesh.vertices[:, 1] + 0.5)
    image = Image.new("RGB", (8, 8), (220, 30, 30))
    material = trimesh.visual.material.SimpleMaterial(image=image)
    mesh.visual = trimesh.visual.texture.TextureVisuals(uv=uv, material=material)
    mesh.export(path)


def test_embedded_texture_upscale_rebuilds_glb_buffer_views():
    root = Path(".test-upscale").resolve(); root.mkdir(exist_ok=True)
    source = root / "source.glb"; output = root / "upscaled.glb"
    _textured_glb(source)
    report = upscale_embedded_textures(source, output, factor=2)
    assert report["textures_upscaled"] >= 1
    assert report["textures"][0]["to"] == [16, 16]
    gltf = GLTF2().load(output)
    assert gltf.images[0].bufferView is not None
    shutil.rmtree(root)


def test_derived_asset_api_queues_retopology_and_upscale(client, monkeypatch):
    owner = User(username="deriveowner", email="derive@example.com")
    owner.set_password("password")
    db.session.add(owner); db.session.flush()
    model = UserModel(
        id="40404040-4040-4040-4040-404040404040",
        filename="unused.glb", user_id=owner.id,
    )
    db.session.add(model); db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    first = client.post(f"/api/models/{model.id}/derivatives", json={
        "kind": "retopology", "ratio": 0.6,
    })
    second = client.post(f"/api/models/{model.id}/derivatives", json={
        "kind": "texture_upscale", "factor": 4,
    })
    assert first.status_code == second.status_code == 202
    jobs = ConversionJob.query.order_by(ConversionJob.created_at).all()
    assert {job.job_type for job in jobs} == {"retopology", "texture_upscale"}
    assert all(job.status_token_hash for job in jobs)
    assert client.post(
        f"/api/models/{model.id}/derivatives", json={"kind": "texture_upscale", "factor": 3}
    ).status_code == 400
