"""
FBX format to GLB format conversion operations using FBX2glTF.
"""

import os
import subprocess
import logging
import contextlib
import trimesh
import tempfile
import numpy as np
import platform
from pathlib import Path
from .base_converter import (
    BaseConverter,
    hex_to_linear_rgb,
    safe_texture_ext,
    safe_join_within,
)
from pygltflib import GLTF2, Image, Texture, TextureInfo, PbrMetallicRoughness


@contextlib.contextmanager
def _pyassimp_scene(pyassimp, path, processing=None):
    """Load an assimp scene and guarantee release().

    pyassimp builds disagree on whether load() supports the context-manager
    protocol — several versions (incl. the 4.1.x pinned here) return a plain
    Scene, so `with pyassimp.load(...) as scene` raises
    'Scene object does not support the context manager protocol' and the
    whole FBX dimension/texture/rescue path silently dies. Load explicitly,
    yield, then always release the native scene so peak memory stays low on
    large FBX files (which matters: this used to OOM-kill the worker).
    """
    scene = (pyassimp.load(path, processing=processing)
             if processing is not None else pyassimp.load(path))
    try:
        yield scene
    finally:
        try:
            pyassimp.release(scene)
        except Exception:
            pass



# Inline utility functions (replacing deleted utils/)
def ensure_directory(path):
    """Ensure directory exists, create if needed."""
    import os

    os.makedirs(path, exist_ok=True)


def safe_delete_file(path):
    """Safely delete a file if it exists."""
    import os

    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


def is_valid_extension(filename, extensions):
    """Check if filename has valid extension."""
    return any(filename.lower().endswith(ext) for ext in extensions)


logger = logging.getLogger(__name__)


def _ensure_assimp_library_path():
    """Make libassimp discoverable before pyassimp is imported.

    pyassimp resolves the shared library via LD_LIBRARY_PATH; on nix-based
    deploys (Railway/nixpacks) libassimp lives under /nix/store or the nix
    profile, which is not on the default search path.
    """
    import sys
    import glob

    if "pyassimp" in sys.modules:
        return
    candidates = []
    for pattern in (
        "/root/.nix-profile/lib/libassimp.so*",
        "/nix/var/nix/profiles/default/lib/libassimp.so*",
        "/nix/store/*/lib/libassimp.so*",
    ):
        candidates = glob.glob(pattern)
        if candidates:
            break
    if not candidates:
        return
    lib_dir = os.path.dirname(candidates[0])
    current = os.environ.get("LD_LIBRARY_PATH", "")
    if lib_dir not in current.split(":"):
        os.environ["LD_LIBRARY_PATH"] = f"{current}:{lib_dir}" if current else lib_dir
        logger.info(f"Added assimp library directory to LD_LIBRARY_PATH: {lib_dir}")


def _gltf_image_bytes(gltf, image_index):
    """Return the raw bytes of a glTF image (data URI or buffer view), or None."""
    import base64

    if image_index is None or not gltf.images or image_index >= len(gltf.images):
        return None
    img = gltf.images[image_index]
    if img.uri and img.uri.startswith("data:"):
        try:
            return base64.b64decode(img.uri.split(",", 1)[1])
        except Exception:
            return None
    if img.bufferView is not None:
        blob = gltf.binary_blob()
        if not blob:
            return None
        bv = gltf.bufferViews[img.bufferView]
        offset = bv.byteOffset if bv.byteOffset else 0
        return blob[offset : offset + bv.byteLength]
    return None


def _analyze_alpha_channel(image_bytes):
    """Inspect an encoded image's alpha channel.

    Returns (has_transparency, mostly_binary):
    - has_transparency: any meaningfully transparent pixel exists
    - mostly_binary: alpha is essentially on/off (foliage cutout) rather than
      gradual (glass/fades), so MASK renders it better than BLEND
    """
    from PIL import Image as PILImage
    import io

    pil = PILImage.open(io.BytesIO(image_bytes))
    if pil.mode not in ("RGBA", "LA", "PA") and "transparency" not in pil.info:
        return False, False
    alpha = pil.convert("RGBA").getchannel("A")
    lo, _ = alpha.getextrema()
    if lo >= 250:
        return False, False
    hist = alpha.histogram()
    total = sum(hist) or 1
    partial = sum(hist[16:240])  # neither fully transparent nor fully opaque
    # Foliage cutouts are dominated by fully-transparent/fully-opaque texels;
    # partial alpha appears only on antialiased edges (typically 5-15%). Truly
    # gradual textures (glass, fades) have large smooth partial regions. MASK
    # must win for cutouts: BLEND disables depth sorting, so dense foliage
    # blends against the background instead of the leaves behind it and the
    # whole canopy washes out.
    return True, (partial / total) < 0.25


def fix_material_transparency(gltf, log=None):
    """Alpha-correctness pass for FBX-derived materials.

    FBX exporters and FBX2glTF disagree about opacity semantics, which shows up
    in two broken ways:
    1. Cutout textures (foliage) arrive with alphaMode=OPAQUE, so the texture's
       alpha channel is ignored and leaves render as solid quads.
    2. A bogus FBX TransparencyFactor arrives as baseColorFactor alpha < 1
       (often 0). Harmless while OPAQUE (spec says alpha is ignored), but fatal
       if anything later switches the material to BLEND — the mesh disappears.

    The fix is driven by what the base-color texture actually contains, not by
    material names. Returns True if any material was modified.

    Also normalizes metallic/roughness on textured materials: glTF defaults
    metallicFactor to 1.0 when omitted, so an FBX2glTF material that leaves it
    unset renders fully metallic — the texture is replaced by grey environment
    reflection and the model washes out. Traditional FBX (lambert/phong)
    materials have no metalness concept, so when there is no
    metallicRoughnessTexture the factor is dialect noise, not artist intent.
    """
    log = log or (lambda msg, level="INFO": None)
    changed = False
    for mat in gltf.materials or []:
        pbr = mat.pbrMetallicRoughness
        if pbr is None:
            continue

        if pbr.baseColorTexture is not None and pbr.metallicRoughnessTexture is None:
            metallic = pbr.metallicFactor if pbr.metallicFactor is not None else 1.0
            roughness = pbr.roughnessFactor if pbr.roughnessFactor is not None else 1.0
            if metallic > 0.2 or roughness < 0.5:
                pbr.metallicFactor = 0.0 if metallic > 0.2 else metallic
                pbr.roughnessFactor = 0.9 if roughness < 0.5 else roughness
                changed = True
                log(
                    f"Normalized PBR factors on textured material '{mat.name}': "
                    f"metallic {metallic:.2f} → {pbr.metallicFactor:.2f}, "
                    f"roughness {roughness:.2f} → {pbr.roughnessFactor:.2f}"
                )
        factor = pbr.baseColorFactor
        factor_alpha = factor[3] if factor and len(factor) == 4 else 1.0

        has_alpha = mostly_binary = False
        if pbr.baseColorTexture is not None and gltf.textures:
            tex_idx = pbr.baseColorTexture.index
            if tex_idx is not None and tex_idx < len(gltf.textures):
                data = _gltf_image_bytes(gltf, gltf.textures[tex_idx].source)
                if data:
                    try:
                        has_alpha, mostly_binary = _analyze_alpha_channel(data)
                    except Exception as exc:
                        log(f"Alpha analysis failed for material '{mat.name}': {exc}", "WARNING")

        if has_alpha:
            # Binary cutouts (foliage) must use MASK even when FBX2glTF already
            # marked them BLEND: BLEND disables depth sorting, so dense leaves
            # blend against the background and the canopy washes out.
            target = "MASK" if mostly_binary else "BLEND"
            if mat.alphaMode != target and mat.alphaMode != "MASK":
                mat.alphaMode = target
                if target == "MASK":
                    mat.alphaCutoff = 0.5
                changed = True
            if mat.doubleSided is not True:
                mat.doubleSided = True
                changed = True
            if factor_alpha < 1.0:
                # Let the texture drive transparency; a stray <1 factor alpha
                # would dim the whole surface.
                pbr.baseColorFactor = [factor[0], factor[1], factor[2], 1.0]
                changed = True
            log(
                f"Transparency fix → material '{mat.name}': "
                f"alphaMode={mat.alphaMode}, doubleSided=True"
            )
        elif factor_alpha < 1.0:
            mode = mat.alphaMode or "OPAQUE"
            if mode == "OPAQUE" or (mode == "BLEND" and factor_alpha < 0.05):
                # FBX opacity import bug: clamp instead of going translucent.
                pbr.baseColorFactor = [factor[0], factor[1], factor[2], 1.0]
                if mode == "BLEND":
                    mat.alphaMode = "OPAQUE"
                changed = True
                log(
                    f"Clamped bogus baseColorFactor alpha {factor_alpha:.3f} → 1.0 "
                    f"on material '{mat.name}' (no texture alpha)"
                )
    return changed


class FBXConverter(BaseConverter):
    """Converter for FBX files to GLB format using FBX2glTF."""

    def __init__(self):
        super().__init__()
        self.supported_extensions = {".fbx"}

        # Platform-aware FBX2glTF path
        tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools")
        if platform.system() == "Windows":
            self.fbx2gltf_path = os.path.join(tools_dir, "FBX2glTF.exe")
        else:
            self.fbx2gltf_path = os.path.join(tools_dir, "FBX2glTF")

        self.remove_textures = False  # Option to remove existing textures
        self._fbx_material_textures = {}  # Store material -> texture mapping from pyassimp

    def validate(self, file_path: str) -> bool:
        """Validate if the file exists and has .fbx extension."""
        if not super().validate(file_path):
            return False

        if not os.path.exists(file_path):
            self.handle_error(f"File does not exist: {file_path}")
            return False

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.supported_extensions:
            self.handle_error(f"Unsupported file format: {file_ext}")
            return False

        if not os.path.exists(self.fbx2gltf_path):
            self.handle_error(f"FBX2glTF not found at path: {self.fbx2gltf_path}")
            self.log_operation("Please ensure FBX2glTF.exe is in the tools directory")
            return False

        return True

    def calculate_scale_factor(self, mesh) -> float:
        """Calculate scale factor to fit model within maximum dimensions."""
        try:
            # Get the current dimensions
            extents = mesh.extents
            max_dimension = max(extents)

            # Calculate scale factor if needed
            if max_dimension > self.max_dimension:
                return self.max_dimension / max_dimension

            return 1.0

        except Exception as e:
            self.handle_error(f"Error calculating scale factor: {str(e)}")
            return 1.0

    def apply_color(self, mesh, color_str: str) -> trimesh.Trimesh:
        """Apply color to the mesh."""
        try:
            if not color_str:
                return mesh

            # sRGB picker value → linear (glTF baseColorFactor/COLOR_0 are linear)
            lr, lg, lb = hex_to_linear_rgb(color_str)
            r = int(round(lr * 255))
            g = int(round(lg * 255))
            b = int(round(lb * 255))

            self.log_operation(f"Applying color linear RGB({r}, {g}, {b}) to mesh")

            # Remove existing textures if requested
            if self.remove_textures:
                self.log_operation(
                    "Removing existing textures and applying solid color"
                )
                mesh.visual = None

            # Create PBR material with the specified color
            material = trimesh.visual.material.PBRMaterial(
                baseColorFactor=[lr, lg, lb, 1.0],
                metallicFactor=0.1,
                roughnessFactor=0.9,
            )

            # Apply both material and vertex colors for maximum compatibility
            mesh.visual = trimesh.visual.TextureVisuals(material=material)
            vertex_colors = np.tile([r, g, b, 255], (len(mesh.vertices), 1))
            mesh.visual.vertex_colors = vertex_colors.astype(np.uint8)

            self.log_operation(f"Solid color applied successfully: RGB({r}, {g}, {b})")
            return mesh

        except Exception as e:
            self.handle_error(f"Error applying color: {str(e)}")
            import traceback

            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return mesh

    def convert(self, input_path: str, output_path: str, color: str = None) -> bool:
        """Convert FBX to GLB format."""
        try:
            self.update_status("CONVERTING")
            self.log_operation("Starting FBX conversion")

            # FIRST: Read original FBX dimensions before conversion using pyassimp
            original_dimensions = None
            try:
                # Attempt to load pyassimp and the underlying library
                _ensure_assimp_library_path()
                import pyassimp
                from pyassimp import postprocess

                # pyassimp.load() returns a Scene directly in this version —
                # manage its lifecycle via our shim (load + guaranteed release).
                with _pyassimp_scene(
                    pyassimp, input_path,
                    processing=postprocess.aiProcess_Triangulate,
                ) as scene:
                    self.log_operation(
                        f"Scene type: {type(scene)}, has mMeshes: {hasattr(scene, 'mMeshes')}"
                    )
                    if hasattr(scene, "mNumMeshes"):
                        self.log_operation(f"Number of meshes: {scene.mNumMeshes}")

                    # DETECT FBX UNIT SCALE FACTOR
                    # FBX files can use different units (mm, cm, m)
                    # UnitScaleFactor tells us how to convert to cm, then we convert to meters
                    self._fbx_unit_scale = 1.0  # Default: assume meters
                    try:
                        if hasattr(scene, 'metadata') and scene.metadata:
                            for key in scene.metadata:
                                if isinstance(key, bytes):
                                    key_str = key.decode('utf-8', errors='ignore')
                                else:
                                    key_str = str(key)
                                if key_str.lower() in ('unitscalefactor', 'unit_scale_factor'):
                                    val = scene.metadata[key]
                                    if hasattr(val, 'data'):
                                        val = val.data
                                    unit_scale = float(val)
                                    # UnitScaleFactor is typically: 1.0=cm, 100.0=m, 0.1=mm
                                    # Convert to meters: value_in_meters = value_in_fbx_units * (unit_scale / 100.0)
                                    self._fbx_unit_scale = unit_scale / 100.0
                                    self.log_operation(
                                        f"FBX UnitScaleFactor: {unit_scale} -> scale to meters: {self._fbx_unit_scale}"
                                    )
                                    break
                        if self._fbx_unit_scale == 1.0:
                            self.log_operation(
                                "No UnitScaleFactor found in FBX metadata, assuming cm (default FBX unit)"
                            )
                            self._fbx_unit_scale = 0.01  # Default FBX unit is cm
                    except Exception as unit_err:
                        self.log_operation(f"Warning: Could not read FBX unit scale: {unit_err}", "WARNING")
                        self._fbx_unit_scale = 0.01  # Fallback: assume cm

                    # EXTRACT EMBEDDED TEXTURES
                    self._fbx_material_textures = {}
                    extracted_texture_paths = {}  # index -> path

                    if hasattr(scene, "textures") and scene.textures:
                        self.log_operation(
                            f"Found {len(scene.textures)} embedded textures"
                        )
                        texture_dir = os.path.dirname(input_path)

                        for idx, texture in enumerate(scene.textures):
                            try:
                                # Get texture data. The format hint is attacker
                                # -controlled (it comes from the uploaded FBX),
                                # so sanitize it to a known image extension
                                # rather than building a filename from it.
                                if hasattr(texture, "achFormatHint"):
                                    format_hint = (
                                        texture.achFormatHint.decode("utf-8", "ignore")
                                        if isinstance(texture.achFormatHint, bytes)
                                        else texture.achFormatHint
                                    )
                                    ext = safe_texture_ext(format_hint)
                                else:
                                    ext = ".png"

                                # Save texture to file. The index is ours (not
                                # from the file), so this name is fully trusted.
                                texture_filename = f"texture_{idx}{ext}"
                                texture_path = os.path.join(
                                    texture_dir, texture_filename
                                )

                                if hasattr(texture, "pcData") and texture.pcData:
                                    with open(texture_path, "wb") as f:
                                        f.write(texture.pcData)
                                    self.log_operation(
                                        f"Extracted texture: {texture_filename}"
                                    )
                                    extracted_texture_paths[idx] = texture_path
                            except Exception as tex_error:
                                self.log_operation(
                                    f"Warning: Could not extract texture {idx}: {tex_error}",
                                    "WARNING",
                                )

                    all_vertices = []
                    all_faces = []
                    all_uvs = []  # Store UV coordinates
                    all_materials = []  # Store material info

                    # EXTRACT MATERIAL TEXTURE MAPPINGS
                    if hasattr(scene, "materials"):
                        for mat_idx, material in enumerate(scene.materials):
                            mat_name = material.properties.get(
                                "?mat.name", f"Material_{mat_idx}"
                            )
                            # Try multiple possible texture property names in pyassimp
                            tex_file = material.properties.get("$tex.file")
                            if not tex_file:
                                # Try common keys for different slots
                                for key in material.properties.keys():
                                    if "$tex.file" in key:
                                        tex_file = material.properties[key]
                                        break

                            if tex_file:
                                self._fbx_material_textures[mat_name] = tex_file
                                self.log_operation(
                                    f"Material '{mat_name}' Texture: {tex_file}"
                                )
                            elif len(extracted_texture_paths) == 1 and len(scene.materials) == 1:
                                # Single material + single embedded texture but no
                                # property linking them: the pairing is unambiguous.
                                self._fbx_material_textures[mat_name] = list(
                                    extracted_texture_paths.values()
                                )[0]
                                self.log_operation(
                                    f"Assigned sole extracted texture to material '{mat_name}'"
                                )

                    # Try different pyassimp API approaches
                    # Approach 1: Direct meshes attribute (newer pyassimp)
                    if hasattr(scene, "meshes") and scene.meshes:
                        self.log_operation(
                            f"Using scene.meshes (found {len(scene.meshes)} meshes)"
                        )
                        for mesh_idx, mesh in enumerate(scene.meshes):
                            if hasattr(mesh, "vertices") and len(mesh.vertices) > 0:
                                all_vertices.append(np.array(mesh.vertices))
                                self.log_operation(
                                    f"Added {len(mesh.vertices)} vertices from mesh {mesh_idx}"
                                )

                                # Collect UV coordinates (texture coordinates)
                                if (
                                    hasattr(mesh, "texturecoords")
                                    and mesh.texturecoords is not None
                                ):
                                    # texturecoords[0] is the first UV channel
                                    if (
                                        len(mesh.texturecoords) > 0
                                        and mesh.texturecoords[0] is not None
                                    ):
                                        uvs = np.array(mesh.texturecoords[0])[
                                            :, :2
                                        ]  # Take only U,V (ignore W)
                                        all_uvs.append(uvs)
                                        self.log_operation(
                                            f"Added {len(uvs)} UV coordinates from mesh {mesh_idx}"
                                        )
                                    else:
                                        all_uvs.append(None)
                                else:
                                    all_uvs.append(None)

                                # Collect material index
                                if hasattr(mesh, "materialindex"):
                                    all_materials.append(mesh.materialindex)
                                    self.log_operation(
                                        f"Mesh {mesh_idx} uses material index: {mesh.materialindex}"
                                    )
                                else:
                                    all_materials.append(None)

                                # Also collect faces (triangles)
                                if hasattr(mesh, "faces") and len(mesh.faces) > 0:
                                    # Faces are stored as arrays of vertex indices
                                    mesh_faces = []
                                    for face in mesh.faces:
                                        if len(face) >= 3:  # Triangle or polygon
                                            # Convert to triangle indices
                                            mesh_faces.append(
                                                [face[0], face[1], face[2]]
                                            )
                                    if mesh_faces:
                                        all_faces.append(np.array(mesh_faces))
                                        self.log_operation(
                                            f"Added {len(mesh_faces)} faces from mesh {mesh_idx}"
                                        )
                    # Approach 2: mMeshes ctypes array (older pyassimp)
                    elif hasattr(scene, "mMeshes") and scene.mMeshes:
                        self.log_operation(
                            f"Using scene.mMeshes (found {scene.mNumMeshes} meshes)"
                        )
                        for i in range(scene.mNumMeshes):
                            mesh = scene.mMeshes[i].contents
                            if hasattr(mesh, "mVertices") and mesh.mNumVertices > 0:
                                vertices = np.array(
                                    [
                                        [
                                            mesh.mVertices[j].x,
                                            mesh.mVertices[j].y,
                                            mesh.mVertices[j].z,
                                        ]
                                        for j in range(mesh.mNumVertices)
                                    ]
                                )
                                all_vertices.append(vertices)
                                self.log_operation(
                                    f"Added {mesh.mNumVertices} vertices from mesh {i}"
                                )

                    if all_vertices:
                        combined_vertices = np.vstack(all_vertices)
                        min_bounds = combined_vertices.min(axis=0)
                        max_bounds = combined_vertices.max(axis=0)
                        extents = max_bounds - min_bounds

                        # Store original vertices for later use (in case GLB has zero vertices)
                        # Note: FBX units vary (mm, cm, m) - we keep raw values and let FBX2glTF handle conversion
                        # FBX2glTF outputs in meters, so we trust its output for final dimensions
                        self._fbx_vertices = combined_vertices  # Keep raw units, will be scaled if needed
                        self._fbx_raw_extents = extents  # Store raw extents for logging
                        self.log_operation(
                            f"Stored {len(combined_vertices)} original FBX vertices (raw units)"
                        )

                        # Store UV coordinates
                        if all_uvs and any(uv is not None for uv in all_uvs):
                            combined_uvs = []
                            for idx, uv in enumerate(all_uvs):
                                if uv is not None:
                                    combined_uvs.append(uv)
                                else:
                                    # If a mesh has no UVs, create dummy UVs
                                    combined_uvs.append(
                                        np.zeros((len(all_vertices[idx]), 2))
                                    )

                            self._fbx_uvs = np.vstack(combined_uvs)
                            self.log_operation(
                                f"Stored {len(self._fbx_uvs)} UV coordinates"
                            )
                        else:
                            self._fbx_uvs = None
                            self.log_operation("No UV coordinates found in FBX")

                        # Store original faces if available
                        if all_faces:
                            # Combine all faces, adjusting indices for combined vertex array
                            combined_faces = []
                            vertex_offset = 0
                            for i, faces in enumerate(all_faces):
                                # Adjust face indices by vertex offset
                                adjusted_faces = faces + vertex_offset
                                combined_faces.append(adjusted_faces)
                                vertex_offset += len(all_vertices[i])

                            self._fbx_faces = np.vstack(combined_faces)
                            self.log_operation(
                                f"Stored {len(self._fbx_faces)} original FBX faces for mesh creation"
                            )
                        else:
                            self._fbx_faces = None
                            self.log_operation(
                                "No faces found in FBX, will use vertices only"
                            )

                        if max(extents) > 0.001:
                            # Apply detected FBX unit scale to convert to meters
                            unit_scale = getattr(self, '_fbx_unit_scale', 0.01)
                            extents_m = extents * unit_scale
                            self.log_operation(
                                f"Original FBX dimensions (raw units): {extents}"
                            )
                            self.log_operation(
                                f"FBX unit scale: {unit_scale}, dimensions in meters: {extents_m}"
                            )
                            # Store original dimensions in meters for reference
                            # FBX2glTF output is authoritative, but this helps validate
                            original_dimensions = {
                                "x": float(extents_m[0]),
                                "y": float(extents_m[1]),
                                "z": float(extents_m[2]),
                                "max": float(max(extents_m)),
                                "unit_scale": unit_scale,
                            }
                        else:
                            self.log_operation(
                                f"Warning: Original FBX has zero dimensions: {extents}"
                            )
                    else:
                        self.log_operation("Warning: No vertices found in FBX file")
                        self._fbx_vertices = None
            except (Exception, BaseException) as e:
                import traceback

                self.log_operation(
                    f"Warning: pyassimp initialization failed: {str(e)}. "
                    "FBX dimension reading and texture extraction will be skipped. "
                    "Conversion will still proceed using FBX2glTF.",
                    "WARNING",
                )
                self.log_operation(f"Traceback: {traceback.format_exc()}")

            # Store dimensions for later use
            self.original_dimensions = original_dimensions

            # Create output directory
            ensure_directory(os.path.dirname(output_path))

            # Create a temporary directory for intermediate files
            with tempfile.TemporaryDirectory() as temp_dir:
                try:
                    # First convert FBX to GLB using FBX2glTF
                    # Use -i and -o parameters (based on working project)
                    # NOTE: Draco compression disabled - it corrupts textures and geometry
                    # Ensure FBX2glTF has execute permissions. Only chmod when
                    # it's actually missing the bit — doing it on every request
                    # is wasteful and normalizes flipping a binary executable at
                    # request time.
                    try:
                        if not os.access(self.fbx2gltf_path, os.X_OK):
                            os.chmod(self.fbx2gltf_path, 0o755)
                            self.log_operation(
                                f"Set execute permissions for {self.fbx2gltf_path}"
                            )
                    except Exception as pe:
                        self.log_operation(
                            f"Warning: Could not set execute permissions: {pe}",
                            "WARNING",
                        )

                    # --pbr-metallic-roughness forces FBX2glTF to emit core glTF
                    # metallic-roughness materials (with baseColorTexture) instead
                    # of the default KHR_materials_pbrSpecularGlossiness extension.
                    # Modern model-viewer / three.js dropped spec-gloss support, so
                    # without this flag FBX textures are written into an extension
                    # the viewer ignores and the model renders untextured.
                    cmd = [
                        str(self.fbx2gltf_path),
                        "-i",
                        str(input_path),
                        "-o",
                        str(output_path),
                        "--binary",
                        "--pbr-metallic-roughness",
                    ]

                    self.log_operation(f"Running command: {' '.join(cmd)}")
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                        stdin=subprocess.DEVNULL,  # Don't wait for input
                        cwd=os.path.dirname(input_path) or None,
                        timeout=300,
                    )  # 5 minute timeout

                    # FBX2glTF sometimes writes the GLB under a variant of the
                    # requested name (e.g. appending the input stem or "_out").
                    # Adopt the first matching candidate before declaring failure.
                    if not os.path.exists(output_path):
                        out_dir = Path(os.path.dirname(output_path))
                        out_stem = Path(output_path).stem
                        in_stem = Path(input_path).stem
                        candidates = [
                            p
                            for p in sorted(out_dir.glob("*.glb"))
                            if p.stem.startswith(out_stem) or p.stem.startswith(in_stem)
                        ]
                        if candidates:
                            import shutil

                            shutil.move(str(candidates[0]), output_path)
                            self.log_operation(
                                f"Adopted FBX2glTF output {candidates[0].name} as model.glb"
                            )

                    # Check conversion result
                    if result.returncode != 0 or not os.path.exists(output_path):
                        error_msg = f"FBX2glTF conversion failed (exit code {result.returncode})\n"
                        error_msg += f"STDERR: {result.stderr}\n"
                        error_msg += f"STDOUT: {result.stdout}"
                        self.handle_error(error_msg)
                        return False

                    self.log_operation(f"FBX2glTF output: {result.stdout}")

                    # Rescue: FBX2glTF occasionally emits a GLB with degenerate
                    # (zero-extent) geometry. Rebuild from the original FBX data
                    # read via pyassimp instead of publishing an empty model.
                    if self._rescue_zero_geometry(output_path, color, original_dimensions):
                        self.update_status("COMPLETED")
                        return True

                    # If neither FBX2glTF nor the pyassimp rescue produced real
                    # geometry, fail loudly instead of publishing an empty model
                    # that later 500s the viewer/dimension endpoints.
                    if not self._glb_has_geometry(output_path):
                        self.handle_error(
                            "Conversion produced an empty model — this FBX has no "
                            "extractable mesh geometry (it may contain only NURBS/"
                            "curves, cameras, lights, or animation data)."
                        )
                        return False

                    # Post-processing: Only if color or scaling needed
                    # IMPORTANT: Use pygltflib for post-processing to preserve animations
                    self.log_operation(
                        f"Post-processing - color: {color}, max_dimension: {self.max_dimension}"
                    )

                    # Check if GLB has animations - if so, use pygltflib to preserve them
                    has_animations = False
                    try:
                        from pygltflib import GLTF2

                        gltf_check = GLTF2().load(output_path)
                        if gltf_check.animations and len(gltf_check.animations) > 0:
                            has_animations = True
                            self.log_operation(
                                f"✅ GLB has {len(gltf_check.animations)} animations - will use pygltflib to preserve them"
                            )
                        if gltf_check.skins and len(gltf_check.skins) > 0:
                            self.log_operation(
                                f"✅ GLB has {len(gltf_check.skins)} skins"
                            )
                    except Exception as e:
                        self.log_operation(
                            f"Warning: Could not check for animations: {e}", "WARNING"
                        )

                    # Check if we need post-processing
                    needs_processing = False
                    needs_scaling = False
                    scale_factor = 1.0

                    # Check if color application needed
                    if color:
                        needs_processing = True
                        self.log_operation("Post-processing needed: color application")

                    # Check if scaling needed - get dimensions from GLB output (more accurate)
                    if self.max_dimension > 0 and os.path.exists(output_path):
                        try:
                            temp_mesh = trimesh.load(output_path)
                            if isinstance(temp_mesh, trimesh.Scene):
                                bounds = temp_mesh.bounds
                                extents = (
                                    bounds[1] - bounds[0]
                                    if bounds is not None
                                    else np.array([0, 0, 0])
                                )
                            else:
                                extents = temp_mesh.extents

                            max_dim_m = float(max(extents))
                            if max_dim_m > 0:
                                scale_factor = self.max_dimension / max_dim_m
                                if (
                                    abs(scale_factor - 1.0) > 0.001
                                ):  # Only scale if significant difference
                                    needs_scaling = True
                                    needs_processing = True
                                    self.log_operation(
                                        f"Post-processing needed: scaling (factor: {scale_factor:.4f})"
                                    )
                                    self.log_operation(
                                        f"Current max: {max_dim_m:.4f}m, Target: {self.max_dimension:.4f}m"
                                    )
                            del temp_mesh
                        except Exception as e:
                            self.log_operation(
                                f"Warning: Could not check dimensions: {e}", "WARNING"
                            )

                    # If no post-processing needed, just embed external textures
                    if not needs_processing:
                        self.log_operation(
                            "No post-processing needed - embedding external textures into GLB"
                        )
                        try:
                            self._embed_external_textures(output_path, input_path)
                        except Exception as tex_error:
                            self.log_operation(
                                f"Warning: Could not embed textures: {tex_error}",
                                "WARNING",
                            )
                        self.update_status("COMPLETED")
                        return True

                    # Use pygltflib for post-processing to preserve animations
                    # IMPORTANT: If model has animations, ALWAYS use pygltflib (never trimesh)
                    if has_animations or needs_scaling or color:
                        self.log_operation(
                            "Using pygltflib for post-processing to preserve animations"
                        )
                        try:
                            from pygltflib import GLTF2
                            import sys

                            sys.path.insert(
                                0, os.path.dirname(os.path.dirname(__file__))
                            )
                            from glb_modifier import (
                                apply_material_modifications,
                                apply_transform_modifications,
                            )

                            gltf = GLTF2().load(output_path)

                            # Apply scaling using glb_modifier (preserves animations)
                            if needs_scaling:
                                transform_mods = {
                                    "scale": scale_factor,
                                    "rotation": {"x": 0, "y": 0, "z": 0},
                                }
                                gltf = apply_transform_modifications(
                                    gltf, transform_mods
                                )
                                self.log_operation(
                                    f"Applied scale {scale_factor:.4f}x using pygltflib"
                                )

                            # Apply color using glb_modifier (preserves animations).
                            # Skip when the GLB carries baseColorTextures: the
                            # factor multiplies the texture, so a solid color
                            # would tint/darken the original artwork.
                            has_textures = any(
                                mat.pbrMetallicRoughness
                                and mat.pbrMetallicRoughness.baseColorTexture is not None
                                for mat in (gltf.materials or [])
                            )
                            if color and has_textures:
                                self.log_operation(
                                    f"Skipping color {color}: GLB already has baseColorTextures"
                                )
                            elif color:
                                material_mods = {
                                    "color": color,
                                    "metalness": 0.1,
                                    "roughness": 0.9,
                                    "opacity": 1.0,
                                }
                                gltf = apply_material_modifications(gltf, material_mods)
                                self.log_operation(
                                    f"Applied color {color} using pygltflib"
                                )

                            # Embed textures
                            try:
                                self._embed_external_textures_gltf(gltf, input_path)
                            except Exception as tex_error:
                                self.log_operation(
                                    f"Warning: Could not embed textures: {tex_error}",
                                    "WARNING",
                                )

                            # Save modified GLB
                            gltf.save(output_path)

                            # Verify animations preserved
                            gltf_verify = GLTF2().load(output_path)
                            if gltf_verify.animations:
                                self.log_operation(
                                    f"✅ Animations preserved: {len(gltf_verify.animations)} animations"
                                )

                            self.update_status("COMPLETED")
                            return True

                        except Exception as e:
                            self.log_operation(
                                f"Warning: pygltflib post-processing failed: {e}",
                                "WARNING",
                            )
                            import traceback

                            self.log_operation(f"Traceback: {traceback.format_exc()}")
                            # Keep the raw FBX2glTF output: a correctly textured
                            # model at the wrong scale beats the old trimesh
                            # concatenate fallback, which destroyed per-material
                            # textures (and animations).
                            self.log_operation(
                                "Keeping unmodified FBX2glTF GLB to preserve textures/animations"
                            )
                            try:
                                self._embed_external_textures(output_path, input_path)
                            except Exception as tex_error:
                                self.log_operation(
                                    f"Warning: Could not embed textures: {tex_error}",
                                    "WARNING",
                                )
                            self.update_status("COMPLETED")
                            return True

                    # Verify output file exists
                    if not os.path.exists(output_path):
                        self.handle_error("GLB file was not created")
                        return False

                    file_size = os.path.getsize(output_path)
                    self.log_operation(
                        f"Conversion completed successfully. Output size: {file_size} bytes"
                    )
                    return True

                except subprocess.TimeoutExpired:
                    self.handle_error("FBX conversion timed out after 5 minutes")
                    return False
                except Exception as e:
                    self.handle_error(f"Error during conversion: {str(e)}")
                    import traceback

                    self.log_operation(f"Traceback: {traceback.format_exc()}")
                    return False

        except Exception as e:
            self.handle_error(f"Conversion failed: {str(e)}")
            import traceback

            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return False

    def _glb_has_geometry(self, glb_path: str) -> bool:
        """True if the GLB has at least one mesh with non-zero extents."""
        try:
            obj = trimesh.load(glb_path)
            bounds = getattr(obj, "bounds", None)
            if bounds is None:
                return False
            extents = bounds[1] - bounds[0]
            return bool(np.any(extents > 1e-9))
        except Exception as e:
            self.log_operation(f"Warning: geometry check failed: {e}", "WARNING")
            # Be permissive on checker errors — don't fail a possibly-valid model.
            return True

    def _rescue_zero_geometry(self, output_path: str, color, original_dimensions) -> bool:
        """Rebuild the GLB from pyassimp-read FBX data when FBX2glTF emitted
        degenerate (zero-extent) geometry. Returns True if a rescue happened.
        """
        try:
            scene_or_mesh = trimesh.load(output_path)
            if isinstance(scene_or_mesh, trimesh.Scene):
                bounds = scene_or_mesh.bounds
            else:
                bounds = scene_or_mesh.bounds
            if bounds is not None:
                extents = bounds[1] - bounds[0]
                if np.any(extents > 1e-9):
                    return False  # geometry is fine
            del scene_or_mesh
        except Exception as e:
            self.log_operation(f"Warning: zero-geometry check failed: {e}", "WARNING")
            return False

        if getattr(self, "_fbx_vertices", None) is None or getattr(self, "_fbx_faces", None) is None:
            self.log_operation(
                "WARNING: FBX2glTF GLB has zero geometry and no pyassimp data to rescue from",
                "WARNING",
            )
            return False

        self.log_operation(
            "WARNING: FBX2glTF GLB has zero geometry - rebuilding from original FBX data"
        )
        mesh = trimesh.Trimesh(vertices=self._fbx_vertices, faces=self._fbx_faces)
        if original_dimensions and self.max_dimension > 0 and original_dimensions["max"] > 0:
            scale_factor = self.max_dimension / original_dimensions["max"]
            mesh.apply_scale(scale_factor)
            self.log_operation(f"Applied scale factor {scale_factor:.4f} to rescued mesh")
        if color:
            self.apply_color(mesh, color)
        if os.path.exists(output_path):
            os.remove(output_path)
        mesh.export(output_path, file_type="glb")
        self.log_operation(
            f"Rescued mesh exported: {len(mesh.vertices)} vertices, "
            f"{os.path.getsize(output_path)} bytes"
        )
        return True

    def _embed_external_textures_gltf(self, gltf, fbx_path: str) -> None:
        """Embed external texture files into an already-loaded GLTF object.
        This version works with a gltf object that's already in memory.
        """
        try:
            import base64

            fbx_dir = os.path.dirname(fbx_path)

            # --- AGGRESSIVE TEXTURE RECOVERY ---
            # If pyassimp found textures that aren't in the GLB, add them now
            if (
                hasattr(self, "_fbx_material_textures")
                and self._fbx_material_textures
                and gltf.materials
            ):
                self.log_operation(
                    f"Attempting aggressive texture recovery for {len(gltf.materials)} materials"
                )
                for mat in gltf.materials:
                    mat_name = mat.name
                    if mat_name in self._fbx_material_textures:
                        # Found a mapping from pyassimp
                        tex_source = self._fbx_material_textures[mat_name]

                        # If baseColorTexture is missing or points to a non-existent image
                        has_texture = False
                        if (
                            mat.pbrMetallicRoughness
                            and mat.pbrMetallicRoughness.baseColorTexture
                        ):
                            has_texture = True

                        if not has_texture:
                            # Find the texture file. tex_source comes from the
                            # uploaded FBX's material data and may be absolute or
                            # contain '..'; constrain every candidate to stay
                            # within the upload dirs (no arbitrary file read).
                            texture_file = None
                            search_paths = [
                                safe_join_within(fbx_dir, tex_source),
                                safe_join_within(
                                    os.path.join(fbx_dir, "textures"), tex_source
                                ),
                                safe_join_within(os.path.dirname(fbx_path), tex_source),
                            ]

                            for path in search_paths:
                                if path and os.path.exists(path):
                                    texture_file = path
                                    break

                            if texture_file:
                                # Add new image, embedded immediately as a data
                                # URI — a bare filename URI would leave the GLB
                                # with a dangling external reference.
                                with open(texture_file, "rb") as tf:
                                    tex_bytes = tf.read()
                                ext = os.path.splitext(texture_file)[1].lower()
                                mime = {
                                    ".png": "image/png",
                                    ".jpg": "image/jpeg",
                                    ".jpeg": "image/jpeg",
                                    ".webp": "image/webp",
                                }.get(ext, "image/png")
                                img_idx = len(gltf.images) if gltf.images else 0
                                new_img = Image(
                                    uri=f"data:{mime};base64,{base64.b64encode(tex_bytes).decode('utf-8')}"
                                )
                                if gltf.images is None:
                                    gltf.images = []
                                gltf.images.append(new_img)

                                # Add new texture
                                tex_idx = len(gltf.textures) if gltf.textures else 0
                                new_tex = Texture(source=img_idx)
                                if gltf.textures is None:
                                    gltf.textures = []
                                gltf.textures.append(new_tex)

                                # Assign to material
                                if mat.pbrMetallicRoughness is None:
                                    mat.pbrMetallicRoughness = PbrMetallicRoughness()
                                mat.pbrMetallicRoughness.baseColorTexture = TextureInfo(
                                    index=tex_idx
                                )
                                self.log_operation(
                                    f"  ✅ Recovered texture for material '{mat_name}': {os.path.basename(texture_file)}"
                                )

            if gltf.images:
                # Convert buffer-embedded images to data URIs
                binary_blob = gltf.binary_blob()
                for i, img in enumerate(gltf.images):
                    if binary_blob and img.bufferView is not None:
                        try:
                            buffer_view = gltf.bufferViews[img.bufferView]
                            offset = buffer_view.byteOffset if buffer_view.byteOffset else 0
                            length = buffer_view.byteLength

                            image_data = binary_blob[offset : offset + length]

                            # Determine MIME type
                            mime_type = "image/png"
                            if image_data[:4] == b"\x89PNG":
                                mime_type = "image/png"
                            elif image_data[:2] == b"\xff\xd8":
                                mime_type = "image/jpeg"

                            # Convert to data URI
                            data_uri = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"
                            img.uri = data_uri
                            img.bufferView = None
                            self.log_operation(f"Converted image {i} to data URI")
                        except Exception as e:
                            self.log_operation(
                                f"Warning: Could not convert image {i}: {e}", "WARNING"
                            )
            else:
                self.log_operation("No images found in GLB to embed")

            # Alpha-correctness pass (cutout → MASK, bogus factor alpha → clamp).
            # Runs after image conversion so the texture bytes are inspectable.
            fix_material_transparency(gltf, self.log_operation)

        except Exception as e:
            self.log_operation(f"Warning: Could not embed textures: {e}", "WARNING")

    def _embed_external_textures(self, glb_path: str, fbx_path: str) -> None:
        """Embed external texture files into GLB."""
        try:
            from pygltflib import GLTF2
            import base64

            # LOG: FBX directory contents (textures that came with FBX)
            fbx_dir = os.path.dirname(fbx_path)
            self.log_operation(f"📁 FBX Directory: {fbx_dir}")
            self.log_operation(f"📁 Scanning for texture files in FBX directory...")

            texture_extensions = {
                ".png",
                ".jpg",
                ".jpeg",
                ".tga",
                ".bmp",
                ".tif",
                ".tiff",
                ".webp",
            }
            found_textures = []

            try:
                for file in os.listdir(fbx_dir):
                    file_path = os.path.join(fbx_dir, file)
                    if os.path.isfile(file_path):
                        ext = os.path.splitext(file)[1].lower()
                        if ext in texture_extensions:
                            size = os.path.getsize(file_path)
                            found_textures.append((file, size, ext))
                            self.log_operation(
                                f"  🖼️  Found: {file} ({size} bytes, {ext})"
                            )

                if not found_textures:
                    self.log_operation(f"  ⚠️  No texture files found in FBX directory")
                else:
                    self.log_operation(
                        f"  ✅ Total textures found: {len(found_textures)}"
                    )
            except Exception as e:
                self.log_operation(f"  ⚠️  Error scanning FBX directory: {e}")

            self.log_operation(f"Loading GLB to embed textures: {glb_path}")
            gltf = GLTF2().load(glb_path)

            if not gltf.images:
                self.log_operation(
                    "No images found in GLB - FBX2glTF may have discarded textures"
                )
                # Still clamp bogus FBX factor alphas so the model can't go
                # invisible if anything later switches it to BLEND.
                if fix_material_transparency(gltf, self.log_operation):
                    gltf.save(glb_path)
                return

            self.log_operation(
                f"📦 GLB Analysis: Found {len(gltf.images)} images in GLB"
            )
            self.log_operation(f"📦 Image Details:")

            has_buffer_images = False
            for i, img in enumerate(gltf.images):
                if img.uri:
                    if img.uri.startswith("data:"):
                        uri_preview = (
                            img.uri[:50] + "..." if len(img.uri) > 50 else img.uri
                        )
                        self.log_operation(
                            f"  🖼️  Image {i}: Data URI (embedded, {len(img.uri)} chars)"
                        )
                        self.log_operation(f"       Preview: {uri_preview}")
                    else:
                        self.log_operation(f"  🖼️  Image {i}: External file - {img.uri}")
                        # Check if external file exists
                        external_path = os.path.join(fbx_dir, img.uri)
                        if os.path.exists(external_path):
                            size = os.path.getsize(external_path)
                            self.log_operation(f"       ✅ File exists: {size} bytes")
                        else:
                            self.log_operation(
                                f"       ❌ File NOT found at: {external_path}"
                            )
                elif img.bufferView is not None:
                    # Get buffer size
                    buffer_view = gltf.bufferViews[img.bufferView]
                    buffer_size = buffer_view.byteLength
                    self.log_operation(
                        f"  🖼️  Image {i}: Buffer-embedded (bufferView: {img.bufferView}, {buffer_size} bytes)"
                    )
                    has_buffer_images = True
                else:
                    self.log_operation(
                        f"  ⚠️  Image {i}: Unknown format (no URI, no bufferView)"
                    )

            # If images are embedded in buffer, convert to data URIs for model-viewer compatibility
            if has_buffer_images:
                self.log_operation(
                    "🔄 Converting buffer-embedded textures to data URIs for model-viewer"
                )
                try:
                    # Get binary blob
                    binary_blob = gltf.binary_blob()
                    if not binary_blob:
                        self.log_operation(
                            "⚠️  Warning: No binary blob found", "WARNING"
                        )
                        return

                    self.log_operation(f"📦 Binary blob size: {len(binary_blob)} bytes")

                    # Convert each buffer-embedded image to data URI
                    conversion_summary = []
                    for i, img in enumerate(gltf.images):
                        if img.bufferView is not None:
                            try:
                                # Get buffer view
                                buffer_view = gltf.bufferViews[img.bufferView]
                                offset = (
                                    buffer_view.byteOffset
                                    if buffer_view.byteOffset
                                    else 0
                                )
                                length = buffer_view.byteLength

                                self.log_operation(f"  🔄 Converting Image {i}:")
                                self.log_operation(
                                    f"     Buffer offset: {offset}, length: {length}"
                                )

                                # Extract image data from binary blob
                                image_data = binary_blob[offset : offset + length]

                                # Determine MIME type from image data
                                mime_type = "image/png"  # Default
                                if image_data[:4] == b"\x89PNG":
                                    mime_type = "image/png"
                                elif image_data[:2] == b"\xff\xd8":
                                    mime_type = "image/jpeg"
                                elif (
                                    image_data[:4] == b"RIFF"
                                    and image_data[8:12] == b"WEBP"
                                ):
                                    mime_type = "image/webp"

                                self.log_operation(f"     Detected format: {mime_type}")

                                # Convert to data URI
                                data_uri = f"data:{mime_type};base64,{base64.b64encode(image_data).decode('utf-8')}"

                                # Replace bufferView with data URI
                                img.uri = data_uri
                                img.bufferView = None

                                conversion_summary.append(
                                    {
                                        "index": i,
                                        "size": len(image_data),
                                        "mime": mime_type,
                                        "data_uri_size": len(data_uri),
                                    }
                                )

                                self.log_operation(
                                    f"     ✅ Converted to data URI: {len(image_data)} bytes → {len(data_uri)} chars"
                                )
                            except Exception as img_error:
                                self.log_operation(
                                    f"     ❌ Failed to convert image {i}: {img_error}",
                                    "WARNING",
                                )
                                conversion_summary.append(
                                    {"index": i, "error": str(img_error)}
                                )

                    # Summary
                    successful = len(
                        [c for c in conversion_summary if "error" not in c]
                    )
                    failed = len([c for c in conversion_summary if "error" in c])
                    self.log_operation(
                        f"🔄 Conversion Summary: {successful} successful, {failed} failed"
                    )

                    # Ensure all images have corresponding textures
                    from pygltflib import Texture, Sampler

                    if not gltf.textures:
                        gltf.textures = []
                    if not gltf.samplers:
                        gltf.samplers = []

                    # Create a default sampler if none exists
                    if len(gltf.samplers) == 0:
                        sampler = Sampler()
                        sampler.magFilter = 9729  # LINEAR
                        sampler.minFilter = 9987  # LINEAR_MIPMAP_LINEAR
                        sampler.wrapS = 10497  # REPEAT
                        sampler.wrapT = 10497  # REPEAT
                        gltf.samplers.append(sampler)

                    # Map images to textures
                    image_to_texture = {}
                    for tex_idx, tex in enumerate(gltf.textures):
                        if tex.source is not None:
                            image_to_texture[tex.source] = tex_idx

                    # Create missing textures for images without them
                    for img_idx in range(len(gltf.images)):
                        if img_idx not in image_to_texture:
                            self.log_operation(
                                f"Creating missing texture for image {img_idx}"
                            )
                            texture = Texture()
                            texture.source = img_idx
                            texture.sampler = 0  # Use first sampler
                            tex_idx = len(gltf.textures)
                            gltf.textures.append(texture)
                            image_to_texture[img_idx] = tex_idx
                            self.log_operation(
                                f"  Created Texture {tex_idx} → Image {img_idx}"
                            )

                    # Alpha-correctness pass (cutout → MASK, semi-transparent →
                    # BLEND, bogus factor alpha → clamp to opaque).
                    fix_material_transparency(gltf, self.log_operation)

                    # Log mesh-material assignments
                    if gltf.meshes:
                        self.log_operation(
                            f"Mesh-Material assignments ({len(gltf.meshes)} meshes):"
                        )
                        for mesh_idx, mesh in enumerate(gltf.meshes):
                            mesh_name = mesh.name if mesh.name else f"Mesh_{mesh_idx}"
                            for prim_idx, prim in enumerate(mesh.primitives):
                                mat_idx = (
                                    prim.material
                                    if prim.material is not None
                                    else "None"
                                )
                                mat_name = (
                                    gltf.materials[prim.material].name
                                    if prim.material is not None
                                    and prim.material < len(gltf.materials)
                                    else "Unknown"
                                )
                                self.log_operation(
                                    f"  {mesh_name}[{prim_idx}] → Material {mat_idx} ({mat_name})"
                                )

                    # Log material-texture assignments for debugging
                    if gltf.materials:
                        self.log_operation(
                            f"Material-Texture assignments ({len(gltf.materials)} materials):"
                        )
                        for i, mat in enumerate(gltf.materials):
                            mat_name = mat.name if mat.name else f"Material_{i}"
                            if (
                                mat.pbrMetallicRoughness
                                and mat.pbrMetallicRoughness.baseColorTexture
                            ):
                                tex_idx = (
                                    mat.pbrMetallicRoughness.baseColorTexture.index
                                )
                                img_idx = (
                                    gltf.textures[tex_idx].source
                                    if tex_idx < len(gltf.textures)
                                    else "?"
                                )
                                self.log_operation(
                                    f"  Material {i} ({mat_name}): Texture {tex_idx} → Image {img_idx}"
                                )
                            else:
                                self.log_operation(
                                    f"  Material {i} ({mat_name}): No baseColorTexture ❌"
                                )

                    # Log all textures
                    if gltf.textures:
                        self.log_operation(
                            f"All Textures ({len(gltf.textures)} total):"
                        )
                        for tex_idx, tex in enumerate(gltf.textures):
                            img_idx = tex.source if tex.source is not None else "None"
                            self.log_operation(f"  Texture {tex_idx} → Image {img_idx}")

                    # FINAL SUMMARY
                    self.log_operation("=" * 60)
                    self.log_operation("📊 TEXTURE EMBEDDING SUMMARY")
                    self.log_operation("=" * 60)
                    self.log_operation(
                        f"📁 Textures in FBX directory: {len(found_textures)}"
                    )
                    self.log_operation(
                        f"📦 Images in GLB (from FBX2glTF): {len(gltf.images)}"
                    )
                    self.log_operation(f"🔄 Images converted to Data URI: {successful}")
                    self.log_operation(
                        f"🎨 Textures in GLB: {len(gltf.textures) if gltf.textures else 0}"
                    )
                    self.log_operation(
                        f"🎭 Materials in GLB: {len(gltf.materials) if gltf.materials else 0}"
                    )

                    # Check which textures are actually used
                    used_textures = set()
                    if gltf.materials:
                        for mat in gltf.materials:
                            if (
                                mat.pbrMetallicRoughness
                                and mat.pbrMetallicRoughness.baseColorTexture
                            ):
                                used_textures.add(
                                    mat.pbrMetallicRoughness.baseColorTexture.index
                                )

                    unused_count = (
                        len(gltf.textures) - len(used_textures) if gltf.textures else 0
                    )
                    self.log_operation(
                        f"✅ Textures assigned to materials: {len(used_textures)}"
                    )
                    self.log_operation(f"⚠️  Unused textures: {unused_count}")
                    self.log_operation("=" * 60)

                    # Save with data URIs
                    temp_path = glb_path.replace(".glb", "_temp.glb")
                    gltf.save(temp_path)

                    if os.path.exists(temp_path):
                        temp_size = os.path.getsize(temp_path)
                        self.log_operation(f"Temp GLB created: {temp_size} bytes")

                        import shutil

                        shutil.move(temp_path, glb_path)

                        final_size = os.path.getsize(glb_path)
                        self.log_operation(
                            f"✅ GLB re-exported with data URI textures: {final_size} bytes"
                        )
                        return
                    else:
                        self.log_operation(
                            "Warning: Temp file was not created", "WARNING"
                        )
                except Exception as e:
                    self.log_operation(
                        f"Warning: Could not convert textures: {e}", "WARNING"
                    )
                    import traceback

                    self.log_operation(
                        f"Traceback: {traceback.format_exc()}", "WARNING"
                    )

            fbx_dir = os.path.dirname(fbx_path)
            glb_dir = os.path.dirname(glb_path)
            modified = False

            for i, image in enumerate(gltf.images):
                # Check if image has external URI (not embedded)
                if image.uri and not image.uri.startswith("data:"):
                    self.log_operation(f"Found external texture: {image.uri}")

                    # Try multiple locations for texture file
                    texture_path = None
                    search_paths = [
                        os.path.join(glb_dir, image.uri),  # Same dir as GLB
                        os.path.join(fbx_dir, image.uri),  # Same dir as FBX
                        os.path.join(
                            glb_dir, os.path.basename(image.uri)
                        ),  # GLB dir, filename only
                        os.path.join(
                            fbx_dir, os.path.basename(image.uri)
                        ),  # FBX dir, filename only
                    ]

                    for path in search_paths:
                        if os.path.exists(path):
                            texture_path = path
                            break

                    if not texture_path:
                        self.log_operation(
                            f"Warning: Texture file not found in any location: {image.uri}",
                            "WARNING",
                        )
                        self.log_operation(f"Searched: {search_paths}", "WARNING")
                        continue

                    self.log_operation(f"Embedding texture: {texture_path}")

                    # Read texture file
                    with open(texture_path, "rb") as f:
                        texture_data = f.read()

                    # Determine MIME type
                    ext = os.path.splitext(texture_path)[1].lower()
                    mime_type = {
                        ".png": "image/png",
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".webp": "image/webp",
                    }.get(ext, "image/png")

                    # Convert to data URI
                    data_uri = f"data:{mime_type};base64,{base64.b64encode(texture_data).decode('utf-8')}"
                    image.uri = data_uri
                    modified = True
                    self.log_operation(
                        f"Embedded texture {i}: {len(texture_data)} bytes"
                    )

            # Alpha-correctness pass for the no-buffer-images path (the buffer
            # path above runs it before saving and returns early).
            if fix_material_transparency(gltf, self.log_operation):
                modified = True

            if modified:
                self.log_operation("Saving GLB with embedded textures")
                gltf.save(glb_path)
                self.log_operation("✅ Textures embedded successfully")
            else:
                self.log_operation("No external textures to embed")

        except Exception as e:
            self.log_operation(f"Error embedding textures: {e}", "ERROR")
            import traceback

            self.log_operation(f"Traceback: {traceback.format_exc()}")
            raise

    def handle_error(self, error_message: str) -> None:
        """Handle and log error messages."""
        self.update_status("ERROR")
        logger.error(error_message)
        self.log_operation(f"Error: {error_message}")
