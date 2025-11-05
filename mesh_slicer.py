import trimesh
import os
import logging
from werkzeug.utils import secure_filename

# Configure logging
logger = logging.getLogger(__name__)

def slice_model_with_plane(model_path, plane_origin, plane_normal, keep_side='positive'):
    """
    Slices a 3D model using a defined plane and keeps one side.

    Args:
        model_path (str): The absolute path to the GLB model file.
        plane_origin (list): A list of 3 floats representing the plane's origin point [x, y, z].
        plane_normal (list): A list of 3 floats representing the plane's normal vector [x, y, z].
        keep_side (str): Which side of the sliced mesh to keep. 'positive' or 'negative'.

    Returns:
        trimesh.Trimesh or None: The sliced mesh object, or None if slicing fails.
    """
    try:
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found at: {model_path}")

        # Load the mesh from the file
        mesh = trimesh.load(model_path, force='mesh')

        # Perform the slice operation
        # The slice_mesh_plane function returns the part of the mesh on the positive side of the normal
        sliced_mesh = trimesh.intersections.slice_mesh_plane(
            mesh=mesh,
            plane_normal=plane_normal,
            plane_origin=plane_origin
        )

        # If the user wants to keep the negative side, we need to flip the normal and slice again
        if keep_side == 'negative':
            flipped_normal = [-n for n in plane_normal]
            sliced_mesh = trimesh.intersections.slice_mesh_plane(
                mesh=mesh,
                plane_normal=flipped_normal,
                plane_origin=plane_origin
            )

        if not sliced_mesh or sliced_mesh.is_empty:
            logger.warning("Slicing resulted in an empty mesh.")
            return None
            
        # The result might be a Scene object if the original had multiple meshes.
        # We need to ensure we return a single Trimesh object.
        if isinstance(sliced_mesh, trimesh.Scene):
            # Combine all geometries in the scene into a single mesh
            consolidated_mesh = trimesh.util.concatenate(sliced_mesh.geometry.values())
            return consolidated_mesh
        elif isinstance(sliced_mesh, trimesh.Trimesh):
            return sliced_mesh
        else:
            return None

    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        return None
    except Exception as e:
        logger.exception(f"An unexpected error occurred during slicing: {e}")
        return None

def get_mesh_bounds(model_path):
    """
    Calculates the bounding box of a 3D model.

    Args:
        model_path (str): The absolute path to the model file.

    Returns:
        dict or None: A dictionary with 'min', 'max', and 'center' bounds, or None on failure.
    """
    try:
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model file not found at: {model_path}")

        # Load the mesh as a scene to correctly handle transforms
        scene = trimesh.load(model_path, force='scene')
        
        # Use scene.bounds to get the overall axis-aligned bounding box
        min_bound, max_bound = scene.bounds
        center_bound = scene.centroid.tolist()

        return {
            'min': min_bound.tolist(),
            'max': max_bound.tolist(),
            'center': center_bound
        }
    except Exception as e:
        logger.exception(f"An unexpected error occurred while getting mesh bounds: {e}")
        return None

def save_sliced_model(mesh, original_path):
    """
    Saves the sliced Trimesh object back to the original file path.

    Args:
        mesh (trimesh.Trimesh): The mesh object to save.
        original_path (str): The file path to save the new GLB to.

    Returns:
        bool: True if saving was successful, False otherwise.
    """
    try:
        # Export the sliced mesh back to a GLB file in-memory
        export_data = mesh.export(file_type='glb')

        # Write the in-memory data to the original file path, overwriting it
        with open(original_path, 'wb') as f:
            f.write(export_data)

        logger.info(f"Successfully saved sliced model to {original_path}")
        return True
    except Exception as e:
        logger.exception(f"An error occurred while saving the sliced model: {e}")
        return False
