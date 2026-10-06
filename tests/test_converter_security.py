"""Untrusted-upload path-safety tests for the converters (OPS-21).

OBJ/MTL references, GLB/FBX external texture URIs and the path helpers in
converters/base_converter.py must never let an uploaded file make the server
read (and embed into the served GLB) anything outside the upload directory.
"""

import os

import pytest
import trimesh
from PIL import Image
from pygltflib import GLTF2, Image as GltfImage

from converters import obj_converter
from converters.base_converter import safe_join_within, safe_texture_ext
from converters.fbx_converter import FBXConverter
from converters.glb_quality import embed_external_textures
from converters.obj_converter import OBJConverter, assert_safe_obj_references


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    return path


def _obj(tmp_path, mtllib="model.mtl", mtl_body="newmtl m\nKd 1 1 1\n"):
    obj = _write(tmp_path / "model.obj",
                 f"mtllib {mtllib}\nusemtl m\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    if mtl_body is not None:
        _write(tmp_path / "model.mtl", mtl_body)
    return obj


# --------------------------------------------------------------------------
# OBJ / MTL reference scanning
# --------------------------------------------------------------------------

def test_clean_obj_and_mtl_are_accepted(tmp_path):
    obj = _obj(tmp_path, mtl_body=(
        "newmtl m\nKd 1 1 1\nmap_Kd diffuse.png\nmap_Bump -bm 1.0 textures/normal.png\n"
        "map_Pr rough.jpg\nbump bump.png\n"))
    assert_safe_obj_references(str(obj))  # does not raise


@pytest.mark.parametrize("mtllib", [
    "../../etc/passwd",
    "/etc/passwd",
    "..\\..\\etc\\passwd",
    "~/secrets.mtl",
    "sub/../../x.mtl",
    "ok.mtl ../evil.mtl",           # second of several libraries
])
def test_mtllib_traversal_is_rejected(tmp_path, mtllib):
    obj = _obj(tmp_path, mtllib=mtllib, mtl_body=None)
    with pytest.raises(ValueError, match="mtllib"):
        assert_safe_obj_references(str(obj))


@pytest.mark.parametrize("directive", [
    "map_Kd ../../../../etc/passwd",
    "map_Kd /etc/passwd",
    "map_Kd ..\\..\\secret.png",
    "map_Kd C:/../../secret.png",
    "map_Kd -s 1 1 1 -o 0 0 0 /etc/passwd",   # options before the path
    "map_Ks ../x.png",
    "map_Pr /abs/rough.png",                   # PBR map extension keys
    "map_Pm ../metal.png",
    "map_ns ../../gloss.png",
    "map_d ../alpha.png",
    "MAP_KD ../upper.png",                     # keys are case-insensitive
    "bump ../bump.png",
    "disp /abs/disp.png",
    "decal ../decal.png",
    "refl ../refl.png",
    "norm /abs/norm.png",
    "map_Kd ~/secret.png",
])
def test_mtl_texture_traversal_is_rejected(tmp_path, directive):
    obj = _obj(tmp_path, mtl_body=f"newmtl m\n{directive}\n")
    with pytest.raises(ValueError, match="Unsafe file reference"):
        assert_safe_obj_references(str(obj))


@pytest.mark.parametrize("path_with_space", [
    "/srv/my secrets/data.png",       # absolute path whose last token looks safe
    "../my dir/pic.png",
])
def test_mtl_texture_path_with_spaces_cannot_hide_traversal(tmp_path, path_with_space):
    obj = _obj(tmp_path, mtl_body=f"newmtl m\nmap_Kd {path_with_space}\n")
    with pytest.raises(ValueError):
        assert_safe_obj_references(str(obj))


def test_mtl_reference_check_ignores_unreadable_or_missing_mtl(tmp_path):
    obj = _obj(tmp_path, mtllib="absent.mtl", mtl_body=None)
    assert_safe_obj_references(str(obj))  # nothing to scan, nothing to reject


def test_mtl_is_resolved_by_basename_inside_obj_dir(tmp_path):
    # `mtllib sub/evil.mtl` is contained (basename only), but a malicious MTL
    # sitting next to the OBJ is still scanned.
    (tmp_path / "sub").mkdir()
    obj = _obj(tmp_path, mtllib="sub/model.mtl",
               mtl_body="newmtl m\nmap_Kd ../../escape.png\n")
    with pytest.raises(ValueError, match="Unsafe file reference"):
        assert_safe_obj_references(str(obj))


def test_obj_converter_rejects_before_running_obj2gltf(tmp_path, monkeypatch):
    obj = _obj(tmp_path, mtl_body="newmtl m\nmap_Kd /etc/passwd\n")

    def must_not_run(*args, **kwargs):
        raise AssertionError("obj2gltf must not be invoked for an unsafe OBJ")

    monkeypatch.setattr(obj_converter.subprocess, "run", must_not_run)
    out = tmp_path / "out" / "model.glb"
    converter = OBJConverter()
    assert converter.convert(str(obj), str(out)) is False
    assert not out.exists()
    assert any("Unsafe file reference" in err for err in converter.errors)


def test_obj_converter_rejects_absolute_mtllib(tmp_path, monkeypatch):
    obj = _obj(tmp_path, mtllib="/etc/passwd", mtl_body=None)
    monkeypatch.setattr(obj_converter.subprocess, "run",
                        lambda *a, **k: pytest.fail("obj2gltf must not run"))
    converter = OBJConverter()
    assert converter.convert(str(obj), str(tmp_path / "o.glb")) is False
    assert converter.errors


# --------------------------------------------------------------------------
# base_converter helpers
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "", None, ".", "..", "../", "/", "a/..", "dir/", "..\\", "x/y/.",
])
def test_safe_join_within_rejects_degenerate_names(tmp_path, name):
    assert safe_join_within(str(tmp_path), name) is None


@pytest.mark.parametrize("name", [
    "../../etc/passwd", "/etc/passwd", "..\\..\\windows\\win.ini",
    "sub/../../../etc/passwd", "a/b/c.png",
])
def test_safe_join_within_collapses_to_leaf_inside_base(tmp_path, name):
    result = safe_join_within(str(tmp_path), name)
    assert result is not None
    assert os.path.dirname(result) == os.path.realpath(tmp_path)
    assert os.path.basename(result) == os.path.basename(name.replace("\\", "/"))


def test_safe_join_within_refuses_symlink_escaping_base(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    (base / "link.png").symlink_to(outside)
    assert safe_join_within(str(base), "link.png") is None
    (base / "real.png").write_bytes(b"x")
    assert safe_join_within(str(base), "real.png") == os.path.realpath(base / "real.png")


@pytest.mark.parametrize("hint,expected", [
    ("png", ".png"), (".JPG", ".jpg"), ("jpeg", ".jpeg"), ("webp", ".webp"),
    ("../../x", ".png"), ("png/../../etc", ".png"), ("exe", ".png"),
    ("", ".png"), (None, ".png"), ("php\x00.png", ".png"),
])
def test_safe_texture_ext_only_returns_known_image_extensions(hint, expected):
    assert safe_texture_ext(hint) == expected


# --------------------------------------------------------------------------
# External texture URIs in GLB / FBX output
# --------------------------------------------------------------------------

def _glb_with_external_image(path, uri):
    mesh = trimesh.creation.box()
    gltf = GLTF2().load_from_bytes(trimesh.Scene([mesh]).export(file_type="glb"))
    gltf.images = [GltfImage(uri=uri)]
    gltf.save(path)


def _secret_png(path):
    Image.new("RGB", (3, 3), (200, 10, 10)).save(path)
    return path.read_bytes()


@pytest.fixture
def sandbox(tmp_path):
    """upload dir with a GLB, and a secret PNG that lives OUTSIDE it."""
    upload = tmp_path / "upload"
    upload.mkdir()
    secret = tmp_path / "secret.png"
    _secret_png(secret)
    return upload, secret


def _image_state(glb_path):
    image = GLTF2().load(glb_path).images[0]
    return image.uri, image.bufferView


@pytest.mark.parametrize("uri_for", [
    lambda secret: "../secret.png",
    lambda secret: "..\\secret.png",
    lambda secret: str(secret),                      # absolute path
    lambda secret: "sub/../../secret.png",
])
def test_glb_external_texture_outside_upload_dir_is_not_embedded(sandbox, uri_for):
    upload, secret = sandbox
    glb = upload / "model.glb"
    uri = uri_for(secret)
    _glb_with_external_image(glb, uri)

    assert embed_external_textures(str(glb), [str(upload)]) is False
    stored_uri, buffer_view = _image_state(glb)
    assert stored_uri == uri and buffer_view is None


def test_glb_external_texture_inside_upload_dir_is_embedded(sandbox):
    upload, _ = sandbox
    glb = upload / "model.glb"
    _secret_png(upload / "paint.png")
    _glb_with_external_image(glb, "paint.png")
    assert embed_external_textures(str(glb), [str(upload)]) is True
    stored_uri, buffer_view = _image_state(glb)
    assert stored_uri is None and buffer_view is not None


def test_glb_traversal_uri_resolves_only_to_same_named_file_inside_dir(sandbox):
    # `../secret.png` degrades to the *basename*, so a same-named file inside
    # the upload dir is what gets used -- never the one outside it.
    upload, secret = sandbox
    glb = upload / "model.glb"
    inside = upload / "secret.png"
    Image.new("RGB", (3, 3), (1, 2, 3)).save(inside)
    _glb_with_external_image(glb, "../secret.png")
    assert embed_external_textures(str(glb), [str(upload)]) is True
    reloaded = GLTF2().load(glb)
    blob = reloaded.binary_blob()
    view = reloaded.bufferViews[reloaded.images[0].bufferView]
    embedded = blob[view.byteOffset:view.byteOffset + view.byteLength]
    assert embedded == inside.read_bytes()
    assert embedded != secret.read_bytes()


def _fbx_converter():
    converter = FBXConverter.__new__(FBXConverter)
    converter.log_operation = lambda *args, **kwargs: None
    return converter


@pytest.mark.parametrize("uri_for", [
    lambda secret: "../secret.png",
    lambda secret: str(secret),
    lambda secret: "..\\..\\secret.png",
])
def test_fbx_postprocess_does_not_embed_external_texture_outside_dir(sandbox, uri_for):
    upload, secret = sandbox
    glb = upload / "model.glb"
    fbx = upload / "model.fbx"
    fbx.write_bytes(b"placeholder")
    uri = uri_for(secret)
    _glb_with_external_image(glb, uri)

    _fbx_converter()._embed_external_textures(str(glb), str(fbx))

    stored_uri, buffer_view = _image_state(glb)
    assert buffer_view is None
    assert not (stored_uri or "").startswith("data:")
    assert secret.read_bytes() not in glb.read_bytes()


@pytest.mark.parametrize("source_for", [
    lambda secret: "../secret.png",
    lambda secret: str(secret),
])
def test_fbx_material_texture_source_outside_dir_is_not_recovered(sandbox, source_for):
    """pyassimp-reported texture paths come from the uploaded FBX and must be
    contained exactly like image URIs."""
    upload, secret = sandbox
    glb = upload / "model.glb"
    fbx = upload / "model.fbx"
    fbx.write_bytes(b"placeholder")
    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(baseColorFactor=[1, 1, 1, 1]))
    gltf = GLTF2().load_from_bytes(trimesh.Scene([mesh]).export(file_type="glb"))
    gltf.materials[0].name = "Paint"
    gltf.save(glb)

    converter = _fbx_converter()
    converter._fbx_material_textures = {"Paint": source_for(secret)}
    converter._embed_external_textures(str(glb), str(fbx))

    reloaded = GLTF2().load(glb)
    assert not reloaded.images
    assert reloaded.materials[0].pbrMetallicRoughness.baseColorTexture is None


def test_fbx_material_texture_source_inside_dir_is_recovered(sandbox):
    """Positive control for the test above."""
    upload, _ = sandbox
    glb = upload / "model.glb"
    fbx = upload / "model.fbx"
    fbx.write_bytes(b"placeholder")
    _secret_png(upload / "paint.png")
    mesh = trimesh.creation.box()
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(baseColorFactor=[1, 1, 1, 1]))
    gltf = GLTF2().load_from_bytes(trimesh.Scene([mesh]).export(file_type="glb"))
    gltf.materials[0].name = "Paint"
    gltf.save(glb)

    converter = _fbx_converter()
    converter._fbx_material_textures = {"Paint": "paint.png"}
    converter._embed_external_textures(str(glb), str(fbx))

    reloaded = GLTF2().load(glb)
    assert reloaded.images and reloaded.materials[0].pbrMetallicRoughness.baseColorTexture
