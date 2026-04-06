"""
Mesh Slicer Module
Handles 3D mesh slicing operations using trimesh.
Scene-aware: preserves materials, textures, and node hierarchy.
PBR materials are extracted before slicing and re-injected after,
so color, metallic, roughness, and textures survive every cut.
"""
import os
import struct
import logging
import trimesh
import numpy as np
from pygltflib import (
    GLTF2, BufferView, Image as GLTFImage,
    Material, PbrMetallicRoughness,
)

logger = logging.getLogger(__name__)


# ================================================================== #
#  PBR Material Preservation (pygltflib layer)
# ================================================================== #

def _sample_vertex_color(gltf):
    """
    Read the first vertex color from COLOR_0 accessor.
    Returns [r, g, b, a] in 0-1 range, or None if no vertex colors.
    Used to promote upload-time face_colors to PBR baseColorFactor.
    """
    blob = gltf.binary_blob()
    if not blob:
        return None

    for mesh in (gltf.meshes or []):
        for prim in (mesh.primitives or []):
            color_idx = getattr(prim.attributes, 'COLOR_0', None)
            if color_idx is None:
                continue

            acc = gltf.accessors[color_idx]
            if acc.bufferView is None:
                continue

            bv = gltf.bufferViews[acc.bufferView]
            offset = (bv.byteOffset or 0) + (acc.byteOffset or 0)
            n_comps = 4 if acc.type == 'VEC4' else 3

            try:
                # FLOAT
                if acc.componentType == 5126:
                    vals = struct.unpack_from(f'<{n_comps}f', blob, offset)
                    rgba = list(vals) + ([1.0] if n_comps == 3 else [])
                # UNSIGNED_BYTE (normalized)
                elif acc.componentType == 5121:
                    vals = [blob[offset + i] / 255.0 for i in range(n_comps)]
                    rgba = vals + ([1.0] if n_comps == 3 else [])
                # UNSIGNED_SHORT (normalized)
                elif acc.componentType == 5123:
                    vals = struct.unpack_from(f'<{n_comps}H', blob, offset)
                    rgba = [v / 65535.0 for v in vals] + ([1.0] if n_comps == 3 else [])
                else:
                    continue

                logger.info(f"Sampled vertex color: [{rgba[0]:.3f}, {rgba[1]:.3f}, {rgba[2]:.3f}, {rgba[3]:.3f}]")
                return [round(c, 6) for c in rgba]
            except Exception as e:
                logger.warning(f"Could not read COLOR_0: {e}")
                continue
    return None


def _extract_material_data(glb_path):
    """
    Read PBR material definitions, textures, samplers, and embedded
    image binary blobs from a GLB *before* trimesh touches it.

    If the GLB has no materials but has vertex colors (COLOR_0),
    a synthetic PBR material is created from the sampled vertex color
    so that upload-time colors survive slicing.

    Returns a dict with everything needed to restore later, or None.
    """
    try:
        gltf = GLTF2().load(glb_path)

        # ── Promote vertex colors to PBR if no materials exist ──
        if not gltf.materials:
            vertex_color = _sample_vertex_color(gltf)
            if vertex_color:
                logger.info(f"No materials found – promoting vertex color to PBR: {vertex_color}")
                gltf.materials = [Material(
                    pbrMetallicRoughness=PbrMetallicRoughness(
                        baseColorFactor=vertex_color,
                        metallicFactor=0.0,
                        roughnessFactor=1.0,
                    ),
                    doubleSided=True,
                )]
            else:
                logger.info("No materials and no vertex colors – nothing to preserve")
                return None

        blob = gltf.binary_blob() or b''

        # Pull raw bytes for every embedded image
        image_blobs = []
        for img in (gltf.images or []):
            if img.bufferView is not None and img.bufferView < len(gltf.bufferViews or []):
                bv = gltf.bufferViews[img.bufferView]
                start = bv.byteOffset or 0
                image_blobs.append(blob[start:start + bv.byteLength])
            else:
                image_blobs.append(None)      # URI-based or missing

        logger.info(
            f"Extracted {len(gltf.materials)} materials, "
            f"{len(gltf.textures or [])} textures, "
            f"{len(gltf.images or [])} images from original GLB"
        )

        return {
            'materials': gltf.materials,
            'textures':  gltf.textures or [],
            'samplers':  gltf.samplers or [],
            'images':    gltf.images or [],
            'image_blobs': image_blobs,
        }
    except Exception as e:
        logger.error(f"_extract_material_data failed: {e}", exc_info=True)
        return None


def _inject_materials(sliced_path, mat_data):
    """
    Open the trimesh-exported GLB and replace its material / texture /
    sampler / image arrays with the originals we saved earlier.
    Image binary data is appended to the GLB buffer, and new
    BufferView entries are created so image indices stay consistent.
    """
    try:
        gltf = GLTF2().load(sliced_path)
        blob = bytearray(gltf.binary_blob() or b'')

        # ---- restore definitions ----
        gltf.materials = mat_data['materials']
        gltf.textures  = mat_data['textures']
        gltf.samplers  = mat_data['samplers']

        # ---- rebuild images with correct buffer-view refs ----
        new_images = []
        for img_orig, img_blob in zip(mat_data['images'], mat_data['image_blobs']):
            if img_blob is not None:
                # pad to 4-byte alignment
                while len(blob) % 4 != 0:
                    blob.append(0)

                offset = len(blob)
                blob.extend(img_blob)

                bv_idx = len(gltf.bufferViews)
                gltf.bufferViews.append(BufferView(
                    buffer=0,
                    byteOffset=offset,
                    byteLength=len(img_blob),
                ))
                new_images.append(GLTFImage(
                    bufferView=bv_idx,
                    mimeType=img_orig.mimeType or 'image/png',
                ))
            else:
                # URI-based image – keep original reference
                new_images.append(img_orig)

        gltf.images = new_images

        # ---- update buffer size & blob ----
        if gltf.buffers:
            gltf.buffers[0].byteLength = len(blob)
        gltf.set_binary_blob(bytes(blob))

        # ---- ensure every primitive points to a valid material ----
        num_mats = len(gltf.materials)
        for mesh in (gltf.meshes or []):
            for prim in (mesh.primitives or []):
                if prim.material is None or prim.material >= num_mats:
                    prim.material = 0      # fall back to first material

        gltf.save(sliced_path)
        logger.info(
            f"Restored {num_mats} materials, "
            f"{len(new_images)} images into sliced GLB"
        )
        return True

    except Exception as e:
        logger.error(f"_inject_materials failed: {e}", exc_info=True)
        return False


# ================================================================== #
#  Geometry slicing helpers
# ================================================================== #

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
    Tries trimesh.slice_plane first, falls back to manual face-mask.
    Returns sliced mesh or None if result is empty.
    """
    # --- Primary: trimesh built-in ---
    try:
        sliced = mesh.slice_plane(
            plane_origin=plane_origin,
            plane_normal=plane_normal,
            cap=True,
        )
        if sliced is not None and len(getattr(sliced, 'vertices', [])) > 0:
            return sliced
    except Exception as e:
        logger.warning(f"slice_plane failed ({e}), using fallback")

    # --- Fallback: manual face-mask ---
    try:
        vertices = mesh.vertices
        distances = np.dot(vertices - plane_origin, plane_normal)
        keep_mask = distances >= -1e-6

        face_mask = np.all(keep_mask[mesh.faces], axis=1)
        if not np.any(face_mask):
            return None

        new_faces = mesh.faces[face_mask]
        used_idx = np.unique(new_faces.flatten())
        vertex_map = np.full(len(vertices), -1, dtype=np.intp)
        vertex_map[used_idx] = np.arange(len(used_idx))
        remapped_faces = vertex_map[new_faces]

        result = trimesh.Trimesh(
            vertices=vertices[used_idx],
            faces=remapped_faces,
            process=False,
        )

        # Carry over UV + material reference (trimesh-level)
        if hasattr(mesh, 'visual') and mesh.visual is not None:
            try:
                vis = mesh.visual
                if hasattr(vis, 'uv') and vis.uv is not None and len(vis.uv) == len(vertices):
                    result.visual = trimesh.visual.TextureVisuals(
                        uv=vis.uv[used_idx],
                        material=getattr(vis, 'material', None),
                    )
                elif hasattr(vis, 'material'):
                    result.visual = trimesh.visual.TextureVisuals(
                        material=vis.material,
                    )
            except Exception as ve:
                logger.warning(f"Could not copy visual: {ve}")

        return result
    except Exception as e:
        logger.error(f"Fallback slicing failed: {e}")
        return None


# ================================================================== #
#  Public API
# ================================================================== #

def slice_mesh(input_path, output_path, plane_origin, plane_normal, keep_side='positive'):
    """
    Slice a GLB mesh with a plane and keep one side.

    Pipeline:
      1. pygltflib  → extract PBR materials & textures from original
      2. trimesh    → slice geometry (scene-aware)
      3. pygltflib  → re-inject original materials into sliced GLB

    Safe to call multiple times on the same model.

    Args:
        input_path:   Path to input GLB file
        output_path:  Path to output GLB file
        plane_origin: [x, y, z] – point on cutting plane
        plane_normal: [x, y, z] – plane normal
        keep_side:    'positive' | 'negative'

    Returns:
        bool: True if successful
    """
    try:
        logger.info(f"Loading mesh from {input_path}")
        plane_origin, plane_normal = _normalize_plane(plane_origin, plane_normal, keep_side)
        logger.info(f"Plane origin={plane_origin}, normal={plane_normal}, keep={keep_side}")

        # ── Step 1: Save original PBR materials ──
        mat_data = _extract_material_data(input_path)

        # ── Step 2: Slice geometry with trimesh ──
        loaded = trimesh.load(input_path, force=None)

        if isinstance(loaded, (trimesh.Scene, trimesh.Trimesh)):
            # dump(concatenate=True) applies all node transforms → world-space coords
            # This fixes FBX-derived GLBs where root node has a rotation transform
            if isinstance(loaded, trimesh.Scene):
                logger.info(f"Scene with {len(loaded.geometry)} geometries — dumping to world space")
                combined = loaded.dump(concatenate=True)
            else:
                logger.info(f"Single mesh: {len(loaded.vertices)} verts")
                combined = loaded

            if combined is None or len(getattr(combined, 'vertices', [])) == 0:
                logger.error("Mesh is empty after loading")
                return False

            sliced = _slice_single_mesh(combined, plane_origin, plane_normal)
            if sliced is None or len(sliced.vertices) == 0:
                logger.error("Slicing resulted in empty mesh")
                return False

            # Guard: check for degenerate (near-flat) result
            sliced_bounds = sliced.bounds  # (2, 3) array
            sliced_extents = sliced_bounds[1] - sliced_bounds[0]
            logger.info(
                f"Sliced mesh: {len(sliced.vertices)} verts, "
                f"extents=[{sliced_extents[0]:.6f}, {sliced_extents[1]:.6f}, {sliced_extents[2]:.6f}]"
            )
            if np.any(sliced_extents < 1e-6):
                logger.warning(
                    f"Sliced mesh is near-degenerate on at least one axis "
                    f"(extents={sliced_extents.tolist()}). Result may look flat."
                )

            sliced.export(output_path, file_type='glb')

        else:
            logger.error(f"Unexpected type from trimesh.load: {type(loaded)}")
            return False

        # ── Step 3: Re-inject original PBR materials ──
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            if mat_data:
                _inject_materials(output_path, mat_data)
            logger.info(f"Exported sliced model: {os.path.getsize(output_path)} bytes")
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
    Always reads from file so repeated calls after slicing
    return accurate bounds.

    Returns:
        dict: {'min': [x,y,z], 'max': [x,y,z], 'center': [x,y,z]} or None
    """
    try:
        loaded = trimesh.load(glb_path, force=None)

        if isinstance(loaded, trimesh.Scene):
            # dump(concatenate=True) applies all node transforms → world-space coordinates
            combined = loaded.dump(concatenate=True)
            if combined is None or len(getattr(combined, 'vertices', [])) == 0:
                return None
        elif isinstance(loaded, trimesh.Trimesh):
            combined = loaded
        else:
            return None

        bounds = combined.bounds      # (2, 3)
        center = combined.centroid    # (3,)

        return {
            'min':    {'x': float(bounds[0][0]), 'y': float(bounds[0][1]), 'z': float(bounds[0][2])},
            'max':    {'x': float(bounds[1][0]), 'y': float(bounds[1][1]), 'z': float(bounds[1][2])},
            'center': {'x': float(center[0]),    'y': float(center[1]),    'z': float(center[2])},
        }
    except Exception as e:
        logger.error(f"get_mesh_bounds error: {e}")
        return None
