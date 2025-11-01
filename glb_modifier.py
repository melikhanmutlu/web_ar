"""
GLB Modifier Module
Applies material and transform modifications to GLB files
"""

import trimesh
import numpy as np
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def hex_to_rgb(hex_color):
    """Convert hex color to RGB tuple (0-1 range)"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def apply_material_modifications(scene, material_mods):
    """
    Apply material modifications to all geometries in the scene
    
    Args:
        scene: Trimesh scene object
        material_mods: dict with 'color', 'metalness', 'roughness'
    """
    logger.info(f"Applying material modifications: {material_mods}")
    
    for geometry_name in scene.geometry:
        geom = scene.geometry[geometry_name]
        
        # Ensure geometry has visual material
        if not hasattr(geom.visual, 'material'):
            logger.warning(f"Geometry {geometry_name} has no material, skipping")
            continue
        
        material = geom.visual.material
        
        # Apply base color
        if 'color' in material_mods and material_mods['color']:
            try:
                color_rgb = hex_to_rgb(material_mods['color'])
                # Set baseColorFactor (RGBA)
                material.baseColorFactor = list(color_rgb) + [1.0]
                logger.info(f"Applied color {material_mods['color']} to {geometry_name}")
            except Exception as e:
                logger.error(f"Failed to apply color: {e}")
        
        # Apply metalness
        if 'metalness' in material_mods:
            try:
                material.metallicFactor = float(material_mods['metalness'])
                logger.info(f"Applied metalness {material_mods['metalness']} to {geometry_name}")
            except Exception as e:
                logger.error(f"Failed to apply metalness: {e}")
        
        # Apply roughness
        if 'roughness' in material_mods:
            try:
                material.roughnessFactor = float(material_mods['roughness'])
                logger.info(f"Applied roughness {material_mods['roughness']} to {geometry_name}")
            except Exception as e:
                logger.error(f"Failed to apply roughness: {e}")
    
    return scene


def apply_transform_modifications(scene, transform_mods):
    """
    Apply transform modifications to the scene
    
    Args:
        scene: Trimesh scene object
        transform_mods: dict with 'scale' and 'rotation' (x, y, z in degrees)
    """
    logger.info(f"Applying transform modifications: {transform_mods}")
    
    # Apply scale
    if 'scale' in transform_mods:
        try:
            scale_factor = float(transform_mods['scale'])
            if scale_factor != 1.0:
                scene.apply_scale(scale_factor)
                logger.info(f"Applied scale {scale_factor}")
        except Exception as e:
            logger.error(f"Failed to apply scale: {e}")
    
    # Apply rotation
    if 'rotation' in transform_mods:
        try:
            rotation = transform_mods['rotation']
            
            # Convert degrees to radians
            rx = np.radians(float(rotation.get('x', 0)))
            ry = np.radians(float(rotation.get('y', 0)))
            rz = np.radians(float(rotation.get('z', 0)))
            
            # Create rotation matrix (ZYX order - standard in 3D)
            # Apply rotations in order: Z, then Y, then X
            if rz != 0:
                matrix_z = trimesh.transformations.rotation_matrix(rz, [0, 0, 1])
                scene.apply_transform(matrix_z)
                logger.info(f"Applied Z rotation {rotation.get('z', 0)}°")
            
            if ry != 0:
                matrix_y = trimesh.transformations.rotation_matrix(ry, [0, 1, 0])
                scene.apply_transform(matrix_y)
                logger.info(f"Applied Y rotation {rotation.get('y', 0)}°")
            
            if rx != 0:
                matrix_x = trimesh.transformations.rotation_matrix(rx, [1, 0, 0])
                scene.apply_transform(matrix_x)
                logger.info(f"Applied X rotation {rotation.get('x', 0)}°")
                
        except Exception as e:
            logger.error(f"Failed to apply rotation: {e}")
    
    return scene


def modify_glb(input_path, output_path, modifications):
    """
    Main function to modify a GLB file
    
    Args:
        input_path: Path to input GLB file
        output_path: Path to output GLB file
        modifications: dict with 'material' and 'transform' keys
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Loading GLB from {input_path}")
        
        # Load the GLB file
        scene = trimesh.load(input_path, force='scene')
        
        if not isinstance(scene, trimesh.Scene):
            logger.error("Loaded object is not a scene")
            return False
        
        logger.info(f"Loaded scene with {len(scene.geometry)} geometries")
        
        # Apply material modifications
        if 'material' in modifications:
            scene = apply_material_modifications(scene, modifications['material'])
        
        # Apply transform modifications
        if 'transform' in modifications:
            scene = apply_transform_modifications(scene, modifications['transform'])
        
        # Export modified scene
        logger.info(f"Exporting modified GLB to {output_path}")
        scene.export(output_path, file_type='glb')
        
        # Verify output file exists
        if Path(output_path).exists():
            file_size = Path(output_path).stat().st_size
            logger.info(f"Successfully exported GLB ({file_size} bytes)")
            return True
        else:
            logger.error("Output file was not created")
            return False
            
    except Exception as e:
        logger.error(f"Error modifying GLB: {e}", exc_info=True)
        return False
