"""
GLB Modifier Module
Applies material and transform modifications to GLB files
Preserves animations, skins, and all other GLB features
"""

import numpy as np
import logging
from pathlib import Path
from pygltflib import (
    GLTF2, Image as GLTFImage, Texture, Sampler, TextureInfo,
    Material, PbrMetallicRoughness,
)
import os
import copy
import struct
import base64
from PIL import Image
import io

logger = logging.getLogger(__name__)

# DoS guards for untrusted input.
# Cap decoded texture bytes and total pixel count so a crafted base64 blob or a
# "pixel bomb" image can't exhaust memory before the 2048px downscale runs.
MAX_TEXTURE_BYTES = int(os.environ.get("MAX_TEXTURE_BYTES", 32 * 1024 * 1024))
# Pillow uses MAX_IMAGE_PIXELS to raise DecompressionBombError; set a sane cap.
Image.MAX_IMAGE_PIXELS = int(os.environ.get("MAX_IMAGE_PIXELS", 50_000_000))


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple (0-1 range)"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def apply_material_modifications(gltf, material_mods):
    """
    Apply material modifications to all materials in the GLTF
    
    Args:
        gltf: GLTF2 object
        material_mods: dict with 'color', 'metalness', 'roughness'
    """
    logger.info(f"Applying material modifications: {material_mods}")

    if not gltf.materials:
        logger.info("No materials in GLB – creating a default PBR material")
        gltf.materials = [Material(
            pbrMetallicRoughness=PbrMetallicRoughness(
                baseColorFactor=[1.0, 1.0, 1.0, 1.0],
                metallicFactor=0.0,
                roughnessFactor=1.0,
            ),
            doubleSided=True,
        )]
        # Assign the new material to all mesh primitives that lack one
        for mesh in (gltf.meshes or []):
            for prim in (mesh.primitives or []):
                if prim.material is None:
                    prim.material = 0
    
    for i, material in enumerate(gltf.materials):
        # Ensure material has PBR metallic roughness
        if not material.pbrMetallicRoughness:
            logger.warning(f"Material {i} has no PBR properties, skipping")
            continue
        
        pbr = material.pbrMetallicRoughness
        name = material.name or f"Material_{i}"
        # MASK cutouts (foliage from the FBX pipeline) keep their alpha setup —
        # user knobs must not clobber them into invisibility. BLEND materials
        # stay editable so an opacity change can be reverted to 1.0.
        is_transparent_like = (material.alphaMode or "OPAQUE") == "MASK"
        # A baseColorFactor multiplies the texture, so a solid color would
        # tint/darken existing artwork instead of "coloring" the model.
        has_texture = pbr.baseColorTexture is not None

        # Always set doubleSided to True for all materials
        material.doubleSided = True

        # Apply base color with opacity
        if 'color' in material_mods and material_mods['color'] and not is_transparent_like:
            try:
                raw_color = material_mods['color']
                # Accept both hex string ("#FF0000") and RGB float array ([0.78, 0.2, 0.2])
                if isinstance(raw_color, (list, tuple)):
                    color_rgb = tuple(float(c) for c in raw_color[:3])
                else:
                    color_rgb = hex_to_rgb(raw_color)
                # Get opacity value (default 1.0)
                opacity = float(material_mods.get('opacity', 1.0))

                # tint_textures: set by the viewer's material editor, where the
                # user picks the color while seeing the texture — honor it as a
                # multiply tint. Without the flag (upload-time color) textures
                # are protected from being tinted/darkened by a solid color.
                tint_textures = bool(material_mods.get('tint_textures'))

                if has_texture and not tint_textures:
                    # Preserve the texture's colors; only honor an explicit
                    # opacity change via the factor's alpha component.
                    if opacity < 1.0:
                        base = pbr.baseColorFactor or [1.0, 1.0, 1.0, 1.0]
                        pbr.baseColorFactor = [base[0], base[1], base[2], opacity]
                        logger.info(f"Applied opacity {opacity} to textured material {i} (color skipped)")
                    else:
                        logger.info(f"Skipped color for textured material {i} ({name})")
                else:
                    # Set baseColorFactor (RGBA) — on textured materials this
                    # multiplies (tints) the texture, matching the live preview.
                    pbr.baseColorFactor = list(color_rgb) + [opacity]
                    logger.info(
                        f"Applied color {raw_color} with opacity {opacity} to material {i}"
                        + (" (texture tint)" if has_texture else "")
                    )

                # Set alpha mode based on opacity; never downgrade MASK cutouts.
                # Only downgrade BLEND→OPAQUE for untextured materials: a
                # textured material authored as BLEND (glass, foliage with an
                # alpha texture) carries meaningful per-texel transparency that
                # a default opacity=1.0 must not silently flatten to opaque.
                if opacity < 1.0:
                    material.alphaMode = 'BLEND'
                    logger.info(f"Set alphaMode to BLEND for material {i} (opacity < 1.0)")
                elif material.alphaMode == 'BLEND' and not has_texture:
                    material.alphaMode = 'OPAQUE'
            except Exception as e:
                logger.error(f"Failed to apply color to material {i}: {e}")
        elif 'opacity' in material_mods and not is_transparent_like:
            # Opacity-only edit (no color in the payload): keep each
            # material's own RGB — opacity lives in baseColorFactor's alpha
            # channel, so writing it must not homogenize per-material colors.
            try:
                opacity = float(material_mods['opacity'])
                base = pbr.baseColorFactor or [1.0, 1.0, 1.0, 1.0]
                pbr.baseColorFactor = [base[0], base[1], base[2], opacity]
                if opacity < 1.0:
                    material.alphaMode = 'BLEND'
                elif material.alphaMode == 'BLEND':
                    material.alphaMode = 'OPAQUE'
                logger.info(f"Applied opacity {opacity} to material {i} (color preserved)")
            except Exception as e:
                logger.error(f"Failed to apply opacity to material {i}: {e}")

        # Apply metalness (skip for foliage-like/transparent materials)
        if 'metalness' in material_mods and not is_transparent_like:
            try:
                pbr.metallicFactor = float(material_mods['metalness'])
                logger.info(f"Applied metalness {material_mods['metalness']} to material {i}")
            except Exception as e:
                logger.error(f"Failed to apply metalness to material {i}: {e}")
        elif 'metalness' in material_mods and is_transparent_like:
            logger.info(f"Skipped metalness for foliage/transparent material {i} ({name})")
        
        # Apply roughness (skip for foliage-like/transparent materials)
        if 'roughness' in material_mods and not is_transparent_like:
            try:
                pbr.roughnessFactor = float(material_mods['roughness'])
                logger.info(f"Applied roughness {material_mods['roughness']} to material {i}")
            except Exception as e:
                logger.error(f"Failed to apply roughness to material {i}: {e}")
        elif 'roughness' in material_mods and is_transparent_like:
            logger.info(f"Skipped roughness for foliage/transparent material {i} ({name})")

        # Material summary
        try:
            tex_idx = pbr.baseColorTexture.index if pbr.baseColorTexture else None
            logger.info(f"Material summary [{i}] {name}: alphaMode={material.alphaMode}, doubleSided={getattr(material, 'doubleSided', False)}, tex={tex_idx}, metallic={getattr(pbr,'metallicFactor',None)}, roughness={getattr(pbr,'roughnessFactor',None)}")
        except Exception:
            pass
    
    return gltf


def _iter_gltf_mesh_nodes(gltf):
    """
    Yield (node_index, node) for every node with a mesh, in the same
    depth-first pre-order the viewer's THREE.Scene.traverse() visits them in
    (both walk the glTF node hierarchy top-down, children in array order),
    so layer identities line up between the client's live scene and this
    on-disk GLTF2 object.
    """
    if not gltf.nodes:
        return []

    result = []
    visited = set()

    def walk(node_idx):
        if node_idx in visited or node_idx < 0 or node_idx >= len(gltf.nodes):
            return
        visited.add(node_idx)
        node = gltf.nodes[node_idx]
        if node.mesh is not None:
            result.append((node_idx, node))
        for child_idx in (node.children or []):
            walk(child_idx)

    if gltf.scenes:
        scene_idx = gltf.scene if gltf.scene is not None else 0
        roots = gltf.scenes[scene_idx].nodes or []
    else:
        roots = list(range(len(gltf.nodes)))

    for r in roots:
        walk(r)
    return result


def _resolve_layer_node(mesh_nodes, name, occurrence):
    """Find the Nth (0-indexed `occurrence`) mesh node named `name`."""
    count = 0
    for node_idx, node in mesh_nodes:
        if (node.name or "") == (name or ""):
            if count == occurrence:
                return node_idx, node
            count += 1
    return None, None


def apply_layer_modifications(gltf, layer_mods):
    """
    Apply per-layer (per-mesh-node) visibility and color overrides baked
    from the viewer's Layers panel.

    Args:
        gltf: GLTF2 object
        layer_mods: {
            'hidden': [{'name': str, 'occurrence': int}, ...],
            'colors': [{'name': str, 'occurrence': int, 'color': [r, g, b]}, ...]
        }
    """
    if not gltf.nodes or not gltf.meshes:
        return gltf

    mesh_nodes = _iter_gltf_mesh_nodes(gltf)

    # Recolor first: clone the primitive's material per targeted layer so a
    # color change on one layer never bleeds into a sibling layer that
    # happens to share the same material.
    for entry in layer_mods.get('colors') or []:
        node_idx, node = _resolve_layer_node(mesh_nodes, entry.get('name', ''), entry.get('occurrence', 0))
        if node is None or node.mesh is None:
            continue
        try:
            color = [float(c) for c in entry['color'][:3]]
        except (KeyError, TypeError, ValueError, IndexError):
            continue

        mesh = gltf.meshes[node.mesh]
        for prim in (mesh.primitives or []):
            if prim.material is None or not gltf.materials:
                continue
            new_material = copy.deepcopy(gltf.materials[prim.material])
            if not new_material.pbrMetallicRoughness:
                new_material.pbrMetallicRoughness = PbrMetallicRoughness(baseColorFactor=[1.0, 1.0, 1.0, 1.0])
            alpha = (new_material.pbrMetallicRoughness.baseColorFactor or [1.0, 1.0, 1.0, 1.0])[3]
            new_material.pbrMetallicRoughness.baseColorFactor = color + [alpha]
            new_material.doubleSided = True
            gltf.materials.append(new_material)
            prim.material = len(gltf.materials) - 1
            logger.info(f"Applied layer color {color} to node '{node.name}' (cloned material {prim.material})")

    # Hide last: detach the node from its parent's children (or the scene's
    # root node list) so AR viewers (which load the GLB directly, not the
    # viewer's live THREE scene) never see it either.
    hidden_targets = set()
    for entry in layer_mods.get('hidden') or []:
        node_idx, node = _resolve_layer_node(mesh_nodes, entry.get('name', ''), entry.get('occurrence', 0))
        if node_idx is not None:
            hidden_targets.add(node_idx)

    if hidden_targets:
        for node in gltf.nodes:
            if node.children:
                node.children = [c for c in node.children if c not in hidden_targets]
        for scene in (gltf.scenes or []):
            if scene.nodes:
                scene.nodes = [n for n in scene.nodes if n not in hidden_targets]
        logger.info(f"Hid {len(hidden_targets)} layer node(s): {sorted(hidden_targets)}")

    return gltf


def apply_explode_modifications(gltf, explode_mods):
    """
    Permanently bake the viewer's exploded per-layer positions (normally
    preview-only) into each mesh node's local transform, so AR viewers
    (which load the GLB directly) show the exploded layout too.

    Args:
        gltf: GLTF2 object
        explode_mods: {'positions': [{'name': str, 'occurrence': int, 'translation': [x, y, z]}, ...]}
    """
    if not gltf.nodes:
        return gltf

    mesh_nodes = _iter_gltf_mesh_nodes(gltf)

    for entry in explode_mods.get('positions') or []:
        node_idx, node = _resolve_layer_node(mesh_nodes, entry.get('name', ''), entry.get('occurrence', 0))
        if node is None:
            continue
        try:
            translation = [float(c) for c in entry['translation'][:3]]
        except (KeyError, TypeError, ValueError, IndexError):
            continue

        if node.matrix:
            # Column-major 4x4: elements 12-14 are the translation column,
            # independent of whatever rotation/scale the other columns encode.
            m = list(node.matrix)
            m[12], m[13], m[14] = translation
            node.matrix = m
        else:
            node.translation = translation
        logger.info(f"Baked exploded position {translation} onto node '{node.name}'")

    return gltf


def _ensure_texcoord0(gltf):
    """
    Generate TEXCOORD_0 for mesh primitives that lack it.
    Uses triplanar box projection: each vertex is UV-mapped based on
    the dominant axis of its face normal, giving a natural-looking
    texture wrap on most model shapes.
    """
    from pygltflib import Accessor, BufferView as BV
    import math

    blob = gltf.binary_blob()
    if not blob:
        blob = b""

    extra_bytes = bytearray()

    for mesh in (gltf.meshes or []):
        for prim in (mesh.primitives or []):
            if getattr(prim.attributes, 'TEXCOORD_0', None) is not None:
                continue  # already has UVs

            pos_idx = getattr(prim.attributes, 'POSITION', None)
            if pos_idx is None:
                continue

            # Read vertex positions
            acc = gltf.accessors[pos_idx]
            bv = gltf.bufferViews[acc.bufferView]
            offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
            stride = bv.byteStride or 12  # 3 floats * 4 bytes
            count = acc.count

            positions = []
            for v in range(count):
                o = offset + v * stride
                x, y, z = struct.unpack_from('<3f', blob, o)
                positions.append((x, y, z))

            # Read face normals if available, else compute from indices
            norm_idx = getattr(prim.attributes, 'NORMAL', None)
            normals = None
            if norm_idx is not None:
                nacc = gltf.accessors[norm_idx]
                nbv = gltf.bufferViews[nacc.bufferView]
                noff = (nbv.byteOffset or 0) + (nacc.byteOffset or 0)
                nstride = nbv.byteStride or 12
                normals = []
                for v in range(nacc.count):
                    o = noff + v * nstride
                    nx, ny, nz = struct.unpack_from('<3f', blob, o)
                    normals.append((nx, ny, nz))

            # Compute bounding box for normalisation
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            zs = [p[2] for p in positions]
            min_v = [min(xs), min(ys), min(zs)]
            max_v = [max(xs), max(ys), max(zs)]
            rng = [max_v[i] - min_v[i] if max_v[i] != min_v[i] else 1.0 for i in range(3)]

            # Generate UVs: triplanar box projection based on vertex normal
            uv_data = bytearray()
            for i, (x, y, z) in enumerate(positions):
                # Normalised coords in [0,1]
                nx = (x - min_v[0]) / rng[0]
                ny = (y - min_v[1]) / rng[1]
                nz = (z - min_v[2]) / rng[2]

                if normals and i < len(normals):
                    anx, any_, anz = abs(normals[i][0]), abs(normals[i][1]), abs(normals[i][2])
                else:
                    # Fallback: use spherical projection
                    anx, any_, anz = 0, 0, 1

                # Pick projection plane based on dominant normal axis
                if anx >= any_ and anx >= anz:
                    # X-dominant: project on YZ plane
                    u, v = nz, ny
                elif any_ >= anx and any_ >= anz:
                    # Y-dominant: project on XZ plane
                    u, v = nx, nz
                else:
                    # Z-dominant: project on XY plane
                    u, v = nx, ny

                uv_data += struct.pack('<2f', u, v)

            # Add BufferView for UV data
            bv_offset = len(blob) + len(extra_bytes)
            new_bv = BV(buffer=0, byteOffset=bv_offset, byteLength=len(uv_data))
            bv_index = len(gltf.bufferViews)
            gltf.bufferViews.append(new_bv)

            # Add Accessor
            new_acc = Accessor(
                bufferView=bv_index,
                byteOffset=0,
                componentType=5126,  # FLOAT
                count=count,
                type='VEC2',
                max=[1.0, 1.0],
                min=[0.0, 0.0],
            )
            acc_index = len(gltf.accessors)
            gltf.accessors.append(new_acc)

            prim.attributes.TEXCOORD_0 = acc_index
            extra_bytes += uv_data
            logger.info(f"Generated TEXCOORD_0 for primitive ({count} vertices)")

    # Append extra bytes to binary buffer
    if extra_bytes:
        new_blob = blob + bytes(extra_bytes)
        gltf.set_binary_blob(new_blob)
        if gltf.buffers:
            gltf.buffers[0].byteLength = len(new_blob)

    return gltf


def apply_texture_modifications(gltf, texture_data_base64, tint_rgba=None):
    """
    Apply texture to all materials in the GLTF.
    Embeds the image into the GLB binary buffer (not as data URI)
    and generates TEXCOORD_0 if the mesh lacks UV coordinates.

    tint_rgba: explicit [r,g,b,a] tint chosen alongside the texture (viewer
    editor). Defaults to white so a stale color can't discolor the image.
    """
    if not texture_data_base64:
        logger.info("No texture data provided, skipping texture modification")
        return gltf

    try:
        logger.info("Applying texture modifications")

        # Decode base64 image
        if ',' in texture_data_base64:
            texture_data_base64 = texture_data_base64.split(',')[1]

        # Bound the encoded payload before decoding (base64 inflates ~4:3).
        if len(texture_data_base64) > MAX_TEXTURE_BYTES * 4 // 3 + 1024:
            raise ValueError("Texture payload too large")

        image_bytes = base64.b64decode(texture_data_base64)
        if len(image_bytes) > MAX_TEXTURE_BYTES:
            raise ValueError("Decoded texture too large")
        logger.info(f"Decoded texture image: {len(image_bytes)} bytes")

        # Open image with PIL to optimise. MAX_IMAGE_PIXELS (set at import) makes
        # PIL raise DecompressionBombError on pixel bombs before allocating.
        img = Image.open(io.BytesIO(image_bytes))
        img.load()  # force decode now so a bomb fails here, inside the try
        logger.info(f"Image format: {img.format}, size: {img.size}, mode: {img.mode}")

        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        max_size = 2048
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            logger.info(f"Resized image to: {img.size}")

        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        image_bytes = buf.getvalue()
        logger.info(f"Optimized texture: {len(image_bytes)} bytes")

        # ── Embed image in binary buffer (not data URI) ──
        blob = gltf.binary_blob() or b""
        img_offset = len(blob)
        # Pad the image to a 4-byte boundary. The image bufferView itself does
        # not require alignment, but _ensure_texcoord0() may append a FLOAT
        # TEXCOORD_0 accessor right after it, and accessor-backed bufferViews
        # MUST start on a 4-byte offset (glTF spec). Without this pad, a PNG
        # whose length isn't a multiple of 4 leaves the UV accessor misaligned
        # and three.js/model-viewer refuses to load the GLB.
        img_padding = (-len(image_bytes)) % 4
        new_blob = blob + image_bytes + (b"\x00" * img_padding)
        gltf.set_binary_blob(new_blob)
        if gltf.buffers:
            gltf.buffers[0].byteLength = len(new_blob)

        # Initialize arrays
        if gltf.images is None:
            gltf.images = []
        if gltf.textures is None:
            gltf.textures = []
        if gltf.samplers is None:
            gltf.samplers = []
        if gltf.bufferViews is None:
            gltf.bufferViews = []

        # BufferView for the image
        from pygltflib import BufferView as BV
        img_bv = BV(buffer=0, byteOffset=img_offset, byteLength=len(image_bytes))
        img_bv_index = len(gltf.bufferViews)
        gltf.bufferViews.append(img_bv)

        # Image referencing the bufferView (no uri)
        gltf_image = GLTFImage()
        gltf_image.bufferView = img_bv_index
        gltf_image.mimeType = "image/png"
        image_index = len(gltf.images)
        gltf.images.append(gltf_image)
        logger.info(f"Embedded image in buffer: {len(image_bytes)} bytes at bv[{img_bv_index}]")

        # Sampler
        sampler = Sampler()
        sampler.magFilter = 9729   # LINEAR
        sampler.minFilter = 9987   # LINEAR_MIPMAP_LINEAR
        sampler.wrapS = 10497      # REPEAT
        sampler.wrapT = 10497      # REPEAT
        sampler_index = len(gltf.samplers)
        gltf.samplers.append(sampler)

        # Texture
        texture = Texture()
        texture.source = image_index
        texture.sampler = sampler_index
        texture_index = len(gltf.textures)
        gltf.textures.append(texture)

        # ── Ensure mesh has TEXCOORD_0 ──
        gltf = _ensure_texcoord0(gltf)

        # Apply texture to all materials
        if gltf.materials:
            for i, material in enumerate(gltf.materials):
                if material.pbrMetallicRoughness:
                    # baseColorFactor MULTIPLIES the texture. Use the explicit
                    # tint when one was chosen with the texture; otherwise reset
                    # to white so a stale color can't discolor the image.
                    prev = material.pbrMetallicRoughness.baseColorFactor
                    alpha = prev[3] if prev and len(prev) == 4 else 1.0
                    if tint_rgba and len(tint_rgba) == 4:
                        material.pbrMetallicRoughness.baseColorFactor = list(tint_rgba)
                    else:
                        material.pbrMetallicRoughness.baseColorFactor = [1.0, 1.0, 1.0, alpha]
                    texture_info = TextureInfo()
                    texture_info.index = texture_index
                    texture_info.texCoord = 0
                    material.pbrMetallicRoughness.baseColorTexture = texture_info
                    logger.info(
                        f"Applied texture to material {i} "
                        f"(tint={material.pbrMetallicRoughness.baseColorFactor})"
                    )

        logger.info("Texture embedding completed successfully")
        return gltf

    except Exception as e:
        logger.error(f"Failed to apply texture: {e}", exc_info=True)
        return gltf


def normalize_model_to_center(gltf):
    """
    Normalize model by translating its WORLD-space bounding-box center to
    the origin. The shift is conjugated into each mesh's local frame
    (t = −L⁻¹·center for a mesh under world matrix W = [L|t]), so models
    whose parts are positioned by node transforms (STEP assemblies, GLB
    uploads) keep their inter-part layout. The old local-space version
    centered every mesh's own vertices instead, which piled all the parts
    of an assembly on top of each other at the origin.

    Normalization is cosmetic — whenever it cannot be applied safely
    (instanced meshes under different transforms, shared vertex data,
    compressed geometry) the model is returned UNCHANGED rather than risking
    corruption.

    Returns:
        GLTF2: Modified GLTF object
    """
    logger.info("Normalizing model to center origin")

    import base64
    import struct

    try:
        if not gltf.meshes:
            return gltf

        # One world matrix per mesh. Instanced meshes under differing
        # transforms would need different shifts in the same vertex data —
        # skip normalization for those models.
        mesh_world = _mesh_world_matrices(gltf)
        identity = np.eye(4)
        mesh_w = {}
        for mesh_idx in range(len(gltf.meshes)):
            entries = mesh_world.get(mesh_idx)
            ws = [w for _, w in entries] if entries else [identity]
            for w in ws[1:]:
                if not np.allclose(w, ws[0], atol=1e-9):
                    logger.warning(
                        f"Mesh {mesh_idx} instanced under differing node transforms "
                        "— skipping center normalization"
                    )
                    return gltf
            mesh_w[mesh_idx] = ws[0]

        # Unique POSITION accessors (the old per-primitive loop shifted
        # shared vertex data once per referencing primitive). An accessor
        # shared across meshes with different transforms can't be shifted
        # both ways — skip.
        pos_targets = {}
        for mesh_idx, mesh in enumerate(gltf.meshes):
            for primitive in (mesh.primitives or []):
                if primitive.attributes is None:
                    continue
                p_idx = getattr(primitive.attributes, 'POSITION', None)
                if p_idx is None:
                    continue
                claimed = pos_targets.get(p_idx)
                if claimed is not None and not np.allclose(
                    mesh_w[claimed], mesh_w[mesh_idx], atol=1e-9
                ):
                    logger.warning(
                        f"POSITION accessor {p_idx} shared across differing node "
                        "transforms — skipping center normalization"
                    )
                    return gltf
                pos_targets.setdefault(p_idx, mesh_idx)

        for acc_idx in pos_targets:
            acc = gltf.accessors[acc_idx]
            if acc.bufferView is None or acc.componentType != 5126:
                logger.warning(
                    f"POSITION accessor {acc_idx} not plain float data — "
                    "skipping center normalization"
                )
                return gltf

        buffers_data = {}

        def _buffer_bytes(buf_idx):
            if buf_idx not in buffers_data:
                buffer = gltf.buffers[buf_idx]
                if buffer.uri and buffer.uri.startswith('data:'):
                    raw = base64.b64decode(buffer.uri[buffer.uri.find(',') + 1:])
                elif hasattr(gltf, 'binary_blob') and gltf.binary_blob():
                    raw = gltf.binary_blob()
                else:
                    raise ValueError(f"buffer {buf_idx} has no accessible data")
                buffers_data[buf_idx] = bytearray(raw)
            return buffers_data[buf_idx]

        def _accessor_layout(acc_idx):
            accessor = gltf.accessors[acc_idx]
            buffer_view = gltf.bufferViews[accessor.bufferView]
            data = _buffer_bytes(buffer_view.buffer)
            offset = (buffer_view.byteOffset or 0) + (accessor.byteOffset or 0)
            stride = buffer_view.byteStride if buffer_view.byteStride else 12
            return accessor, data, offset, stride

        # World-space bounding box (the old local-space scan pooled vertices
        # across unrelated coordinate frames).
        mins_w = [float('inf')] * 3
        maxs_w = [float('-inf')] * 3
        for acc_idx, mesh_idx in pos_targets.items():
            accessor, data, offset, stride = _accessor_layout(acc_idx)
            (w00, w01, w02, wt0), (w10, w11, w12, wt1), (w20, w21, w22, wt2) = mesh_w[mesh_idx][:3]
            for i in range(accessor.count):
                x, y, z = struct.unpack_from('fff', data, offset + i * stride)
                wv = (w00 * x + w01 * y + w02 * z + wt0,
                      w10 * x + w11 * y + w12 * z + wt1,
                      w20 * x + w21 * y + w22 * z + wt2)
                for j in range(3):
                    if wv[j] < mins_w[j]:
                        mins_w[j] = wv[j]
                    if wv[j] > maxs_w[j]:
                        maxs_w[j] = wv[j]
        if mins_w[0] == float('inf'):
            return gltf
        center = (np.array(mins_w) + np.array(maxs_w)) / 2.0
        if np.allclose(center, 0.0, atol=1e-9):
            logger.info("Model already centered — nothing to normalize")
            return gltf
        logger.info(f"World-space model center: ({center[0]:.3f}, {center[1]:.3f}, {center[2]:.3f})")

        for acc_idx, mesh_idx in pos_targets.items():
            accessor, data, offset, stride = _accessor_layout(acc_idx)
            # World shift of -center, expressed in this mesh's local frame.
            sx, sy, sz = -np.linalg.solve(mesh_w[mesh_idx][:3, :3], center)
            mins = [float('inf')] * 3
            maxs = [float('-inf')] * 3
            for i in range(accessor.count):
                pos = offset + i * stride
                x, y, z = struct.unpack_from('fff', data, pos)
                nx, ny, nz = x + sx, y + sy, z + sz
                struct.pack_into('fff', data, pos, nx, ny, nz)
                for j, v in enumerate((nx, ny, nz)):
                    if v < mins[j]:
                        mins[j] = v
                    if v > maxs[j]:
                        maxs[j] = v
            if accessor.count:
                accessor.min = [float(v) for v in mins]
                accessor.max = [float(v) for v in maxs]
            logger.info(f"Translated {accessor.count} vertices in POSITION accessor {acc_idx}")

        # Commit buffers only after every accessor shifted cleanly.
        for buf_idx, data in buffers_data.items():
            buffer = gltf.buffers[buf_idx]
            if buffer.uri and buffer.uri.startswith('data:'):
                buffer.uri = 'data:application/octet-stream;base64,' + base64.b64encode(bytes(data)).decode('utf-8')
            else:
                gltf.set_binary_blob(bytes(data))
            buffer.byteLength = len(data)

        logger.info("✅ Model normalized to center origin")
        return gltf

    except Exception as e:
        logger.error(f"Failed to normalize model: {e}", exc_info=True)
        return gltf


def calculate_model_center(gltf):
    """
    Calculate the center point of the model's bounding box
    
    Returns:
        tuple: (center_x, center_y, center_z)
    """
    if not gltf.meshes:
        return (0.0, 0.0, 0.0)
    
    min_x = min_y = min_z = float('inf')
    max_x = max_y = max_z = float('-inf')
    
    try:
        for mesh in gltf.meshes:
            if not mesh.primitives:
                continue
            
            for primitive in mesh.primitives:
                if primitive.attributes is None:
                    continue
                
                # Get POSITION accessor
                if hasattr(primitive.attributes, 'POSITION') and primitive.attributes.POSITION is not None:
                    pos_accessor_idx = primitive.attributes.POSITION
                    accessor = gltf.accessors[pos_accessor_idx]
                    buffer_view = gltf.bufferViews[accessor.bufferView]
                    buffer = gltf.buffers[buffer_view.buffer]
                    
                    # Get binary data
                    if buffer.uri and buffer.uri.startswith('data:'):
                        data_start = buffer.uri.find(',') + 1
                        binary_data = base64.b64decode(buffer.uri[data_start:])
                    elif hasattr(gltf, 'binary_blob') and gltf.binary_blob():
                        binary_data = gltf.binary_blob()
                    else:
                        continue
                    
                    # Parse vertex positions
                    offset = buffer_view.byteOffset if buffer_view.byteOffset else 0
                    offset += accessor.byteOffset if accessor.byteOffset else 0
                    vertex_count = accessor.count
                    stride = buffer_view.byteStride if buffer_view.byteStride else 12
                    
                    for i in range(vertex_count):
                        pos = offset + i * stride
                        x, y, z = struct.unpack_from('fff', binary_data, pos)
                        
                        min_x = min(min_x, x)
                        min_y = min(min_y, y)
                        min_z = min(min_z, z)
                        max_x = max(max_x, x)
                        max_y = max(max_y, y)
                        max_z = max(max_z, z)
        
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        center_z = (min_z + max_z) / 2.0
        
        logger.info(f"Model center calculated: ({center_x:.3f}, {center_y:.3f}, {center_z:.3f})")
        return (center_x, center_y, center_z)
        
    except Exception as e:
        logger.error(f"Failed to calculate model center: {e}")
        return (0.0, 0.0, 0.0)


def create_rotation_matrix(rx, ry, rz):
    """
    Create a 3x3 rotation matrix from Euler angles (in radians)
    Orientation follows model-viewer's yaw (Y), pitch (X), roll (Z) convention.
    Rotation order: intrinsic YXZ (yaw -> pitch -> roll).
    
    Args:
        rx: Rotation around X axis (pitch, radians)
        ry: Rotation around Y axis (yaw, radians)
        rz: Rotation around Z axis (roll, radians)
    
    Returns:
        3x3 numpy rotation matrix
    """
    try:
        from scipy.spatial.transform import Rotation as R
        # Use intrinsic YXZ (yaw, pitch, roll) to mirror model-viewer orientation
        rot = R.from_euler('YXZ', [ry, rx, rz], degrees=False)
        return rot.as_matrix()
    except ImportError:
        # Fallback to manual matrix multiplication if scipy not available
        logger.warning("scipy not available, using manual rotation matrix")
        
        # Rotation matrix around X axis (pitch)
        Rx = np.array([
            [1, 0, 0],
            [0, np.cos(rx), -np.sin(rx)],
            [0, np.sin(rx), np.cos(rx)]
        ])
        
        # Rotation matrix around Y axis (yaw)
        Ry = np.array([
            [np.cos(ry), 0, np.sin(ry)],
            [0, 1, 0],
            [-np.sin(ry), 0, np.cos(ry)]
        ])
        
        # Rotation matrix around Z axis (roll)
        Rz = np.array([
            [np.cos(rz), -np.sin(rz), 0],
            [np.sin(rz), np.cos(rz), 0],
            [0, 0, 1]
        ])
        
        # Intrinsic YXZ: first yaw (Y), then pitch (X), finally roll (Z)
        return Ry @ Rx @ Rz


def _quat_to_matrix(q):
    """glTF node rotation quaternion [x, y, z, w] -> 3x3 rotation matrix."""
    x, y, z, w = (float(v) for v in q)
    n = (x * x + y * y + z * z + w * w) ** 0.5 or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _node_local_matrix(node):
    """4x4 local transform of a glTF node (matrix or TRS form)."""
    if node.matrix:
        # glTF stores matrices column-major.
        return np.array(node.matrix, dtype=float).reshape(4, 4).T
    m = np.eye(4)
    if node.rotation:
        m[:3, :3] = _quat_to_matrix(node.rotation)
    if node.scale:
        m[:3, :3] = m[:3, :3] @ np.diag([float(s) for s in node.scale])
    if node.translation:
        m[:3, 3] = [float(t) for t in node.translation]
    return m


def _mesh_world_matrices(gltf):
    """mesh index -> list of (node_idx, 4x4 world matrix) for every node
    that instances the mesh. Meshes not referenced by any node don't appear
    (callers treat them as identity)."""
    world = {}
    scene_idx = gltf.scene if gltf.scene is not None else 0
    if not gltf.scenes or scene_idx >= len(gltf.scenes):
        return world
    visiting = set()

    def walk(node_idx, parent):
        if node_idx in visiting:
            raise ValueError("cyclic node graph in GLB")
        visiting.add(node_idx)
        node = gltf.nodes[node_idx]
        w = parent @ _node_local_matrix(node)
        if node.mesh is not None:
            world.setdefault(node.mesh, []).append((node_idx, w))
        for child in (node.children or []):
            walk(child, w)
        visiting.discard(node_idx)

    for root in (gltf.scenes[scene_idx].nodes or []):
        walk(root, np.eye(4))
    return world


def apply_transform_modifications(gltf, transform_mods, transform_info=None):
    """
    Apply transform modifications with the model's world-space center as
    pivot, baked into vertex data. Node transforms are respected: for a mesh
    under world matrix W the world-space change M is baked as W⁻¹·M·W, so
    multi-part models whose parts are positioned by node translations scale
    and rotate as one model instead of each part transforming around its own
    local frame while the node offsets stay put.

    Args:
        gltf: GLTF2 object
        transform_mods: dict with 'scale' and 'rotation' (x, y, z in degrees)
        transform_info: optional dict; if a transform is actually baked, this
            is populated with {'matrix': <4x4 numpy world-space change>}
            (T(center)·R·S·T(-center)) so the caller can keep anything else
            stored in that same world-space frame in sync (e.g. hotspot
            positions/normals, which are captured from model-viewer's
            positionAndNormalFromPoint — the same frame this pivot is
            computed in). Left untouched if nothing was baked.

    Returns:
        gltf
    """
    logger.info(f"Applying transform modifications: {transform_mods}")

    # Get rotation parameters
    rotation = transform_mods.get('rotation', {})
    rx = np.radians(float(rotation.get('x', 0)))
    ry = np.radians(float(rotation.get('y', 0)))
    rz = np.radians(float(rotation.get('z', 0)))
    has_rotation = (rx != 0 or ry != 0 or rz != 0)
    
    # Calculate rotation matrix if needed. create_rotation_matrix follows
    # model-viewer's orientation convention (intrinsic YXZ, right-handed) so
    # the baked result matches the live preview — the old inverted-sign
    # "clockwise" matrix was the exact inverse and saved every rotation
    # mirrored relative to what the preview showed.
    rotation_matrix = None
    if has_rotation:
        rotation_matrix = create_rotation_matrix(rx, ry, rz)
        logger.info(f"Rotation matrix calculated for ({rotation.get('x', 0)}°, {rotation.get('y', 0)}°, {rotation.get('z', 0)}°)")
    
    # Apply scale and rotation to mesh vertices (permanent geometry change)
    scale_factor = float(transform_mods.get('scale', 1.0))
    
    if (scale_factor != 1.0 or has_rotation) and gltf.meshes:
        import base64
        import struct

        transforms = []
        if has_rotation:
            transforms.append(f"rotation ({rotation.get('x', 0)}°, {rotation.get('y', 0)}°, {rotation.get('z', 0)}°)")
        if scale_factor != 1.0:
            transforms.append(f"scale {scale_factor}")
        logger.info(f"Applying {' and '.join(transforms)} to mesh vertices")

        # ---- Validate every target accessor up front: this bake is
        # all-or-nothing. The old loop wrote buffers back per primitive, so
        # one unreadable accessor mid-way (Draco/quantized geometry) left
        # the model half-transformed — some parts scaled, the rest not.
        # Raising here instead propagates to modify_glb, the endpoint
        # reports the error, and the original file is never replaced. ----
        FLOAT_COMPONENT = 5126
        target_attr_names = ('POSITION', 'NORMAL', 'TANGENT') if has_rotation else ('POSITION',)
        for mesh in gltf.meshes:
            for primitive in (mesh.primitives or []):
                if primitive.attributes is None:
                    continue
                for attr_name in target_attr_names:
                    a_idx = getattr(primitive.attributes, attr_name, None)
                    if a_idx is None:
                        continue
                    acc = gltf.accessors[a_idx]
                    if acc.bufferView is None:
                        raise ValueError(
                            f"accessor {a_idx} has no bufferView (Draco/sparse-compressed "
                            "geometry) — cannot bake transforms into this model"
                        )
                    if acc.componentType != FLOAT_COMPONENT:
                        raise ValueError(
                            f"accessor {a_idx} componentType {acc.componentType} is not "
                            "float (quantized geometry) — cannot bake transforms into this model"
                        )

        # ---- Read each involved buffer once; every accessor mutates the
        # same bytearray and buffers are only written back after ALL
        # transforms succeeded. ----
        buffers_data = {}

        def _buffer_bytes(buf_idx):
            if buf_idx not in buffers_data:
                buffer = gltf.buffers[buf_idx]
                if buffer.uri and buffer.uri.startswith('data:'):
                    raw = base64.b64decode(buffer.uri[buffer.uri.find(',') + 1:])
                elif hasattr(gltf, 'binary_blob') and gltf.binary_blob():
                    raw = gltf.binary_blob()
                else:
                    raise ValueError(f"buffer {buf_idx} has no accessible data")
                buffers_data[buf_idx] = bytearray(raw)
            return buffers_data[buf_idx]

        def _accessor_layout(acc_idx, n_floats):
            accessor = gltf.accessors[acc_idx]
            buffer_view = gltf.bufferViews[accessor.bufferView]
            data = _buffer_bytes(buffer_view.buffer)
            offset = (buffer_view.byteOffset or 0) + (accessor.byteOffset or 0)
            stride = buffer_view.byteStride if buffer_view.byteStride else n_floats * 4
            return accessor, data, offset, stride

        N_FLOATS = {'POSITION': 3, 'NORMAL': 3, 'TANGENT': 4}

        def _duplicate_accessor(acc_idx, n_floats):
            """Fresh accessor+bufferView with a tightly-packed copy of the
            data, appended to the accessor's buffer."""
            from pygltflib import BufferView as GLTFBufferView
            accessor, data, offset, stride = _accessor_layout(acc_idx, n_floats)
            item = n_floats * 4
            raw = bytearray()
            for i in range(accessor.count):
                pos = offset + i * stride
                raw += data[pos:pos + item]
            while len(data) % 4:
                data.append(0)
            new_offset = len(data)
            data += raw
            src_bv = gltf.bufferViews[accessor.bufferView]
            gltf.bufferViews.append(GLTFBufferView(
                buffer=src_bv.buffer, byteOffset=new_offset, byteLength=len(raw),
            ))
            import copy as _copy
            new_acc = _copy.deepcopy(accessor)
            new_acc.bufferView = len(gltf.bufferViews) - 1
            new_acc.byteOffset = 0
            gltf.accessors.append(new_acc)
            return len(gltf.accessors) - 1

        # ---- Parts of a multi-part model are positioned by node
        # transforms: the world-space change M must be conjugated into each
        # mesh's local space (A = W⁻¹·M·W). Baking M directly into local
        # vertices shrank each part in place while the node offsets stayed
        # put, tearing the model apart. ----
        mesh_world = _mesh_world_matrices(gltf)
        identity = np.eye(4)

        # A mesh instanced by several nodes under DIFFERENT world transforms
        # can't satisfy them all with one set of vertices — give the extra
        # nodes their own copy (transform-relevant accessors duplicated,
        # indices/UV/color/material shared).
        mesh_w = {}
        for mesh_idx in range(len(gltf.meshes)):
            entries = mesh_world.get(mesh_idx)
            if not entries:
                # Not reachable from any scene node — e.g. a layer the user
                # just hid in the same save (apply_layer_modifications
                # detaches the node from scene.nodes/children but leaves the
                # mesh's vertex data in place). Guessing an identity world
                # transform here corrupted two things at once: the pivot
                # below skewed toward that mesh's raw local coordinates as
                # if they were already world-space, throwing off the
                # rotation/scale of the still-visible parts, and the hidden
                # mesh's own vertices got baked against a transform that
                # doesn't match its real (untouched) node transform — so if
                # it's ever unhidden again its geometry renders wrong. Skip
                # it entirely; only bake what's actually reachable/rendered.
                continue
            mesh_w[mesh_idx] = entries[0][1]
            for node_idx, w in entries[1:]:
                if np.allclose(w, entries[0][1], atol=1e-9):
                    continue
                import copy as _copy
                new_mesh = _copy.deepcopy(gltf.meshes[mesh_idx])
                for primitive in (new_mesh.primitives or []):
                    if primitive.attributes is None:
                        continue
                    for attr_name in target_attr_names:
                        a_idx = getattr(primitive.attributes, attr_name, None)
                        if a_idx is not None:
                            setattr(primitive.attributes, attr_name,
                                    _duplicate_accessor(a_idx, N_FLOATS[attr_name]))
                gltf.meshes.append(new_mesh)
                new_mesh_idx = len(gltf.meshes) - 1
                gltf.nodes[node_idx].mesh = new_mesh_idx
                mesh_w[new_mesh_idx] = w
                logger.info(f"Duplicated mesh {mesh_idx} for node {node_idx} (differing instance transforms)")

        # ---- Collect unique target accessors. Primitives commonly share
        # vertex data (one POSITION accessor reused by several per-material
        # primitives) — transforming per primitive applied the change to the
        # same bytes several times, so shared parts ended up scaled
        # 0.1 -> 0.01 while unshared parts got 0.1. An accessor shared
        # ACROSS meshes with different node transforms (exporters dedupe
        # identical parts) needs a distinct copy per local-space change. ----
        pos_targets = {}     # accessor_idx -> mesh_idx
        attr_targets = {}    # accessor_idx -> (attr_name, mesh_idx)

        def _claim(acc_idx, mesh_idx, attr_name, registry):
            claimed = registry.get(acc_idx)
            claimed_mesh = claimed if attr_name == 'POSITION' else (claimed[1] if claimed else None)
            if claimed is None or np.allclose(mesh_w[claimed_mesh], mesh_w[mesh_idx], atol=1e-9):
                return acc_idx, False
            return _duplicate_accessor(acc_idx, N_FLOATS[attr_name]), True

        for mesh_idx in range(len(gltf.meshes)):
            if mesh_idx not in mesh_w:
                continue  # unreachable/hidden — see the skip above
            for primitive in (gltf.meshes[mesh_idx].primitives or []):
                if primitive.attributes is None:
                    continue
                for attr_name in target_attr_names:
                    a_idx = getattr(primitive.attributes, attr_name, None)
                    if a_idx is None:
                        continue
                    # NORMAL/TANGENT only change under rotation (uniform
                    # scale conjugates to itself: W⁻¹·sI·W = sI).
                    registry = pos_targets if attr_name == 'POSITION' else attr_targets
                    new_idx, duplicated = _claim(a_idx, mesh_idx, attr_name, registry)
                    if duplicated:
                        setattr(primitive.attributes, attr_name, new_idx)
                        logger.info(f"Duplicated {attr_name} accessor {a_idx} (shared across differing transforms)")
                    if attr_name == 'POSITION':
                        registry.setdefault(new_idx, mesh_idx)
                    else:
                        registry.setdefault(new_idx, (attr_name, mesh_idx))

        # ---- Pivot: the model's world-space bounding-box center. A local
        # scan would mix coordinate frames on node-positioned models. ----
        mins_w = [float('inf')] * 3
        maxs_w = [float('-inf')] * 3
        for acc_idx, mesh_idx in pos_targets.items():
            accessor, data, offset, stride = _accessor_layout(acc_idx, 3)
            (w00, w01, w02, wt0), (w10, w11, w12, wt1), (w20, w21, w22, wt2) = mesh_w[mesh_idx][:3]
            for i in range(accessor.count):
                x, y, z = struct.unpack_from('fff', data, offset + i * stride)
                wv = (w00 * x + w01 * y + w02 * z + wt0,
                      w10 * x + w11 * y + w12 * z + wt1,
                      w20 * x + w21 * y + w22 * z + wt2)
                for j in range(3):
                    if wv[j] < mins_w[j]:
                        mins_w[j] = wv[j]
                    if wv[j] > maxs_w[j]:
                        maxs_w[j] = wv[j]
        if mins_w[0] == float('inf'):
            logger.warning("No readable vertices — skipping transform bake")
            return gltf
        center = (np.array(mins_w) + np.array(maxs_w)) / 2.0
        logger.info(f"Using world-space model center as pivot: ({center[0]:.3f}, {center[1]:.3f}, {center[2]:.3f})")

        # World-space change: M = T(center) · R · S · T(-center)
        linear = (rotation_matrix if rotation_matrix is not None else np.eye(3)) * scale_factor
        M = np.eye(4)
        M[:3, :3] = linear
        M[:3, 3] = center - linear @ center
        if transform_info is not None:
            transform_info['matrix'] = M

        def _local_change(mesh_idx):
            w = mesh_w[mesh_idx]
            return M if np.allclose(w, identity, atol=1e-9) else np.linalg.inv(w) @ M @ w

        for acc_idx, mesh_idx in pos_targets.items():
            accessor, data, offset, stride = _accessor_layout(acc_idx, 3)
            (a00, a01, a02, at0), (a10, a11, a12, at1), (a20, a21, a22, at2) = _local_change(mesh_idx)[:3]
            mins = [float('inf')] * 3
            maxs = [float('-inf')] * 3
            for i in range(accessor.count):
                pos = offset + i * stride
                x, y, z = struct.unpack_from('fff', data, pos)
                nx = a00 * x + a01 * y + a02 * z + at0
                ny = a10 * x + a11 * y + a12 * z + at1
                nz = a20 * x + a21 * y + a22 * z + at2
                struct.pack_into('fff', data, pos, nx, ny, nz)
                for j, v in enumerate((nx, ny, nz)):
                    if v < mins[j]:
                        mins[j] = v
                    if v > maxs[j]:
                        maxs[j] = v

            # POSITION min/max is what viewers frame and place the model
            # from — stale bounds survive the bake otherwise.
            if accessor.count:
                accessor.min = [float(v) for v in mins]
                accessor.max = [float(v) for v in maxs]
            logger.info(f"Transformed {accessor.count} vertices in POSITION accessor {acc_idx}")

        # Rotate NORMAL / TANGENT too — positions rotating while normals
        # stay put leaves the baked model lit as if it never rotated.
        # Directions transform differently from points: normals by the
        # inverse-transpose of the linear part, tangents by the linear part
        # itself (TANGENT is VEC4: xyz rotated, w handedness kept); both
        # renormalized so uniform scale cancels out.
        for acc_idx, (attr_name, mesh_idx) in attr_targets.items():
            n_floats = N_FLOATS[attr_name]
            accessor, data, offset, stride = _accessor_layout(acc_idx, n_floats)
            al = _local_change(mesh_idx)[:3, :3]
            dir_m = np.linalg.inv(al).T if attr_name == 'NORMAL' else al
            (d00, d01, d02), (d10, d11, d12), (d20, d21, d22) = dir_m
            fmt = f'{n_floats}f'
            for i in range(accessor.count):
                pos = offset + i * stride
                vals = struct.unpack_from(fmt, data, pos)
                x, y, z = vals[:3]
                nx = d00 * x + d01 * y + d02 * z
                ny = d10 * x + d11 * y + d12 * z
                nz = d20 * x + d21 * y + d22 * z
                norm = (nx * nx + ny * ny + nz * nz) ** 0.5
                if norm > 1e-12:
                    nx, ny, nz = nx / norm, ny / norm, nz / norm
                struct.pack_into(fmt, data, pos, nx, ny, nz, *vals[3:])
            logger.info(f"Rotated {accessor.count} {attr_name} vectors in accessor {acc_idx}")

        # ---- Commit: write buffers back only now that every accessor
        # transformed cleanly. ----
        for buf_idx, data in buffers_data.items():
            buffer = gltf.buffers[buf_idx]
            if buffer.uri and buffer.uri.startswith('data:'):
                buffer.uri = 'data:application/octet-stream;base64,' + base64.b64encode(bytes(data)).decode('utf-8')
            else:
                gltf.set_binary_blob(bytes(data))
            buffer.byteLength = len(data)

        logger.info(f"✅ Geometry transformed: {', '.join(transforms)}")

    logger.info("Transform modifications applied (rotation and scale baked into vertices)")

    return gltf


def euler_to_quaternion(rx, ry, rz):
    """
    Convert Euler angles (in radians) to quaternion (x, y, z, w)
    Rotation order: XYZ (intrinsic rotations)
    Args:
        rx: rotation around X axis (radians)
        ry: rotation around Y axis (radians)
        rz: rotation around Z axis (radians)
    Returns:
        [x, y, z, w] quaternion
    """
    # Calculate half angles
    cx = np.cos(rx * 0.5)
    sx = np.sin(rx * 0.5)
    cy = np.cos(ry * 0.5)
    sy = np.sin(ry * 0.5)
    cz = np.cos(rz * 0.5)
    sz = np.sin(rz * 0.5)
    
    # XYZ rotation order
    w = cx * cy * cz + sx * sy * sz
    x = sx * cy * cz - cx * sy * sz
    y = cx * sy * cz + sx * cy * sz
    z = cx * cy * sz - sx * sy * cz
    
    return [x, y, z, w]


def modify_glb(input_path, output_path, modifications, transform_info=None):
    """
    Main function to modify a GLB file
    Preserves all GLB features including animations, skins, morphs, etc.

    Args:
        input_path: Path to input GLB file
        output_path: Path to output GLB file
        modifications: dict with 'material' and 'transform' keys
        transform_info: optional dict; if a transform was baked, this is
            populated with {'matrix': <4x4 numpy world-space change>} so the
            caller can keep anything else stored in that same world-space
            frame (e.g. hotspot positions) in sync. Left untouched if there
            was no 'transform' in modifications, or if apply_transform_
            modifications baked nothing (e.g. no readable vertices).

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Loading GLB from {input_path}")
        
        # Load the GLB file using pygltflib
        gltf = GLTF2().load(input_path)
        
        logger.info(f"Loaded GLB:")
        logger.info(f"  - Nodes: {len(gltf.nodes) if gltf.nodes else 0}")
        logger.info(f"  - Meshes: {len(gltf.meshes) if gltf.meshes else 0}")
        logger.info(f"  - Materials: {len(gltf.materials) if gltf.materials else 0}")
        logger.info(f"  - Animations: {len(gltf.animations) if gltf.animations else 0}")
        logger.info(f"  - Skins: {len(gltf.skins) if gltf.skins else 0}")
        
        # Apply material modifications
        if 'material' in modifications:
            mat_mods = modifications['material']
            gltf = apply_material_modifications(gltf, mat_mods)

            # Apply texture if provided. Pass the user's tint through so the
            # texture step doesn't clobber an explicitly chosen color.
            if mat_mods.get('texture'):
                tint_rgba = None
                if mat_mods.get('tint_textures') and mat_mods.get('color'):
                    try:
                        raw = mat_mods['color']
                        rgb = tuple(float(c) for c in raw[:3]) if isinstance(raw, (list, tuple)) else hex_to_rgb(raw)
                        tint_rgba = list(rgb) + [float(mat_mods.get('opacity', 1.0))]
                    except Exception as te:
                        logger.warning(f"Could not derive texture tint from color: {te}")
                gltf = apply_texture_modifications(gltf, mat_mods['texture'], tint_rgba=tint_rgba)

        # Apply per-layer visibility/color modifications
        if 'layers' in modifications:
            gltf = apply_layer_modifications(gltf, modifications['layers'])

        # Apply transform modifications
        if 'transform' in modifications:
            gltf = apply_transform_modifications(gltf, modifications['transform'], transform_info=transform_info)

        # Bake exploded layer positions (only present when the user explicitly
        # pressed "Save Exploded Layout" — never part of a regular save)
        if 'explode' in modifications:
            gltf = apply_explode_modifications(gltf, modifications['explode'])

        # Export modified GLB
        logger.info(f"Exporting modified GLB to {output_path}")
        gltf.save(output_path)
        
        # Verify output file exists
        if Path(output_path).exists():
            file_size = Path(output_path).stat().st_size
            logger.info(f"Successfully exported GLB ({file_size} bytes)")
            
            # Verify animations are preserved
            gltf_verify = GLTF2().load(output_path)
            if gltf_verify.animations:
                logger.info(f"✅ Animations preserved: {len(gltf_verify.animations)} animations")
            if gltf_verify.skins:
                logger.info(f"✅ Skins preserved: {len(gltf_verify.skins)} skins")
            
            return True
        else:
            logger.error("Output file was not created")
            return False
            
    except Exception as e:
        logger.error(f"Error modifying GLB: {e}", exc_info=True)
        return False
