"""
Converter yardımcı fonksiyonları için paket.
"""

import numpy as np
import trimesh
from config import MAX_MODEL_SIZE

def scale_model(mesh):
    """
    Scale the model to fit within MAX_MODEL_SIZE while maintaining proportions.
    
    Args:
        mesh: A trimesh.Trimesh object
        
    Returns:
        scaled_mesh: A scaled trimesh.Trimesh object
    """
    # Get current dimensions
    current_dims = mesh.extents
    
    # Find the largest dimension
    max_dim = np.max(current_dims)
    
    # If max dimension is already smaller than MAX_MODEL_SIZE, no scaling needed
    if max_dim <= MAX_MODEL_SIZE:
        return mesh
    
    # Calculate scale factor
    scale_factor = MAX_MODEL_SIZE / max_dim
    
    # Create transformation matrix for scaling
    matrix = np.eye(4)
    matrix[:3, :3] *= scale_factor
    
    # Apply transformation
    scaled_mesh = mesh.copy()
    scaled_mesh.apply_transform(matrix)
    
    return scaled_mesh
