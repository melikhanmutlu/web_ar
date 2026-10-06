"""P3D-17: heavy and compressed models get a real thumbnail; when a real
render is impossible a PNG placeholder is cached on disk."""

import os
import uuid

import numpy as np
import pytest
import trimesh
from PIL import Image

from app import app, db
from converters import glb_optimizer, thumbnail_render
from converters.thumbnail_render import render_thumbnail
from models import UserModel

needs_gltfpack = pytest.mark.skipif(
    glb_optimizer._resolve_gltfpack() is None, reason="gltfpack unavailable"
)


@needs_gltfpack
def test_model_over_face_limit_renders_from_decimated_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail_render, "MAX_RENDER_FACES", 1000)
    monkeypatch.setattr(thumbnail_render, "DECIMATED_TARGET_FACES", 800)
    glb = tmp_path / "heavy.glb"
    trimesh.creation.icosphere(subdivisions=5).export(glb)  # 20480 faces
    out = tmp_path / "thumb.png"

    assert render_thumbnail(str(glb), str(out)) is True

    img = np.asarray(Image.open(out).convert("RGB"))
    background = np.array(thumbnail_render.BG_COLOR[:3])
    assert (np.abs(img.astype(int) - background).sum(axis=2) > 30).mean() > 0.1


@needs_gltfpack
def test_draco_model_renders_real_thumbnail(tmp_path):
    glb = tmp_path / "draco.glb"
    trimesh.creation.icosphere(subdivisions=3).export(glb)
    if glb_optimizer._resolve_gltf_transform() is None:
        pytest.skip("gltf-transform unavailable")
    if not glb_optimizer.optimize_glb(str(glb), enabled=True, mode="draco"):
        pytest.skip("draco compression unavailable")
    assert glb_optimizer.glb_compression_mode(str(glb)) == "draco"
    out = tmp_path / "thumb.png"
    assert render_thumbnail(str(glb), str(out)) is True


def test_placeholder_is_cached_as_png_and_not_re_rendered(client, monkeypatch):
    model_id = str(uuid.uuid4())
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.box().export(glb_path)
    db.session.add(UserModel(id=model_id, filename=glb_path, file_type="glb", file_size=1,
                             user_id=None, cumulative_scale=1.0, visibility="public",
                             color="#336699"))
    db.session.commit()

    calls = []
    monkeypatch.setattr(thumbnail_render, "render_thumbnail",
                        lambda *a, **k: calls.append(a) or False)

    first = client.get(f"/thumbnail/{model_id}")
    assert first.status_code == 200
    assert first.mimetype == "image/png"
    assert "max-age" in first.headers.get("Cache-Control", "")
    assert os.path.exists(os.path.join(model_dir, thumbnail_render.PLACEHOLDER_FILENAME))
    assert Image.open(__import__("io").BytesIO(first.data)).size == (256, 256)

    second = client.get(f"/thumbnail/{model_id}")
    assert second.status_code == 200 and second.mimetype == "image/png"
    assert len(calls) == 1, "placeholder must be served from disk, not re-rendered"
