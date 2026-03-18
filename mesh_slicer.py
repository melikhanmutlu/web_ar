"""
Mesh Slicer Module
Handles 3D mesh slicing operations using trimesh.
Scene-aware: preserves materials, textures, and node hierarchy.
Supports repeated slicing without coordinate drift.
"""
import os
import logging
import trimesh
import numpy as np

logger = logging.getLogger(__name__)


def _normalize_plane(plane_origin, plane_normal, keep_side):
    """Normalize inputs and flip normal for negative side."""
    plane_normal = np.array(plane_normal, dtype=float)
    length = np.linalg.norm(plane_normal)
    if length < 1e-10:
        raise ValueError("plane_normal cannot be a zero vector")
    plane_normal = plane_normal / length
    plane_origin = np.array(plane_origin, dtype=float)
    if keep_side == 'negative':
        plane_normal = -plane_normal
    return plane_origin, plane_normal


def _slice_single_mesh(mesh, plane_origin, plane_normal):
    """
    Slice a single Trimesh object.
    Tries trimesh.slice_plane first (preserves UVs/materials in modern trimesh),
    falls back to face-mask approach which also copies visual attributes.
    Returns sliced mesh or None if result is empty.
    """
    # --- Primary: trimesh built-in (preserves UV & material in trimesh >= 3.x) ---
    try:
        sliced = mesh.slice_plane(
            plane_origin=plane_origin,
            plane_normal=plane_normal,
            cap=True
        )
        if sliced is not None and len(getattr(sliced, 'vertices', [])) > 0:
            return sliced
    except Exception as e:
        logger.warning(f"slice_plane failed ({e}), using fallback")

    # --- Fallback: manual face-mask, preserves visual attributes ---
    try:
        vertices = mesh.vertices
        distances = np.dot(vertices - plane_origin, plane_normal)
        keep_mask = distances >= -1e-6

        face_mask = np.all(keep_mask[mesh.faces], axis=1)
        if not np.any(face_mask):
            logger.warning("Fallback: no faces remain after slicing this submesh")
            return None

        new_faces = mesh.faces[face_mask]
        used_idx = np.unique(new_faces.flatten())
        vertex_map = np.full(len(vertices), -1, dtype=np.intp)
        vertex_map[used_idx] = np.arange(len(used_idx))
        remapped_faces = vertex_map[new_faces]

        result = trimesh.Trimesh(
            vertices=vertices[used_idx],
            faces=remapped_faces,
            process=False
        )

        # Copy visual (material + UV coords)
        if hasattr(mesh, 'visual') and mesh.visual is not None:
            try:
                vis = mesh.visual
                if hasattr(vis, 'uv') and vis.uv is not None and len(vis.uv) == len(vertices):
                    new_uv = vis.uv[used_idx]
                    result.visual = trimesh.visual.TextureVisuals(
                        uv=new_uv,
                        material=getattr(vis, 'material', None)
                    )
                elif hasattr(vis, 'material'):
                    result.visual = trimesh.visual.TextureVisuals(
                        material=vis.material
                    )
            except Exception as ve:
                logger.warning(f"Could not copy visual: {ve}")

        return result
    except Exception as e:
        logger.error(f"Fallback slicing failed: {e}")
        return None


def slice_mesh(input_path, output_path, plane_origin, plane_normal, keep_side='positive'):
    """
    Slice a GLB mesh with a plane and keep one side.
    Preserves materials, textures, and UV coordinates.
    Safe to call multiple times on the same model.

    Args:
        input_path:   Path to input GLB file
        output_path:  Path to output GLB file
        plane_origin: [x, y, z] – a point on the cutting plane (mesh-space coords)
        plane_normal: [x, y, z] – normal vector of the cutting plane
        keep_side:    'positive' | 'negative' – which side to keep

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        logger.info(f"Loading mesh from {input_path}")
        plane_origin, plane_normal = _normalize_plane(plane_origin, plane_normal, keep_side)
        logger.info(f"Plane origin={plane_origin}, normal={plane_normal}, keep={keep_side}")

        loaded = trimesh.load(input_path, force=None)  # keep scene structure

        # ------------------------------------------------------------------ #
        # Case 1 – Scene with multiple geometries (most GLBs)
        # ------------------------------------------------------------------ #
        if isinstance(loaded, trimesh.Scene):
            logger.info(f"Scene with {len(loaded.geometry)} geometries")

            kept = {}
            for name, geom in loaded.geometry.items():
                if not isinstance(geom, trimesh.Trimesh):
                    logger.info(f"Skipping non-Trimesh geometry: {name}")
                    kept[name] = geom
                    continue

                sliced = _slice_single_mesh(geom, plane_origin, plane_normal)
                if sliced is not None:
                    kept[name] = sliced
                    logger.info(f"  {name}: {len(sliced.vertices)} verts after slice")
                else:
                    logger.info(f"  {name}: fully removed by slice plane")

            if not any(isinstance(g, trimesh.Trimesh) for g in kept.values()):
                logger.error("All geometries were removed – nothing to export")
                return False

            # Rebuild scene: replace geometry dict in-place, keep graph/transforms
            loaded.geometry.clear()
            loaded.geometry.update(kept)

            loaded.export(output_path)

        # ------------------------------------------------------------------ #
        # Case 2 – Single Trimesh (rare for GLBs but possible)
        # ------------------------------------------------------------------ #
        elif isinstance(loaded, trimesh.Trimesh):
            logger.info(f"Single mesh: {len(loaded.vertices)} verts")
            sliced = _slice_single_mesh(loaded, plane_origin, plane_normal)
            if sliced is None or len(sliced.vertices) == 0:
                logger.error("Slicing resulted in empty mesh")
                return False
            sliced.export(output_path, file_type='glb')

        else:
            logger.error(f"Unexpected type from trimesh.load: {type(loaded)}")
            return False

        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            logger.info(f"✅ Exported sliced model: {os.path.getsize(output_path)} bytes")
            return True
        else:
            logger.error("Output file missing or empty after export")
            return False

    except Exception as e:
        logger.error(f"slice_mesh error: {e}", exc_info=True)
        return False


def get_mesh_bounds(glb_path):
    """
    Get the bounding box of a mesh in mesh-space coordinates.
    Always reads from file (no cache) so repeated calls after slicing
    return accurate bounds for the current state of the model.

    Returns:
        dict: {'min': [x,y,z], 'max': [x,y,z], 'center': [x,y,z]} or None
    """
    try:
        loaded = trimesh.load(glb_path, force=None)

        if isinstance(loaded, trimesh.Scene):
            meshes = [g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh)]
            if not meshes:
                logger.error("No Trimesh geometries found in scene")
                return None
            combined = trimesh.util.concatenate(meshes)
        elif isinstance(loaded, trimesh.Trimesh):
            combined = loaded
        else:
            logger.error(f"Unexpected type: {type(loaded)}")
            return None

        bounds = combined.bounds          # shape (2, 3): [min, max]
        center = combined.centroid        # shape (3,)

        return {
            'min':    bounds[0].tolist(),
            'max':    bounds[1].tolist(),
            'center': center.tolist()
        }
    except Exception as e:
        logger.error(f"get_mesh_bounds error: {e}")
        return None
