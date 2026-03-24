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
import struct
import base64
from PIL import Image
import io

logger = logging.getLogger(__name__)


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple (0-1 range)"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def euler_to_rotation_matrix(rx, ry, rz):
    """
    Convert Euler angles (in radians, YXZ intrinsic order) to a 3x3 rotation matrix
    Positive angles rotate clockwise when looking along the positive axis direction
    
    Args:
        rx, ry, rz: Rotation angles in radians (X, Y, Z axes)
    
    Returns:
        3x3 numpy rotation matrix
    """
    # Rotation matrices for each axis (clockwise direction)
    # Inverted sin signs for clockwise rotation
    Rx = np.array([
        [1, 0, 0],
        [0, np.cos(rx), np.sin(rx)],   # Inverted sin for clockwise
        [0, -np.sin(rx), np.cos(rx)]
    ])
    
    Ry = np.array([
        [np.cos(ry), 0, -np.sin(ry)],  # Inverted sin for clockwise
        [0, 1, 0],
        [np.sin(ry), 0, np.cos(ry)]
    ])
    
    Rz = np.array([
        [np.cos(rz), np.sin(rz), 0],   # Inverted sin for clockwise
        [-np.sin(rz), np.cos(rz), 0],
        [0, 0, 1]
    ])
    
    # YXZ intrinsic order: R = Rz * Rx * Ry
    return Rz @ Rx @ Ry


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
        name_l = name.lower()
        alpha_mode = (material.alphaMode or "OPAQUE")
        # Detect foliage strictly by name or pre-set alpha modes
        is_transparent_like = alpha_mode in ("BLEND", "MASK") or any(k in name_l for k in ["leaf", "leaves", "foliage", "db2x2"]) 
        
        # Foliage-safe defaults (do BEFORE applying user knobs)
        if is_transparent_like:
            try:
                # Ensure visibility-friendly defaults
                if pbr.baseColorFactor is None:
                    pbr.baseColorFactor = [1.0, 1.0, 1.0, 1.0]
                pbr.metallicFactor = 0.0
                pbr.roughnessFactor = 1.0
                # Transparency and double sided to ensure leaves render both sides
                material.alphaMode = "BLEND"
                material.doubleSided = True
                logger.info(f"Foliage-safe defaults applied to {name}: alphaMode=BLEND, doubleSided=True, metallic=0, roughness=1")
            except Exception as e:
                logger.warning(f"Failed to apply foliage defaults on {name}: {e}")
        
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
                # Set baseColorFactor (RGBA)
                pbr.baseColorFactor = list(color_rgb) + [opacity]
                logger.info(f"Applied color {raw_color} with opacity {opacity} to material {i}")
                
                # Set alpha mode based on opacity
                if opacity < 1.0:
                    material.alphaMode = 'BLEND'
                    logger.info(f"Set alphaMode to BLEND for material {i} (opacity < 1.0)")
                else:
                    material.alphaMode = 'OPAQUE'
            except Exception as e:
                logger.error(f"Failed to apply color to material {i}: {e}")
        
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


def _ensure_texcoord0(gltf):
    """
    Generate TEXCOORD_0 for mesh primitives that lack it.
    Uses normalised bounding-box projection (X→U, Y→V) so that
    any texture applied later has valid UV coordinates.
    """
    from pygltflib import Accessor, BufferView as BV

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

            # Compute bounding box
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            range_x = max_x - min_x if max_x != min_x else 1.0
            range_y = max_y - min_y if max_y != min_y else 1.0

            # Generate UVs: normalised box projection
            uv_data = bytearray()
            for x, y, z in positions:
                u = (x - min_x) / range_x
                v = (y - min_y) / range_y
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


def apply_texture_modifications(gltf, texture_data_base64):
    """
    Apply texture to all materials in the GLTF.
    Embeds the image into the GLB binary buffer (not as data URI)
    and generates TEXCOORD_0 if the mesh lacks UV coordinates.
    """
    if not texture_data_base64:
        logger.info("No texture data provided, skipping texture modification")
        return gltf

    try:
        logger.info("Applying texture modifications")

        # Decode base64 image
        if ',' in texture_data_base64:
            texture_data_base64 = texture_data_base64.split(',')[1]

        image_bytes = base64.b64decode(texture_data_base64)
        logger.info(f"Decoded texture image: {len(image_bytes)} bytes")

        # Open image with PIL to optimise
        img = Image.open(io.BytesIO(image_bytes))
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
        new_blob = blob + image_bytes
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
                    material.pbrMetallicRoughness.baseColorFactor = [1.0, 1.0, 1.0, 1.0]
                    texture_info = TextureInfo()
                    texture_info.index = texture_index
                    texture_info.texCoord = 0
                    material.pbrMetallicRoughness.baseColorTexture = texture_info
                    logger.info(f"Applied texture to material {i}")

        logger.info("Texture embedding completed successfully")
        return gltf

    except Exception as e:
        logger.error(f"Failed to apply texture: {e}", exc_info=True)
        return gltf


def normalize_model_to_center(gltf):
    """
    Normalize model by moving its center to origin (0, 0, 0)
    This ensures consistent pivot behavior in viewer
    
    Note: Basis correction (Z-up to Y-up) is applied only when rotation is applied
    via apply_transform_modifications, not during initial normalization.
    This keeps the model in its original orientation on upload.
    
    Returns:
        GLTF2: Modified GLTF object
    """
    logger.info("Normalizing model to center origin")
    
    # Calculate current center
    center_x, center_y, center_z = calculate_model_center(gltf)
    
    try:
        # Move all vertices to center the model at origin
        for mesh_idx, mesh in enumerate(gltf.meshes):
            if not mesh.primitives:
                continue
            
            for prim_idx, primitive in enumerate(mesh.primitives):
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
                    
                    # Parse and translate vertices
                    offset = buffer_view.byteOffset if buffer_view.byteOffset else 0
                    offset += accessor.byteOffset if accessor.byteOffset else 0
                    vertex_count = accessor.count
                    stride = buffer_view.byteStride if buffer_view.byteStride else 12
                    
                    new_data = bytearray(binary_data)
                    for i in range(vertex_count):
                        pos = offset + i * stride
                        x, y, z = struct.unpack_from('fff', binary_data, pos)
                        
                        # Translate to origin
                        x -= center_x
                        y -= center_y
                        z -= center_z
                        
                        struct.pack_into('fff', new_data, pos, x, y, z)
                    
                    # Update buffer
                    if buffer.uri and buffer.uri.startswith('data:'):
                        buffer.uri = 'data:application/octet-stream;base64,' + base64.b64encode(bytes(new_data)).decode('utf-8')
                    else:
                        gltf.set_binary_blob(bytes(new_data))
                    
                    logger.info(f"Translated {vertex_count} vertices in mesh {mesh_idx}, primitive {prim_idx}")
        
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


def apply_transform_modifications(gltf, transform_mods):
    """
    Apply transform modifications to GLTF with model center as pivot
    - Scale: Applied to mesh vertices around model center
    - Rotation: Applied to node transforms around model center
    
    Args:
        gltf: GLTF2 object
        transform_mods: dict with 'scale' and 'rotation' (x, y, z in degrees)
    """
    logger.info(f"Applying transform modifications: {transform_mods}")
    
    # Calculate model center to use as pivot
    center_x, center_y, center_z = calculate_model_center(gltf)
    logger.info(f"Using model center as pivot: ({center_x:.3f}, {center_y:.3f}, {center_z:.3f})")
    
    # Get rotation parameters
    rotation = transform_mods.get('rotation', {})
    rx = np.radians(float(rotation.get('x', 0)))
    ry = np.radians(float(rotation.get('y', 0)))
    rz = np.radians(float(rotation.get('z', 0)))
    has_rotation = (rx != 0 or ry != 0 or rz != 0)
    
    # Calculate rotation matrix if needed
    rotation_matrix = None
    if has_rotation:
        rotation_matrix = euler_to_rotation_matrix(rx, ry, rz)
        logger.info(f"Rotation matrix calculated for ({rotation.get('x', 0)}°, {rotation.get('y', 0)}°, {rotation.get('z', 0)}°)")
    
    # Apply scale and rotation to mesh vertices (permanent geometry change)
    scale_factor = float(transform_mods.get('scale', 1.0))
    
    if (scale_factor != 1.0 or has_rotation) and gltf.meshes:
            transforms = []
            if has_rotation:
                transforms.append(f"rotation ({rotation.get('x', 0)}°, {rotation.get('y', 0)}°, {rotation.get('z', 0)}°)")
            if scale_factor != 1.0:
                transforms.append(f"scale {scale_factor}")
            logger.info(f"Applying {' and '.join(transforms)} to mesh vertices")
            try:
                for mesh_idx, mesh in enumerate(gltf.meshes):
                    if not mesh.primitives:
                        continue
                    
                    for prim_idx, primitive in enumerate(mesh.primitives):
                        if primitive.attributes is None:
                            continue
                        
                        # Get POSITION accessor
                        if hasattr(primitive.attributes, 'POSITION') and primitive.attributes.POSITION is not None:
                            pos_accessor_idx = primitive.attributes.POSITION
                            accessor = gltf.accessors[pos_accessor_idx]
                            buffer_view = gltf.bufferViews[accessor.bufferView]
                            buffer = gltf.buffers[buffer_view.buffer]
                            
                            # Get binary data
                            import base64
                            if buffer.uri and buffer.uri.startswith('data:'):
                                # Data URI (embedded as base64)
                                data_start = buffer.uri.find(',') + 1
                                binary_data = base64.b64decode(buffer.uri[data_start:])
                            elif hasattr(gltf, 'binary_blob') and gltf.binary_blob():
                                # GLB binary chunk
                                binary_data = gltf.binary_blob()
                            else:
                                logger.warning(f"Cannot scale: buffer {buffer_view.buffer} has no accessible data")
                                continue
                            
                            # Parse vertex positions
                            import struct
                            offset = buffer_view.byteOffset if buffer_view.byteOffset else 0
                            offset += accessor.byteOffset if accessor.byteOffset else 0
                            
                            # Read and scale vertices
                            vertex_count = accessor.count
                            stride = buffer_view.byteStride if buffer_view.byteStride else 12  # 3 floats
                            
                            new_data = bytearray(binary_data)
                            for i in range(vertex_count):
                                pos = offset + i * stride
                                # Read XYZ
                                x, y, z = struct.unpack_from('fff', binary_data, pos)
                                
                                # Transform around model center (pivot)
                                # 1. Translate to origin (relative to center)
                                x -= center_x
                                y -= center_y
                                z -= center_z
                                
                                # 2. Apply rotation (if any)
                                if rotation_matrix is not None:
                                    vertex = np.array([x, y, z])
                                    rotated = rotation_matrix @ vertex
                                    x, y, z = rotated[0], rotated[1], rotated[2]
                                
                                # 3. Apply scale
                                if scale_factor != 1.0:
                                    x *= scale_factor
                                    y *= scale_factor
                                    z *= scale_factor
                                
                                # 4. Translate back
                                x += center_x
                                y += center_y
                                z += center_z
                                
                                # Write back
                                struct.pack_into('fff', new_data, pos, x, y, z)
                            
                            # Update buffer based on type
                            if buffer.uri and buffer.uri.startswith('data:'):
                                # Update data URI
                                buffer.uri = 'data:application/octet-stream;base64,' + base64.b64encode(bytes(new_data)).decode('utf-8')
                            else:
                                # Update GLB binary chunk
                                gltf.set_binary_blob(bytes(new_data))
                            
                            transform_desc = []
                            if has_rotation:
                                transform_desc.append(f"rotated ({rotation.get('x', 0)}°, {rotation.get('y', 0)}°, {rotation.get('z', 0)}°)")
                            if scale_factor != 1.0:
                                transform_desc.append(f"scaled {scale_factor}x")
                            logger.info(f"Transformed {vertex_count} vertices ({', '.join(transform_desc)}) in mesh {mesh_idx}, primitive {prim_idx}")
                
                result_desc = []
                if has_rotation:
                    result_desc.append(f"rotated ({rotation.get('x', 0)}°, {rotation.get('y', 0)}°, {rotation.get('z', 0)}°)")
                if scale_factor != 1.0:
                    result_desc.append(f"scaled by {scale_factor}")
                logger.info(f"✅ Geometry transformed: {', '.join(result_desc) if result_desc else 'no changes'}")
            except Exception as e:
                logger.error(f"Failed to transform geometry: {e}", exc_info=True)
    
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


def modify_glb(input_path, output_path, modifications):
    """
    Main function to modify a GLB file
    Preserves all GLB features including animations, skins, morphs, etc.
    
    Args:
        input_path: Path to input GLB file
        output_path: Path to output GLB file
        modifications: dict with 'material' and 'transform' keys
    
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
            gltf = apply_material_modifications(gltf, modifications['material'])
            
            # Apply texture if provided
            if 'texture' in modifications['material'] and modifications['material']['texture']:
                gltf = apply_texture_modifications(gltf, modifications['material']['texture'])
        
        # Apply transform modifications
        if 'transform' in modifications:
            gltf = apply_transform_modifications(gltf, modifications['transform'])
        
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
