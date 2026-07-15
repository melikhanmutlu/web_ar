"""GLB post-processing and quality checks for converted model assets.

Ported from academic_ar. Three layers, all idempotent:

1. embed_external_textures — pack file-based image URIs into the GLB binary
   chunk (FBX2glTF/obj2gltf can leave relative texture paths; the viewer and
   AR resolvers serve a single GLB file).
2. ensure_pbr_materials — every primitive gets a valid PBR material without
   replacing existing artwork; neutral gray default only where missing.
3. validate_glb_quality — sanity gate (parses, has meshes/POSITION/materials,
   no dangling external texture refs). Used in WARN mode by default so a
   borderline-but-viewable model still publishes; strict mode raises.
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlparse

import requests
from pygltflib import (
    Buffer, BufferView, GLTF2, Image, Material, PbrMetallicRoughness,
    Texture, TextureInfo,
)

logger = logging.getLogger(__name__)

# Cap a single downloaded texture so a hostile/broken URL can't exhaust memory.
_MAX_REMOTE_TEXTURE_BYTES = 32 * 1024 * 1024


class GLBQualityError(ValueError):
    """Raised when a converted GLB is not safe to publish."""


def _load_glb(path: str) -> GLTF2:
    if not os.path.exists(path):
        raise GLBQualityError("GLB output was not created.")
    if os.path.getsize(path) < 20:
        raise GLBQualityError("GLB output is empty or too small.")
    with open(path, "rb") as handle:
        if handle.read(4) != b"glTF":
            raise GLBQualityError("GLB header is invalid.")
    try:
        return GLTF2.load(path)
    except Exception as exc:  # pragma: no cover - exact parser messages vary
        raise GLBQualityError(f"GLB could not be parsed: {exc}") from exc


def _mime_for(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "image/png"


def _append_blob(gltf: GLTF2, payload: bytes) -> int:
    blob = gltf.binary_blob() or b""
    padding = b"\x00" * ((4 - (len(blob) % 4)) % 4)
    offset = len(blob) + len(padding)
    gltf.set_binary_blob(blob + padding + payload)
    if not gltf.buffers:
        gltf.buffers = [Buffer(byteLength=0)]
    gltf.buffers[0].byteLength = len(gltf.binary_blob() or b"")
    return offset


def _find_texture(uri: str, search_dirs: list) -> "Path | None":
    candidates = []
    uri_path = Path(uri.replace("\\", "/"))
    for directory in search_dirs:
        root = Path(directory)
        candidates.append(root / uri_path)
        candidates.append(root / uri_path.name)
    lower_name = uri_path.name.lower()
    for directory in search_dirs:
        root = Path(directory)
        if root.exists():
            for entry in root.rglob("*"):
                if entry.is_file() and entry.name.lower() == lower_name:
                    candidates.append(entry)
                    break
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def embed_external_textures(glb_path: str, search_dirs: list = None) -> bool:
    """Embed file-based image URIs into the GLB binary chunk."""
    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError:
        return False
    if not gltf.images:
        return False

    search_dirs = search_dirs or [os.path.dirname(glb_path)]
    if gltf.bufferViews is None:
        gltf.bufferViews = []

    changed = False
    for image in gltf.images:
        uri = image.uri
        if not uri or uri.startswith("data:") or image.bufferView is not None:
            continue
        texture_path = _find_texture(uri, search_dirs)
        if not texture_path:
            logger.warning(f"External texture not found, leaving as-is: {uri}")
            continue
        payload = texture_path.read_bytes()
        offset = _append_blob(gltf, payload)
        view = BufferView(buffer=0, byteOffset=offset, byteLength=len(payload))
        image.bufferView = len(gltf.bufferViews)
        image.mimeType = _mime_for(texture_path)
        image.uri = None
        gltf.bufferViews.append(view)
        changed = True

    if changed:
        gltf.save(glb_path)
    return changed


def embed_data_uri_textures(glb_path: str) -> bool:
    """Move image data URIs into GLB bufferViews.

    A data URI is legal glTF, but the model-viewer/THREE loader used by the
    web Viewer can fail to load it when it appears inside a binary GLB. The
    failure leaves the model geometry visible but all affected materials white.
    BufferView images are the native, self-contained GLB representation.
    """
    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError:
        return False
    if not gltf.images:
        return False
    if gltf.bufferViews is None:
        gltf.bufferViews = []

    changed = False
    for image in gltf.images:
        uri = image.uri or ""
        if not uri.startswith("data:"):
            continue
        try:
            header, encoded = uri.split(",", 1)
            payload = base64.b64decode(encoded, validate=True)
            mime_type = header[5:].split(";", 1)[0] or "image/png"
        except (ValueError, IndexError, base64.binascii.Error) as exc:
            logger.warning("Leaving malformed texture data URI untouched: %s", exc)
            continue
        if not payload:
            logger.warning("Leaving empty texture data URI untouched")
            continue
        offset = _append_blob(gltf, payload)
        gltf.bufferViews.append(
            BufferView(buffer=0, byteOffset=offset, byteLength=len(payload))
        )
        image.bufferView = len(gltf.bufferViews) - 1
        image.mimeType = mime_type
        image.uri = None
        changed = True

    if changed:
        gltf.save(glb_path)
    return changed


def attach_base_color_texture_files(glb_path: str, texture_paths: list) -> bool:
    """Embed standalone base-color maps and bind them to GLB materials.

    Meshy can return a valid GLB with materials but no image/texture references,
    while exposing the PBR maps separately through ``texture_urls``. Merely
    downloading those files beside the GLB cannot repair that shape because
    :func:`embed_external_textures` has no URI to resolve. This helper creates
    the missing image/texture graph explicitly and keeps the result as a
    self-contained GLB.

    Texture files are matched to materials by position. If Meshy supplies one
    base-color map for several materials, that map is reused for each material.
    Existing, usable embedded base-color assignments are never replaced;
    dangling/external assignments are repaired.
    """
    paths = [Path(path) for path in (texture_paths or []) if path and Path(path).is_file()]
    if not paths:
        return False

    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError:
        return False

    if gltf.bufferViews is None:
        gltf.bufferViews = []
    if gltf.images is None:
        gltf.images = []
    if gltf.textures is None:
        gltf.textures = []
    if gltf.materials is None:
        gltf.materials = []

    texture_indices = []
    for path in paths:
        payload = path.read_bytes()
        if not payload or len(payload) > _MAX_REMOTE_TEXTURE_BYTES:
            logger.warning("Skipping invalid base-color texture file: %s", path)
            continue
        offset = _append_blob(gltf, payload)
        gltf.bufferViews.append(
            BufferView(buffer=0, byteOffset=offset, byteLength=len(payload))
        )
        gltf.images.append(
            Image(bufferView=len(gltf.bufferViews) - 1, mimeType=_mime_for(path))
        )
        gltf.textures.append(Texture(source=len(gltf.images) - 1))
        texture_indices.append(len(gltf.textures) - 1)

    if not texture_indices:
        return False

    # A texture-less GLB may also omit materials entirely. Create a valid PBR
    # target and attach otherwise-unassigned primitives to it.
    changed = False
    if not gltf.materials:
        gltf.materials.append(Material(name="Meshy_BaseColor", doubleSided=True))
        changed = True

    for material_index, material in enumerate(gltf.materials):
        if material.pbrMetallicRoughness is None:
            material.pbrMetallicRoughness = PbrMetallicRoughness()
            changed = True
        pbr = material.pbrMetallicRoughness
        if not _texture_info_is_embedded(gltf, pbr.baseColorTexture):
            texture_index = texture_indices[min(material_index, len(texture_indices) - 1)]
            pbr.baseColorTexture = TextureInfo(index=texture_index)
            # baseColorFactor multiplies the sampled texture; force a neutral
            # factor so a stale/default tint cannot wash out Meshy's artwork.
            pbr.baseColorFactor = [1.0, 1.0, 1.0, 1.0]
            changed = True

    for mesh in gltf.meshes or []:
        for primitive in mesh.primitives or []:
            if primitive.material is None or primitive.material >= len(gltf.materials):
                primitive.material = 0
                changed = True

    if changed:
        gltf.save(glb_path)
    return changed


def _host_allowed(url: str, allowed_hosts: list) -> bool:
    """True if url's host equals or is a subdomain of an allowed host."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    for pattern in allowed_hosts or []:
        p = (pattern or "").lower().lstrip(".")
        if p and (host == p or host.endswith("." + p)):
            return True
    return False


def embed_remote_textures(glb_path: str, allowed_hosts: list) -> bool:
    """Download http(s) image URIs referenced by the GLB and embed them into the
    binary chunk, making the model self-contained.

    Only fetches from `allowed_hosts` (SSRF guard) -- intended for GLBs from a
    trusted source (e.g. Meshy) whose textures are hosted on a known CDN and
    would otherwise be lost (CSP/CORS) or expire (signed URLs). Best-effort:
    any failure leaves the image as-is.
    """
    if not allowed_hosts:
        return False
    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError:
        return False
    if not gltf.images:
        return False
    if gltf.bufferViews is None:
        gltf.bufferViews = []

    changed = False
    for image in gltf.images:
        uri = image.uri
        if not uri or image.bufferView is not None:
            continue
        if not uri.lower().startswith(("http://", "https://")):
            continue
        if not _host_allowed(uri, allowed_hosts):
            logger.warning(f"Remote texture host not allowed, skipping: {uri}")
            continue
        try:
            resp = requests.get(uri, stream=True, timeout=60)
            if resp.status_code >= 400:
                logger.warning(f"Remote texture fetch failed {resp.status_code}: {uri}")
                continue
            payload = b""
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                payload += chunk
                if len(payload) > _MAX_REMOTE_TEXTURE_BYTES:
                    raise ValueError("remote texture exceeds size cap")
        except Exception as exc:
            logger.warning(f"Remote texture fetch error for {uri}: {exc}")
            continue

        offset = _append_blob(gltf, payload)
        view = BufferView(buffer=0, byteOffset=offset, byteLength=len(payload))
        image.bufferView = len(gltf.bufferViews)
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        image.mimeType = content_type if content_type.startswith("image/") else "image/png"
        image.uri = None
        gltf.bufferViews.append(view)
        changed = True

    if changed:
        gltf.save(glb_path)
    return changed


def inspect_texture_state(glb_path: str) -> dict:
    """A small, log-friendly summary of a GLB's texture/material state.

    Used to diagnose why an AI-generated model rendered untextured: whether it
    has any images, whether they're embedded vs referenced externally (and from
    which host), and the first material's key PBR factors.
    """
    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError as exc:
        return {"error": str(exc)}
    images = gltf.images or []
    embedded = 0
    external_hosts = []
    for im in images:
        uri = im.uri or ""
        if im.bufferView is not None or uri.startswith("data:"):
            embedded += 1
        elif uri:
            try:
                external_hosts.append((urlparse(uri).hostname or uri[:48]))
            except Exception:
                external_hosts.append(uri[:48])
    materials = gltf.materials or []
    first = {}
    if materials:
        pbr = materials[0].pbrMetallicRoughness
        first = {
            "baseColorFactor": getattr(pbr, "baseColorFactor", None) if pbr else None,
            "metallicFactor": getattr(pbr, "metallicFactor", None) if pbr else None,
            "has_base_color_texture": bool(pbr and pbr.baseColorTexture is not None),
        }
    return {
        "images": len(images),
        "embedded": embedded,
        "external_hosts": external_hosts,
        "materials": len(materials),
        "first_material": first,
    }


def has_base_color_textures(glb_path: str) -> bool:
    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError:
        return False
    for material in gltf.materials or []:
        pbr = material.pbrMetallicRoughness
        if pbr and pbr.baseColorTexture is not None:
            return True
    return False


def _texture_info_is_embedded(gltf: GLTF2, texture_info) -> bool:
    """Return whether a texture info resolves to image data inside the GLB."""
    if texture_info is None or texture_info.index is None:
        return False
    textures = gltf.textures or []
    if not 0 <= texture_info.index < len(textures):
        return False
    source = textures[texture_info.index].source
    images = gltf.images or []
    if source is None or not 0 <= source < len(images):
        return False
    image = images[source]
    return image.bufferView is not None or bool(
        image.uri and image.uri.startswith("data:")
    )


def has_embedded_base_color_textures(glb_path: str) -> bool:
    """True only when every used material base-color map is self-contained.

    A mere TextureInfo reference is insufficient: Meshy GLBs sometimes point
    at a missing relative file or an expired signed URL, which still made the
    old ``has_base_color_textures`` check pass and skipped the repair fallback.
    """
    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError:
        return False
    used_materials = {
        primitive.material
        for mesh in gltf.meshes or []
        for primitive in mesh.primitives or []
        if primitive.material is not None
    }
    if not used_materials:
        return False
    for material_index in used_materials:
        if material_index >= len(gltf.materials or []):
            return False
        pbr = gltf.materials[material_index].pbrMetallicRoughness
        if not pbr or not _texture_info_is_embedded(gltf, pbr.baseColorTexture):
            return False
    return True


def ensure_pbr_materials(glb_path: str) -> bool:
    """Ensure primitives have valid PBR materials without replacing artwork.

    Existing materials, textures, metallic/roughness values, and color factors
    are preserved. A neutral default material is only added for primitives that
    have no material assignment.
    """
    try:
        gltf = _load_glb(glb_path)
    except GLBQualityError:
        return False

    if gltf.materials is None:
        gltf.materials = []

    changed = False
    default_indices = {}  # white base for COLOR_0 primitives, gray otherwise
    for material in gltf.materials:
        if material.pbrMetallicRoughness is None:
            material.pbrMetallicRoughness = PbrMetallicRoughness(
                baseColorFactor=[0.8, 0.8, 0.8, 1.0],
                metallicFactor=0.0,
                roughnessFactor=0.75,
            )
            changed = True
        if material.doubleSided is not True:
            material.doubleSided = True
            changed = True

    for mesh in gltf.meshes or []:
        for primitive in mesh.primitives or []:
            if primitive.material is None or primitive.material >= len(gltf.materials):
                # Vertex-colored primitives (e.g. STL pipeline) must get a WHITE
                # base color: baseColorFactor multiplies COLOR_0, so the usual
                # 0.8 gray default would darken the user's picked color.
                has_vertex_colors = (
                    getattr(primitive.attributes, "COLOR_0", None) is not None
                )
                base = [1.0, 1.0, 1.0, 1.0] if has_vertex_colors else [0.8, 0.8, 0.8, 1.0]
                key = has_vertex_colors
                if key not in default_indices:
                    default_indices[key] = len(gltf.materials)
                    gltf.materials.append(
                        Material(
                            name="WebAR_Default",
                            pbrMetallicRoughness=PbrMetallicRoughness(
                                baseColorFactor=base,
                                metallicFactor=0.0,
                                roughnessFactor=0.75,
                            ),
                            doubleSided=True,
                        )
                    )
                primitive.material = default_indices[key]
                changed = True

    if changed:
        gltf.save(glb_path)
    return changed


def validate_glb_quality(glb_path: str) -> None:
    """Validate the minimum GLB quality needed for web and AR viewing."""
    gltf = _load_glb(glb_path)
    if not gltf.meshes:
        raise GLBQualityError("GLB contains no meshes.")

    primitive_count = 0
    for mesh in gltf.meshes or []:
        for primitive in mesh.primitives or []:
            primitive_count += 1
            if getattr(primitive.attributes, "POSITION", None) is None:
                raise GLBQualityError("A GLB primitive is missing POSITION data.")
            if primitive.material is None:
                raise GLBQualityError("A GLB primitive is missing a material.")
            if not gltf.materials or primitive.material >= len(gltf.materials):
                raise GLBQualityError("A GLB primitive references an invalid material.")
            material = gltf.materials[primitive.material]
            if material.pbrMetallicRoughness is None:
                raise GLBQualityError("A GLB material is missing PBR properties.")

    if primitive_count == 0:
        raise GLBQualityError("GLB contains no renderable primitives.")

    for image in gltf.images or []:
        if image.bufferView is None and image.uri:
            if image.uri.startswith("data:"):
                try:
                    base64.b64decode(image.uri.split(",", 1)[1], validate=True)
                except Exception as exc:
                    raise GLBQualityError("A GLB texture data URI is invalid.") from exc
            else:
                raise GLBQualityError(
                    f"GLB still references an external texture: {image.uri}"
                )


def finalize_glb(glb_path: str, search_dirs: list = None, strict: bool = False) -> list:
    """Run the full quality pass on a freshly converted GLB.

    Returns a list of warning strings. In strict mode, validation failures
    raise GLBQualityError instead of being returned as warnings.
    """
    warnings = []
    try:
        if embed_data_uri_textures(glb_path):
            logger.info(f"Normalized data URI textures in {glb_path}")
    except Exception as exc:
        warnings.append(f"data URI texture normalization failed: {exc}")
        logger.warning(f"embed_data_uri_textures failed for {glb_path}: {exc}")

    try:
        if embed_external_textures(glb_path, search_dirs):
            logger.info(f"Embedded external textures into {glb_path}")
    except Exception as exc:
        warnings.append(f"texture embedding failed: {exc}")
        logger.warning(f"embed_external_textures failed for {glb_path}: {exc}")

    try:
        if ensure_pbr_materials(glb_path):
            logger.info(f"Patched missing PBR materials in {glb_path}")
    except Exception as exc:
        warnings.append(f"PBR material pass failed: {exc}")
        logger.warning(f"ensure_pbr_materials failed for {glb_path}: {exc}")

    try:
        validate_glb_quality(glb_path)
    except GLBQualityError as exc:
        if strict:
            raise
        warnings.append(str(exc))
        logger.warning(f"GLB quality validation warning for {glb_path}: {exc}")

    return warnings
