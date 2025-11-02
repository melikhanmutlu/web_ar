"""
Mesh Slicer Module
Handles 3D mesh slicing operations using trimesh
"""
import os
import logging
import trimesh
import numpy as np
from pygltflib import GLTF2

logger = logging.getLogger(__name__)


def slice_mesh(input_path, output_path, plane_origin, plane_normal, keep_side='positive'):
    """
    Slice a GLB mesh with a plane and keep one side
    Uses trimesh's built-in slice_plane method for accurate slicing
    
    Args:
        input_path: Path to input GLB file
        output_path: Path to output GLB file
        plane_origin: [x, y, z] coordinates of a point on the plane
        plane_normal: [x, y, z] normal vector of the plane
        keep_side: 'positive' or 'negative' - which side of the plane to keep
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Loading mesh from {input_path}")
        
        # Load the GLB file
        mesh = trimesh.load(input_path, force='mesh')
        
        # Handle scene vs single mesh
        if isinstance(mesh, trimesh.Scene):
            logger.info(f"Scene detected with {len(mesh.geometry)} geometries")
            # Combine all geometries
            meshes = list(mesh.geometry.values())
            if not meshes:
                logger.error("No geometries found in scene")
                return False
            mesh = trimesh.util.concatenate(meshes)
        
        logger.info(f"Mesh loaded: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
        
        # Normalize plane normal
        plane_normal = np.array(plane_normal, dtype=float)
        plane_normal = plane_normal / np.linalg.norm(plane_normal)
        plane_origin = np.array(plane_origin, dtype=float)
        
        logger.info(f"Slicing with plane: origin={plane_origin}, normal={plane_normal}, keep={keep_side}")
        
        # Use trimesh's built-in slice_plane method
        # If keep_side is 'negative', flip the normal to keep the other side
        if keep_side == 'negative':
            plane_normal = -plane_normal
            logger.info(f"Flipped normal for negative side: {plane_normal}")
        
        # Slice the mesh
        try:
            sliced_mesh = mesh.slice_plane(
                plane_origin=plane_origin,
                plane_normal=plane_normal,
                cap=True  # Cap the slice with a face
            )
        except Exception as slice_error:
            logger.error(f"slice_plane failed: {slice_error}")
            # Fallback to manual slicing
            logger.info("Attempting manual slicing fallback...")
            
            # Calculate signed distances from vertices to plane
            vertices = mesh.vertices
            distances = np.dot(vertices - plane_origin, plane_normal)
            
            # Determine which vertices to keep
            keep_mask = distances >= -1e-6  # Small epsilon for numerical stability
            
            # Filter faces: keep faces where all vertices are on the keep side
            face_mask = np.all(keep_mask[mesh.faces], axis=1)
            
            if not np.any(face_mask):
                logger.error("Slicing would result in empty mesh (no faces kept)")
                return False
            
            # Create new mesh with filtered faces
            new_faces = mesh.faces[face_mask]
            
            # Get unique vertices used by kept faces
            used_vertices = np.unique(new_faces.flatten())
            
            # Create vertex mapping (old index -> new index)
            vertex_map = np.full(len(vertices), -1, dtype=int)
            vertex_map[used_vertices] = np.arange(len(used_vertices))
            
            # Remap faces to new vertex indices
            remapped_faces = vertex_map[new_faces]
            
            # Create sliced mesh
            sliced_mesh = trimesh.Trimesh(
                vertices=vertices[used_vertices],
                faces=remapped_faces,
                process=False
            )
        
        if sliced_mesh is None or len(sliced_mesh.vertices) == 0:
            logger.error("Slicing resulted in empty mesh")
            return False
        
        logger.info(f"Sliced mesh: {len(sliced_mesh.vertices)} vertices, {len(sliced_mesh.faces)} faces")
        
        # Export as GLB
        sliced_mesh.export(output_path, file_type='glb')
        
        if os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            logger.info(f"✅ Sliced mesh exported successfully: {file_size} bytes")
            return True
        else:
            logger.error("Output file was not created")
            return False
            
    except Exception as e:
        logger.error(f"Error slicing mesh: {e}", exc_info=True)
        return False


def get_mesh_bounds(glb_path):
    """
    Get the bounding box of a mesh
    
    Args:
        glb_path: Path to GLB file
    
    Returns:
        dict: {'min': [x, y, z], 'max': [x, y, z], 'center': [x, y, z]}
    """
    try:
        mesh = trimesh.load(glb_path, force='mesh')
        
        if isinstance(mesh, trimesh.Scene):
            meshes = list(mesh.geometry.values())
            if not meshes:
                return None
            mesh = trimesh.util.concatenate(meshes)
        
        bounds = mesh.bounds
        center = mesh.centroid
        
        return {
            'min': bounds[0].tolist(),
            'max': bounds[1].tolist(),
            'center': center.tolist()
        }
    except Exception as e:
        logger.error(f"Error getting mesh bounds: {e}")
        return None
