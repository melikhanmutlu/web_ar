"""Tests for the software thumbnail rasterizer (converters/thumbnail_render)."""

import numpy as np
import trimesh

from converters import thumbnail_render
from converters.thumbnail_render import render_thumbnail


def _make_glb(tmp_path, mesh, name="model.glb"):
    path = tmp_path / name
    trimesh.Scene([mesh]).export(str(path), file_type="glb")
    return str(path)


def test_renders_real_geometry(tmp_path):
    box = trimesh.creation.box(extents=[1, 0.5, 0.3])
    glb = _make_glb(tmp_path, box)
    out = tmp_path / "thumb.png"

    assert render_thumbnail(glb, str(out)) is True
    assert out.exists()

    from PIL import Image

    img = np.asarray(Image.open(out).convert("RGB"))
    assert img.shape[:2] == thumbnail_render.THUMBNAIL_SIZE
    # The model must actually be drawn: a meaningful share of pixels differ
    # from the flat background.
    bg = np.array(thumbnail_render.BG_COLOR[:3])
    non_bg = (np.abs(img.astype(int) - bg).sum(axis=2) > 10).mean()
    assert non_bg > 0.05


def test_uses_vertex_colors(tmp_path):
    box = trimesh.creation.box(extents=[1, 1, 1])
    vertex_colors = np.tile([255, 0, 0, 255], (len(box.vertices), 1))
    box.visual = trimesh.visual.ColorVisuals(
        vertex_colors=vertex_colors.astype(np.uint8)
    )
    glb = _make_glb(tmp_path, box)
    out = tmp_path / "thumb.png"

    assert render_thumbnail(glb, str(out)) is True

    from PIL import Image

    img = np.asarray(Image.open(out).convert("RGB")).astype(int)
    # Red model on a neutral background: red channel must dominate on a
    # meaningful share of pixels.
    reddish = ((img[:, :, 0] - img[:, :, 1] > 50) & (img[:, :, 0] - img[:, :, 2] > 50)).mean()
    assert reddish > 0.05


def test_face_limit_skips_render(tmp_path, monkeypatch):
    monkeypatch.setattr(thumbnail_render, "MAX_RENDER_FACES", 5)
    box = trimesh.creation.box(extents=[1, 1, 1])  # 12 faces > 5
    glb = _make_glb(tmp_path, box)
    out = tmp_path / "thumb.png"

    assert render_thumbnail(glb, str(out)) is False
    assert not out.exists()


def test_missing_file_returns_false(tmp_path):
    out = tmp_path / "thumb.png"
    assert render_thumbnail(str(tmp_path / "nope.glb"), str(out)) is False
    assert not out.exists()
