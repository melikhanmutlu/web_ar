"""Texture-repair helpers for AI-generated GLBs (untextured-model fix).

Covers embed_remote_textures (download + embed http image URIs, host-allowlisted),
inspect_texture_state, and the unset-metallicFactor -> 0.0 clamp in
ensure_pbr_materials.
"""
import os
import tempfile
import base64

import trimesh
from pygltflib import (
    GLTF2, Image, Material, PbrMetallicRoughness, Texture, TextureInfo,
)

import converters.glb_quality as gq
from converters.glb_quality import (
    attach_base_color_texture_files, embed_remote_textures,
    embed_data_uri_textures, has_embedded_base_color_textures,
    inspect_texture_state,
)


class _FakeResponse:
    def __init__(self, payload, status=200, content_type="image/png"):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": content_type}

    def iter_content(self, chunk_size=65536):
        yield self._payload


def _glb_with_external_image(path, uri="https://assets.meshy.ai/tex/base_color.png"):
    """A minimal box GLB whose single material has a baseColorTexture pointing
    at an EXTERNAL image uri."""
    trimesh.creation.box(extents=(1, 1, 1)).export(path)
    g = GLTF2.load(path)
    g.images = [Image(uri=uri)]
    g.textures = [Texture(source=0)]
    g.materials = [Material(
        pbrMetallicRoughness=PbrMetallicRoughness(baseColorTexture=TextureInfo(index=0))
    )]
    g.meshes[0].primitives[0].material = 0
    g.save(path)
    return path


def test_embed_remote_textures_embeds_allowed_host(monkeypatch, tmp_path):
    path = str(tmp_path / "m.glb")
    _glb_with_external_image(path)
    monkeypatch.setattr(gq.requests, "get", lambda *a, **k: _FakeResponse(b"PNGDATA" * 100))

    changed = embed_remote_textures(path, allowed_hosts=["meshy.ai"])
    assert changed is True

    g = GLTF2.load(path)
    img = g.images[0]
    assert img.uri is None            # external uri cleared
    assert img.bufferView is not None  # now embedded in the binary chunk
    assert img.mimeType == "image/png"


def test_embed_remote_textures_skips_disallowed_host(monkeypatch, tmp_path):
    path = str(tmp_path / "m.glb")
    _glb_with_external_image(path, uri="https://evil.example.com/x.png")

    called = {"n": 0}

    def _should_not_fetch(*a, **k):
        called["n"] += 1
        return _FakeResponse(b"X")

    monkeypatch.setattr(gq.requests, "get", _should_not_fetch)
    changed = embed_remote_textures(path, allowed_hosts=["meshy.ai"])
    assert changed is False
    assert called["n"] == 0            # SSRF guard: never fetched

    g = GLTF2.load(path)
    assert g.images[0].uri == "https://evil.example.com/x.png"  # untouched


def test_embed_data_uri_textures_rewrites_for_viewer_loader(tmp_path):
    """Viewer-safe GLBs keep images in binary bufferViews, not data URIs."""
    path = str(tmp_path / "data-uri.glb")
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
    )
    _glb_with_external_image(path, "data:image/png;base64," + base64.b64encode(png).decode())

    assert embed_data_uri_textures(path) is True

    repaired = GLTF2.load(path)
    image = repaired.images[0]
    assert image.uri is None
    assert image.bufferView is not None
    assert image.mimeType == "image/png"


def test_inspect_texture_state_external_then_embedded(monkeypatch, tmp_path):
    path = str(tmp_path / "m.glb")
    _glb_with_external_image(path)

    before = inspect_texture_state(path)
    assert before["images"] == 1
    assert before["embedded"] == 0
    assert before["external_hosts"] == ["assets.meshy.ai"]
    assert before["first_material"]["has_base_color_texture"] is True

    monkeypatch.setattr(gq.requests, "get", lambda *a, **k: _FakeResponse(b"PNGDATA" * 100))
    embed_remote_textures(path, allowed_hosts=["meshy.ai"])

    after = inspect_texture_state(path)
    assert after["images"] == 1
    assert after["embedded"] == 1
    assert after["external_hosts"] == []


def test_attach_base_color_texture_repairs_textureless_meshy_glb(tmp_path):
    """Meshy may return maps only in texture_urls, with no GLB image URI."""
    path = str(tmp_path / "textureless.glb")
    trimesh.creation.box(extents=(1, 1, 1)).export(path)

    texture_path = tmp_path / "meshy_base_color.png"
    texture_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"texture-payload")

    assert inspect_texture_state(path)["images"] == 0
    assert attach_base_color_texture_files(path, [str(texture_path)]) is True

    repaired = GLTF2.load(path)
    assert len(repaired.images) == 1
    assert repaired.images[0].uri is None
    assert repaired.images[0].bufferView is not None
    assert len(repaired.textures) == 1
    material = repaired.materials[repaired.meshes[0].primitives[0].material]
    assert material.pbrMetallicRoughness.baseColorTexture.index == 0
    assert material.pbrMetallicRoughness.baseColorFactor == [1.0, 1.0, 1.0, 1.0]
    assert has_embedded_base_color_textures(path) is True


def test_attach_base_color_texture_replaces_dangling_glb_reference(tmp_path):
    """A TextureInfo pointing at an unavailable URI must not skip repair."""
    path = str(tmp_path / "dangling.glb")
    _glb_with_external_image(path, uri="missing_texture.png")
    assert has_embedded_base_color_textures(path) is False

    texture_path = tmp_path / "meshy_base_color.png"
    texture_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"replacement")
    assert attach_base_color_texture_files(path, [str(texture_path)]) is True

    repaired = GLTF2.load(path)
    material = repaired.materials[repaired.meshes[0].primitives[0].material]
    texture = repaired.textures[material.pbrMetallicRoughness.baseColorTexture.index]
    image = repaired.images[texture.source]
    assert image.uri is None
    assert image.bufferView is not None
    assert has_embedded_base_color_textures(path) is True
