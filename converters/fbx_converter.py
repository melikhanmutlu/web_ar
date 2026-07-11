"""
FBX format to GLB format conversion operations using FBX2glTF.
"""

import os
import subprocess
import logging
import trimesh
import tempfile
import numpy as np
import platform
from pathlib import Path
from .base_converter import (
    BaseConverter,
    hex_to_linear_rgb,
)
from .fbx_common import ensure_directory
from .fbx_materials import fix_material_transparency
from .fbx_postprocess import FBXPostProcessMixin

logger = logging.getLogger(__name__)


class FBXConverter(BaseConverter, FBXPostProcessMixin):
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
            # FIRST: extract FBX metadata (unit scale, embedded textures,
            # vertices/faces for the zero-geometry rescue). This runs in a
            # separate, memory-capped process: pyassimp.load() can allocate
            # gigabytes on pathological FBX files and OOM-kill the whole
            # worker. The data is auxiliary, so on any probe failure we just
            # log a warning and let FBX2glTF do the conversion alone.
            original_dimensions = None
            self._fbx_unit_scale = 0.01
            self._fbx_material_textures = {}
            self._fbx_vertices = None
            self._fbx_faces = None
            try:
                from . import fbx_probe

                manifest = fbx_probe.run_isolated(input_path)
                if manifest and not manifest.get("error"):
                    self._fbx_unit_scale = manifest.get("unit_scale", 0.01)
                    self._fbx_material_textures = manifest.get("material_textures", {}) or {}
                    original_dimensions = manifest.get("original_dimensions")
                    self._fbx_vertices = manifest.get("vertices")
                    self._fbx_faces = manifest.get("faces")
                    self.log_operation(
                        f"FBX probe ok: unit_scale={self._fbx_unit_scale}, "
                        f"textures={len(self._fbx_material_textures)}, "
                        f"vertices={'yes' if self._fbx_vertices is not None else 'no'}"
                    )
                else:
                    msg = (manifest or {}).get("error", "no manifest")
                    self.log_operation(
                        f"FBX metadata probe unavailable ({msg}); "
                        "proceeding with FBX2glTF only.",
                        "WARNING",
                    )
            except Exception as probe_err:
                self.log_operation(
                    f"FBX metadata probe failed ({probe_err}); "
                    "proceeding with FBX2glTF only.",
                    "WARNING",
                )

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
                    # Only set cwd to the input's directory if it still exists —
                    # a missing dir makes subprocess.run raise FileNotFoundError
                    # (confusing) instead of letting FBX2glTF report cleanly.
                    input_dir = os.path.dirname(input_path)
                    run_cwd = input_dir if input_dir and os.path.isdir(input_dir) else None
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        check=False,
                        stdin=subprocess.DEVNULL,  # Don't wait for input
                        cwd=run_cwd,
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

    def handle_error(self, error_message: str) -> None:
        """Handle and log error messages."""
        self.update_status("ERROR")
        logger.error(error_message)
        self.log_operation(f"Error: {error_message}")
