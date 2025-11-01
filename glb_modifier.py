"""
GLB Modifier Module
Applies material and transform modifications to GLB files
Preserves animations, skins, and all other GLB features
"""

import numpy as np
import logging
from pathlib import Path
from pygltflib import GLTF2
import struct

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
        
        # Apply base color
        if 'color' in material_mods and material_mods['color']:
            try:
                color_rgb = hex_to_rgb(material_mods['color'])
                # Set baseColorFactor (RGBA)
                pbr.baseColorFactor = list(color_rgb) + [1.0]
                logger.info(f"Applied color {material_mods['color']} to material {i}")
            except Exception as e:
                logger.error(f"Failed to apply color to material {i}: {e}")
        
        # Apply metalness
        if 'metalness' in material_mods:
            try:
                pbr.metallicFactor = float(material_mods['metalness'])
                logger.info(f"Applied metalness {material_mods['metalness']} to material {i}")
            except Exception as e:
                logger.error(f"Failed to apply metalness to material {i}: {e}")
        
        # Apply roughness
        if 'roughness' in material_mods:
            try:
                pbr.roughnessFactor = float(material_mods['roughness'])
                logger.info(f"Applied roughness {material_mods['roughness']} to material {i}")
            except Exception as e:
                logger.error(f"Failed to apply roughness to material {i}: {e}")
    
    return gltf


def apply_transform_modifications(gltf, transform_mods):
    """
    Apply transform modifications to all root nodes in the GLTF
    IMPORTANT: This modifies node transforms, preserving animations
    
    Args:
        gltf: GLTF2 object
        transform_mods: dict with 'scale' and 'rotation' (x, y, z in degrees)
    """
    logger.info(f"Applying transform modifications: {transform_mods}")
    
    if not gltf.nodes:
        logger.warning("No nodes found in GLB")
        return gltf
    
    # Find root nodes (nodes without parents)
    root_nodes = []
    all_child_indices = set()
    
    for node in gltf.nodes:
        if node.children:
            all_child_indices.update(node.children)
    
    for i, node in enumerate(gltf.nodes):
        if i not in all_child_indices:
            root_nodes.append(i)
    
    logger.info(f"Found {len(root_nodes)} root nodes: {root_nodes}")
    
    # Apply transforms to root nodes only
    for node_idx in root_nodes:
        node = gltf.nodes[node_idx]
        
        # Initialize transform components if not present
        if node.scale is None:
            node.scale = [1.0, 1.0, 1.0]
        if node.rotation is None:
            node.rotation = [0.0, 0.0, 0.0, 1.0]  # Quaternion (x, y, z, w)
        if node.translation is None:
            node.translation = [0.0, 0.0, 0.0]
        
        # Apply scale
        if 'scale' in transform_mods:
            try:
                scale_factor = float(transform_mods['scale'])
                if scale_factor != 1.0:
                    node.scale = [scale_factor, scale_factor, scale_factor]
                    logger.info(f"Applied scale {scale_factor} to node {node_idx}")
            except Exception as e:
                logger.error(f"Failed to apply scale to node {node_idx}: {e}")
        
        # Apply rotation (convert Euler angles to quaternion)
        if 'rotation' in transform_mods:
            try:
                rotation = transform_mods['rotation']
                rx = np.radians(float(rotation.get('x', 0)))
                ry = np.radians(float(rotation.get('y', 0)))
                rz = np.radians(float(rotation.get('z', 0)))
                
                # Convert Euler angles (ZYX order) to quaternion
                quat = euler_to_quaternion(rx, ry, rz)
                node.rotation = quat
                logger.info(f"Applied rotation ({rotation.get('x', 0)}°, {rotation.get('y', 0)}°, {rotation.get('z', 0)}°) to node {node_idx}")
            except Exception as e:
                logger.error(f"Failed to apply rotation to node {node_idx}: {e}")
    
    return gltf


def euler_to_quaternion(roll, pitch, yaw):
    """
    Convert Euler angles to quaternion (x, y, z, w)
    Order: ZYX (yaw, pitch, roll)
    """
    cy = np.cos(yaw * 0.5)
    sy = np.sin(yaw * 0.5)
    cp = np.cos(pitch * 0.5)
    sp = np.sin(pitch * 0.5)
    cr = np.cos(roll * 0.5)
    sr = np.sin(roll * 0.5)
    
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    
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
