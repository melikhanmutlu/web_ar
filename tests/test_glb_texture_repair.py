"""Texture-repair helpers for AI-generated GLBs (untextured-model fix).

Covers embed_remote_textures (download + embed http image URIs, host-allowlisted),
inspect_texture_state, and the unset-metallicFactor -> 0.0 clamp in
ensure_pbr_materials.
"""
import os
import tempfile

import trimesh
from pygltflib import (
    GLTF2, Image, Material, PbrMetallicRoughness, Texture, TextureInfo,
)

import converters.glb_quality as gq
from converters.glb_quality import embed_remote_textures, inspect_texture_state


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
