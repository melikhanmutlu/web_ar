"""
Mesh Slicer Module
Handles 3D mesh slicing operations using trimesh.

Scene-aware: each geometry in the scene is sliced separately (never
concatenated), so multi-material models keep their per-primitive
materials. Meshes that carry UVs or vertex/face colors are sliced with
an attribute-preserving face mask (trimesh's plane cut cannot
interpolate UVs — it would orphan every texture). Plain meshes get the
clean geometric plane cut.

A pygltflib material re-injection pass runs ONLY when the exported GLB
ends up with no materials at all (e.g. vertex-color-only uploads).
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

    Only called when the export produced NO materials — injecting over
    a multi-material export would clobber per-primitive assignments.
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


def _exported_material_count(glb_path):
    """How many materials did the exported GLB end up with?"""
    try:
        gltf = GLTF2().load(glb_path)
        return len(gltf.materials or [])
    except Exception:
        return 0


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


def _mesh_needs_attribute_preserve(mesh):
    """
    True when the mesh carries per-vertex data that a geometric plane
    cut would destroy: UV coordinates (textures) or vertex/face colors.
    """
    vis = getattr(mesh, 'visual', None)
    if isinstance(vis, trimesh.visual.TextureVisuals):
        uv = getattr(vis, 'uv', None)
        if uv is not None and len(uv) == len(mesh.vertices):
            return True
    if isinstance(vis, trimesh.visual.ColorVisuals) and getattr(vis, 'kind', None) in ('vertex', 'face'):
        return True
    return False


def _facemask_slice(mesh, plane_origin, plane_normal):
    """
    Keep only faces whose vertices all lie on the kept side. No new
    vertices are created, so UVs, vertex colors, and material refs are
    carried over EXACTLY. The cut edge follows triangle boundaries
    (slightly stepped on low-poly meshes) — the price of keeping
    textures intact.
    """
    vertices = mesh.vertices
    distances = np.dot(vertices - plane_origin, plane_normal)
    # Scale the boundary epsilon to the model size. A fixed 1e-6 is meaningless
    # for models in millimetres (extents in the thousands) and far too coarse
    # for tiny models — both cause wrong keep/drop decisions at the cut plane.
    extent = float(np.linalg.norm(mesh.extents)) if mesh.extents is not None else 1.0
    eps = 1e-6 * max(extent, 1.0)
    keep_mask = distances >= -eps

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

    vis = getattr(mesh, 'visual', None)
    try:
        if isinstance(vis, trimesh.visual.TextureVisuals):
            uv = getattr(vis, 'uv', None)
            uv_subset = uv[used_idx] if (uv is not None and len(uv) == len(vertices)) else None
            result.visual = trimesh.visual.TextureVisuals(
                uv=uv_subset,
                material=getattr(vis, 'material', None),
            )
        elif isinstance(vis, trimesh.visual.ColorVisuals):
            if vis.kind == 'vertex':
                result.visual = trimesh.visual.ColorVisuals(
                    result, vertex_colors=vis.vertex_colors[used_idx]
                )
            elif vis.kind == 'face':
                result.visual = trimesh.visual.ColorVisuals(
                    result, face_colors=vis.face_colors[face_mask]
                )
    except Exception as ve:
        logger.warning(f"Could not copy visual attributes: {ve}")

    return result


def _slice_single_mesh(mesh, plane_origin, plane_normal):
    """
    Slice a single Trimesh object.

    Textured / colored meshes use the attribute-preserving face mask
    (trimesh's plane cut creates new vertices with no UV/color, which
    is what used to wreck materials after Apply). Plain meshes get the
    clean capped plane cut.
    Returns sliced mesh or None if result is empty.
    """
    vis = getattr(mesh, 'visual', None)

    if _mesh_needs_attribute_preserve(mesh):
        try:
            sliced = _facemask_slice(mesh, plane_origin, plane_normal)
            if sliced is not None and len(sliced.vertices) > 0:
                return sliced
        except Exception as e:
            logger.warning(f"Attribute-preserving slice failed ({e}); trying plane cut")

    # --- Clean geometric cut, capped (needs shapely for cap triangulation) ---
    try:
        sliced = mesh.slice_plane(
            plane_origin=plane_origin,
            plane_normal=plane_normal,
            cap=True,
        )
        if sliced is not None and len(getattr(sliced, 'vertices', [])) > 0:
            _reattach_material(sliced, vis)
            return sliced
    except Exception as e:
        logger.warning(f"slice_plane(cap=True) failed ({e}), trying cap=False")

    # --- Same cut without a cap (open cross-section) ---
    try:
        sliced = mesh.slice_plane(
            plane_origin=plane_origin,
            plane_normal=plane_normal,
            cap=False,
        )
        if sliced is not None and len(getattr(sliced, 'vertices', [])) > 0:
            _reattach_material(sliced, vis)
            return sliced
    except Exception as e:
        logger.warning(f"slice_plane(cap=False) failed ({e}), using face-mask fallback")

    # --- Last resort for plain meshes too ---
    try:
        return _facemask_slice(mesh, plane_origin, plane_normal)
    except Exception as e:
        logger.error(f"Fallback slicing failed: {e}")
        return None


def _reattach_material(sliced, vis):
    """slice_plane drops the visual; put the material reference back."""
    try:
        if isinstance(vis, trimesh.visual.TextureVisuals) and getattr(vis, 'material', None) is not None:
            sliced.visual = trimesh.visual.TextureVisuals(material=vis.material)
    except Exception as e:
        logger.warning(f"Could not reattach material: {e}")


def _iter_world_meshes(loaded):
    """
    Yield (name, mesh) pairs with node transforms baked in, WITHOUT
    concatenating the scene — concatenation collapses every geometry
    into one primitive and loses per-geometry materials.
    """
    if isinstance(loaded, trimesh.Trimesh):
        yield 'mesh_0', loaded.copy()
        return

    seen = set()
    for node_name in loaded.graph.nodes_geometry:
        transform, geom_name = loaded.graph[node_name]
        geom = loaded.geometry.get(geom_name)
        if not isinstance(geom, trimesh.Trimesh):
            continue
        m = geom.copy()
        if transform is not None:
            m.apply_transform(transform)
        # Unique node name per instance
        name = node_name if node_name not in seen else f"{node_name}_{len(seen)}"
        seen.add(name)
        yield name, m


def _slice_core(input_path, output_path, planes):
    """
    Shared pipeline for single- and multi-plane slicing.

    1. pygltflib  → snapshot PBR materials (used only if export loses them)
    2. trimesh    → slice each scene geometry separately, preserving visuals
    3. pygltflib  → re-inject materials ONLY if the export has none

    Returns: {'success': bool, 'degenerate': bool, 'extents': list|None}
    """
    mat_data = _extract_material_data(input_path)

    loaded = trimesh.load(input_path, force=None)
    if not isinstance(loaded, (trimesh.Scene, trimesh.Trimesh)):
        logger.error(f"Unexpected type from trimesh.load: {type(loaded)}")
        return {"success": False, "degenerate": False, "extents": None}

    normalized = [
        _normalize_plane(
            p.get("plane_origin"), p.get("plane_normal"), p.get("keep_side", "positive")
        )
        for p in planes
    ]

    out_scene = trimesh.Scene()
    total_in, total_kept = 0, 0
    for name, mesh in _iter_world_meshes(loaded):
        total_in += 1
        current = mesh
        for origin, normal in normalized:
            current = _slice_single_mesh(current, origin, normal)
            if current is None or len(current.vertices) == 0:
                current = None
                break
        if current is not None and len(current.faces) > 0:
            out_scene.add_geometry(current, node_name=name)
            total_kept += 1

    if total_kept == 0:
        logger.error("Slicing removed every geometry — empty result")
        return {"success": False, "degenerate": False, "extents": None}

    bounds = out_scene.bounds
    extents = (bounds[1] - bounds[0]) if bounds is not None else None
    degenerate = bool(extents is not None and np.any(extents < 1e-4))
    logger.info(
        f"Sliced {total_kept}/{total_in} geometries, "
        f"extents={extents.tolist() if extents is not None else None}, degenerate={degenerate}"
    )

    out_scene.export(output_path, file_type='glb')

    if not (os.path.exists(output_path) and os.path.getsize(output_path) > 0):
        logger.error("Output file missing or empty after export")
        return {"success": False, "degenerate": False, "extents": None}

    # Re-inject ONLY when the trimesh export carries no materials at all;
    # otherwise we would overwrite correct per-primitive assignments.
    if mat_data and _exported_material_count(output_path) == 0:
        logger.info("Export has no materials — re-injecting originals")
        _inject_materials(output_path, mat_data)

    logger.info(f"Exported sliced model: {os.path.getsize(output_path)} bytes")
    return {
        "success": True,
        "degenerate": degenerate,
        "extents": [float(e) for e in extents] if extents is not None else None,
    }


# ================================================================== #
#  Public API
# ================================================================== #

def slice_mesh(input_path, output_path, plane_origin, plane_normal, keep_side='positive'):
    """
    Slice a GLB mesh with a plane and keep one side.
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
        result = _slice_core(input_path, output_path, [{
            "plane_origin": plane_origin,
            "plane_normal": plane_normal,
            "keep_side": keep_side,
        }])
        return result["success"]
    except Exception as e:
        logger.error(f"slice_mesh error: {e}", exc_info=True)
        return False


def slice_mesh_multi(input_path, output_path, planes):
    """
    Slice a GLB mesh with several planes in ONE pass (atomic multi-axis slice).

    Args:
        input_path:  Path to input GLB
        output_path: Path to output GLB
        planes:      list of dicts, each: {plane_origin:[x,y,z],
                     plane_normal:[x,y,z], keep_side:'positive'|'negative'}

    Returns:
        dict: {'success': bool, 'degenerate': bool, 'extents': [x,y,z] | None}
    """
    try:
        if not planes:
            return {"success": False, "degenerate": False, "extents": None}
        return _slice_core(input_path, output_path, planes)
    except Exception as e:
        logger.error(f"slice_mesh_multi error: {e}", exc_info=True)
        return {"success": False, "degenerate": False, "extents": None}


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
        # Geometric bounding-box center (NOT centroid/center-of-mass) so the slicer
        # slider starts at the visual middle of each axis for asymmetric meshes.
        center = (bounds[0] + bounds[1]) / 2.0

        return {
            'min':    {'x': float(bounds[0][0]), 'y': float(bounds[0][1]), 'z': float(bounds[0][2])},
            'max':    {'x': float(bounds[1][0]), 'y': float(bounds[1][1]), 'z': float(bounds[1][2])},
            'center': {'x': float(center[0]),    'y': float(center[1]),    'z': float(center[2])},
        }
    except Exception as e:
        logger.error(f"get_mesh_bounds error: {e}")
        return None
