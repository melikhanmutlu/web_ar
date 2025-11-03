"""
GLB Modifier Module
Applies material and transform modifications to GLB files
Preserves animations, skins, and all other GLB features
"""

import numpy as np
import logging
from pathlib import Path
from pygltflib import GLTF2, Image as GLTFImage, Texture, Sampler
import struct
import base64
from PIL import Image
import io

logger = logging.getLogger(__name__)


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
        logger.warning("No materials found in GLB")
        return gltf
    
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
                color_hex = material_mods['color']
                color_rgb = hex_to_rgb(color_hex)
                # Get opacity value (default 1.0)
                opacity = float(material_mods.get('opacity', 1.0))
                # Set baseColorFactor (RGBA)
                pbr.baseColorFactor = list(color_rgb) + [opacity]
                logger.info(f"Applied color {color_hex} with opacity {opacity} to material {i}")
                
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


def apply_texture_modifications(gltf, texture_data_base64):
    """
    Apply texture to all materials in the GLTF
    Embeds texture as base64 data URI in GLB
    
    Args:
        gltf: GLTF2 object
        texture_data_base64: Base64 encoded image data (data:image/png;base64,...)
    
    Returns:
        gltf: Modified GLTF2 object
    """
    if not texture_data_base64:
        logger.info("No texture data provided, skipping texture modification")
        return gltf
    
    try:
        logger.info("Applying texture modifications")
        
        # Decode base64 image
        if ',' in texture_data_base64:
            # Remove data URI prefix (data:image/png;base64,)
            texture_data_base64 = texture_data_base64.split(',')[1]
        
        image_bytes = base64.b64decode(texture_data_base64)
        logger.info(f"Decoded texture image: {len(image_bytes)} bytes")
        
        # Open image with PIL to get format and optimize
        img = Image.open(io.BytesIO(image_bytes))
        logger.info(f"Image format: {img.format}, size: {img.size}, mode: {img.mode}")
        
        # Convert to RGB if needed (remove alpha for JPG compatibility)
        if img.mode in ('RGBA', 'LA', 'P'):
            # Create white background
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        
        # Optimize image size (max 2048x2048 for performance)
        max_size = 2048
        if img.width > max_size or img.height > max_size:
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            logger.info(f"Resized image to: {img.size}")
        
        # Save as PNG to buffer
        buffer = io.BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        image_bytes = buffer.getvalue()
        logger.info(f"Optimized texture: {len(image_bytes)} bytes")
        
        # Create data URI for embedding
        image_data_uri = f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"
        
        # Initialize arrays if not present
        if gltf.images is None:
            gltf.images = []
        if gltf.textures is None:
            gltf.textures = []
        if gltf.samplers is None:
            gltf.samplers = []
        
        # Add sampler (texture filtering settings)
        sampler = Sampler()
        sampler.magFilter = 9729  # LINEAR
        sampler.minFilter = 9987  # LINEAR_MIPMAP_LINEAR
        sampler.wrapS = 10497     # REPEAT
        sampler.wrapT = 10497     # REPEAT
        sampler_index = len(gltf.samplers)
        gltf.samplers.append(sampler)
        
        # Add image with data URI
        gltf_image = GLTFImage()
        gltf_image.uri = image_data_uri
        image_index = len(gltf.images)
        gltf.images.append(gltf_image)
        logger.info(f"Added image at index {image_index}")
        
        # Add texture referencing the image
        texture = Texture()
        texture.source = image_index
        texture.sampler = sampler_index
        texture_index = len(gltf.textures)
        gltf.textures.append(texture)
        logger.info(f"Added texture at index {texture_index}")
        
        # Apply texture to all materials
        if gltf.materials:
            for i, material in enumerate(gltf.materials):
                if material.pbrMetallicRoughness:
                    # Preserve existing baseColorFactor if it exists
                    existing_color = material.pbrMetallicRoughness.baseColorFactor
                    if existing_color:
                        logger.info(f"Preserving existing baseColorFactor for material {i}: {existing_color}")
                    
                    # Apply texture
                    material.pbrMetallicRoughness.baseColorTexture = type('obj', (object,), {
                        'index': texture_index,
                        'texCoord': 0
                    })()
                    logger.info(f"Applied texture to material {i}")
        
        logger.info("✅ Texture embedding completed successfully")
        return gltf
        
    except Exception as e:
        logger.error(f"Failed to apply texture: {e}", exc_info=True)
        return gltf


def normalize_model_to_center(gltf):
    """
    Normalize model by moving its center to origin (0, 0, 0)
    This ensures consistent pivot behavior in viewer
    
    Returns:
        GLTF2: Modified GLTF object
    """
    logger.info("Normalizing model to center origin")
    
    # Calculate current center
    center_x, center_y, center_z = calculate_model_center(gltf)
    
    # If already centered, no need to modify
    if abs(center_x) < 0.0001 and abs(center_y) < 0.0001 and abs(center_z) < 0.0001:
        logger.info("Model already centered at origin")
        return gltf
    
    logger.info(f"Moving model center from ({center_x:.3f}, {center_y:.3f}, {center_z:.3f}) to origin")
    
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
    Uses scipy for accurate rotation matching model-viewer
    
    Args:
        rx: Rotation around X axis (radians)
        ry: Rotation around Y axis (radians)
        rz: Rotation around Z axis (radians)
    
    Returns:
        3x3 numpy rotation matrix
    """
    try:
        from scipy.spatial.transform import Rotation as R
        # model-viewer uses extrinsic XYZ rotation (applied in order: X, then Y, then Z)
        # In scipy, this is 'xyz' with extrinsic=True or 'XYZ' (uppercase = extrinsic)
        rot = R.from_euler('XYZ', [rx, ry, rz], degrees=False)
        return rot.as_matrix()
    except ImportError:
        # Fallback to manual matrix multiplication if scipy not available
        logger.warning("scipy not available, using manual rotation matrix")
        
        # Rotation matrix around X axis
        Rx = np.array([
            [1, 0, 0],
            [0, np.cos(rx), -np.sin(rx)],
            [0, np.sin(rx), np.cos(rx)]
        ])
        
        # Rotation matrix around Y axis
        Ry = np.array([
            [np.cos(ry), 0, np.sin(ry)],
            [0, 1, 0],
            [-np.sin(ry), 0, np.cos(ry)]
        ])
        
        # Rotation matrix around Z axis
        Rz = np.array([
            [np.cos(rz), -np.sin(rz), 0],
            [np.sin(rz), np.cos(rz), 0],
            [0, 0, 1]
        ])
        
        # Extrinsic XYZ = Rz @ Ry @ Rx
        return Rz @ Ry @ Rx


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
    
    # Prepare rotation matrix if rotation is specified
    rotation_matrix = None
    if 'rotation' in transform_mods:
        rotation = transform_mods['rotation']
        # Note: model-viewer's orientation rotates the camera view, not the model
        # To match the visual result, we need to apply inverse rotation to the model
        # Or negate the Y and Z rotations (depending on coordinate system)
        rx = np.radians(float(rotation.get('x', 0)))
        ry = -np.radians(float(rotation.get('y', 0)))  # Negate Y
        rz = np.radians(float(rotation.get('z', 0)))
        
        if rx != 0 or ry != 0 or rz != 0:
            rotation_matrix = create_rotation_matrix(rx, ry, rz)
            logger.info(f"Created rotation matrix for ({rotation.get('x', 0)}°, {-rotation.get('y', 0)}°, {rotation.get('z', 0)}°) [Y negated]")
    
    # Apply scale and rotation to mesh vertices (permanent geometry change)
    scale_factor = float(transform_mods.get('scale', 1.0))
    
    if (scale_factor != 1.0 or rotation_matrix is not None) and gltf.meshes:
            logger.info(f"Applying scale {scale_factor} to mesh vertices")
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
                                
                                # 2. Apply rotation if specified
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
                            if rotation_matrix is not None:
                                transform_desc.append("rotated")
                            if scale_factor != 1.0:
                                transform_desc.append(f"scaled {scale_factor}x")
                            logger.info(f"Transformed {vertex_count} vertices ({', '.join(transform_desc)}) in mesh {mesh_idx}, primitive {prim_idx}")
                
                result_desc = []
                if rotation_matrix is not None:
                    result_desc.append(f"rotation applied")
                if scale_factor != 1.0:
                    result_desc.append(f"scaled by {scale_factor}")
                logger.info(f"✅ Geometry transformed: {', '.join(result_desc)}")
            except Exception as e:
                logger.error(f"Failed to transform geometry: {e}", exc_info=True)
    
    # Note: Both scale and rotation are now applied directly to geometry vertices
    # This ensures consistent behavior between preview and saved model
    logger.info("Transform modifications applied to geometry vertices")
    
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
