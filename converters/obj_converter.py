"""
OBJ format to GLB format conversion operations.
"""

import os
import subprocess
import logging
import trimesh
import numpy as np
import platform
import shutil
from typing import Optional, List
from .base_converter import BaseConverter, hex_to_linear_rgb


# Material/texture directive keys in OBJ/MTL that reference external files.
_MTL_FILE_KEYS = (
    "map_kd", "map_ka", "map_ks", "map_ke", "map_d", "map_bump",
    "bump", "disp", "decal", "refl", "norm",
)


def _reference_is_unsafe(value: str) -> bool:
    """True if an OBJ/MTL file reference is absolute or escapes its directory.

    obj2gltf resolves these relative to the OBJ's directory (cwd), so an
    absolute path or one containing '..' lets a malicious upload read arbitrary
    server files and embed them into the output GLB. We reject such uploads.
    """
    token = (value or "").strip().strip('"').replace("\\", "/")
    if not token:
        return False
    if os.path.isabs(token) or token.startswith("~"):
        return True
    return any(part == ".." for part in token.split("/"))


def assert_safe_obj_references(obj_path: str) -> None:
    """Raise ValueError if the OBJ or its MTLs reference files outside their dir."""
    obj_dir = os.path.dirname(obj_path)

    def _scan(path, line_keys):
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    parts = line.strip().split(None, 1)
                    if len(parts) != 2:
                        continue
                    key, val = parts[0].lower(), parts[1]
                    if key in line_keys:
                        # texture directives can carry options before the path;
                        # the filename is the last whitespace-separated token.
                        candidate = val.split()[-1] if val.split() else val
                        if _reference_is_unsafe(candidate):
                            raise ValueError(
                                f"Unsafe file reference in {os.path.basename(path)}: {candidate}"
                            )
        except (OSError, UnicodeDecodeError):
            pass

    # OBJ -> mtllib references
    mtl_names = []
    try:
        with open(obj_path, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                parts = line.strip().split(None, 1)
                if len(parts) == 2 and parts[0].lower() == "mtllib":
                    for name in parts[1].split():
                        if _reference_is_unsafe(name):
                            raise ValueError(f"Unsafe mtllib reference: {name}")
                        mtl_names.append(name)
    except (OSError, UnicodeDecodeError):
        return

    # MTL -> texture references
    for name in mtl_names:
        mtl_path = os.path.join(obj_dir, os.path.basename(name))
        if os.path.exists(mtl_path):
            _scan(mtl_path, _MTL_FILE_KEYS)


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


class OBJConverter(BaseConverter):
    # OBJ is effectively unitless; map the user-declared source unit to metres.
    # NOTE: unlike STL (which historically forced cm→m), OBJ historically applied
    # NO unit scaling, so the default here is "m" (no scaling) for backward compat.
    _UNIT_TO_METERS = {"mm": 0.001, "cm": 0.01, "m": 1.0}

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.supported_extensions = {".obj"}
        self.source_unit = "m"

        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        local_obj2gltf = os.path.join(
            project_dir, "node_modules", "obj2gltf", "bin", "obj2gltf.js"
        )
        if os.path.exists(local_obj2gltf):
            self.obj2gltf_cmd = ["node", local_obj2gltf]
        else:
            npx_path = shutil.which("npx.cmd") or shutil.which("npx")
            if not npx_path:
                if platform.system() == "Windows":
                    default_win = r"C:\Program Files\nodejs\npx.cmd"
                    npx_path = default_win if os.path.exists(default_win) else "npx"
                else:
                    npx_path = "npx"
            self.obj2gltf_cmd = [npx_path, "obj2gltf"]

        self.texture_files: List[str] = []
        self.mtl_file: Optional[str] = None

    def set_source_unit(self, unit: str) -> None:
        """Set the assumed source unit of the OBJ file (auto | mm | cm | m).

        'auto' measures the raw extents after conversion and picks the most
        plausible unit (see BaseConverter.auto_detect_unit). Default 'm'
        means no scaling, preserving the original behaviour.
        """
        unit = (unit or "").strip().lower()
        if unit == "auto" or unit in self._UNIT_TO_METERS:
            self.source_unit = unit
            self.log_operation(f"OBJ source unit set to '{unit}'")
        else:
            self.log_operation(
                f"Unknown OBJ source unit '{unit}', keeping '{self.source_unit}'",
                "WARNING",
            )

    def validate(self, file_path: str) -> bool:
        """
        Validate OBJ file
        Args:
            file_path: Path of the file to be checked
        Returns:
            bool: Is the file valid
        """
        if not super().validate(file_path):
            return False

        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.supported_extensions:
            self.handle_error(f"Unsupported file format: {file_ext}")
            return False

        return True

    def set_material_file(self, mtl_path: str) -> None:
        """
        Set MTL file
        Args:
            mtl_path: Path of the MTL file
        """
        if os.path.exists(mtl_path):
            self.mtl_file = mtl_path
            self.log_operation(f"MTL file set: {mtl_path}")

    def add_texture_file(self, texture_path: str) -> None:
        """
        Add texture file
        Args:
            texture_path: Path of the texture file
        """
        if os.path.exists(texture_path):
            self.texture_files.append(texture_path)
            self.log_operation(f"Texture file added: {texture_path}")

    def convert(
        self, input_path: str, output_path: str, color: Optional[str] = None
    ) -> bool:
        """
        Convert OBJ file to GLB format
        Args:
            input_path: Path of the OBJ file to be converted
            output_path: Path of the output GLB file
            color: Optional hex color to apply to the model
        Returns:
            bool: Was the conversion successful
        """
        temp_input = None
        try:
            self.update_status("CONVERTING")
            self.log_operation(f"Starting OBJ to GLB conversion")
            self.log_operation(f"Input: {input_path}")
            self.log_operation(f"Output: {output_path}")

            # Create output directory
            ensure_directory(os.path.dirname(output_path))

            # Get the directory where the OBJ file is located
            obj_dir = os.path.dirname(input_path)
            obj_filename = os.path.basename(input_path)

            # Security: obj2gltf reads MTL/texture paths from the (untrusted)
            # OBJ relative to cwd; reject absolute/'..' references that could
            # exfiltrate server files into the output GLB.
            assert_safe_obj_references(input_path)

            # Log MTL and texture files if present
            if self.mtl_file:
                self.log_operation(f"MTL file: {self.mtl_file}")
            if self.texture_files:
                self.log_operation(f"Texture files: {', '.join(self.texture_files)}")

            # obj2gltf automatically looks for MTL and textures in the same directory as the OBJ file
            # So we need to ensure all files are in the same directory

            # If color is specified, we'll apply it after conversion
            # Otherwise, use the original materials
            if color:
                self.log_operation(f"Color will be applied after conversion: {color}")

            # Prepare obj2gltf command
            cmd = [
                *self.obj2gltf_cmd,
                "-i",
                input_path,
                "-o",
                output_path,
                "--checkTransparency",  # Handle transparent textures
                "--binary",  # Embed textures in GLB
            ]

            # Run the command
            self.log_operation(f"Running conversion command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=obj_dir,  # Run in the OBJ directory
                timeout=300,
            )  # 5 minute timeout

            # Log output
            if result.stdout:
                self.log_operation(f"obj2gltf stdout: {result.stdout}")
            if result.stderr:
                self.log_operation(f"obj2gltf stderr: {result.stderr}")

            # Check the result
            if result.returncode != 0:
                self.handle_error(
                    f"Conversion failed (exit code {result.returncode}): {result.stderr}"
                )
                return False

            # Verify output file exists
            if not os.path.exists(output_path):
                self.handle_error("Output GLB file was not created")
                return False

            # Post-processing: Apply color and/or scaling
            # BUT only if there are no textures (don't override textures with solid color)
            self.log_operation(
                f"Post-processing check - color: {color}, mtl_file: {self.mtl_file}, texture_files: {len(self.texture_files) if self.texture_files else 0}"
            )

            # Determine if we need post-processing
            needs_color = color and not (self.mtl_file or self.texture_files)
            needs_scaling = False
            # Unit conversion is needed whenever the user picked a non-metre source unit.
            # 'auto' is resolved below once the raw extents are known.
            needs_unit_scale = self.source_unit not in ("m", "auto")
            unit_scale = self._UNIT_TO_METERS.get(self.source_unit, 1.0)

            # Check if scaling is needed
            try:
                temp_mesh = trimesh.load(output_path)
                if isinstance(temp_mesh, trimesh.Scene):
                    bounds = temp_mesh.bounds
                    extents = bounds[1] - bounds[0]
                else:
                    extents = temp_mesh.extents

                dimensions = {"x": extents[0], "y": extents[1], "z": extents[2]}
                self.log_operation(f"Model dimensions: {dimensions}")

                if self.source_unit == "auto":
                    detected, unit_scale = self.auto_detect_unit(float(max(extents)))
                    self.source_unit = detected
                    needs_unit_scale = unit_scale != 1.0
                    self.log_operation(
                        f"Auto-detected OBJ source unit: '{detected}' "
                        f"(raw max extent {float(max(extents)):.3f} -> {float(max(extents)) * unit_scale:.3f} m)"
                    )

                # Only scale if max_dimension was explicitly set by user
                if self.max_dimension > 0:
                    scale_factor = self.calculate_scale_factor(dimensions)
                    if scale_factor != 1.0:
                        needs_scaling = True
                        self.log_operation(f"Scaling needed - factor: {scale_factor}")
                    else:
                        self.log_operation(
                            "No scaling needed - model already at target size"
                        )
                else:
                    self.log_operation(
                        "No scaling applied - max_dimension not set by user"
                    )

                del temp_mesh
            except Exception as e:
                self.log_operation(
                    f"Warning: Could not check dimensions: {str(e)}", "WARNING"
                )

            # Only reload and process if needed
            if needs_color or needs_scaling or needs_unit_scale:
                try:
                    self.log_operation(
                        f"Post-processing GLB - color: {needs_color}, scaling: {needs_scaling}, unit: {self.source_unit}"
                    )
                    mesh = trimesh.load(output_path)

                    # Apply source-unit conversion first (before any max_dimension limit)
                    if needs_unit_scale:
                        self.log_operation(
                            f"Applying {self.source_unit}->m unit scale: {unit_scale}"
                        )
                        if isinstance(mesh, trimesh.Scene):
                            for geom in mesh.geometry.values():
                                if isinstance(geom, trimesh.Trimesh):
                                    geom.apply_scale(unit_scale)
                        else:
                            mesh.apply_scale(unit_scale)

                    # Apply max-dimension scaling (recomputed on the unit-scaled mesh)
                    if needs_scaling:
                        if isinstance(mesh, trimesh.Scene):
                            bounds = mesh.bounds
                            extents = bounds[1] - bounds[0]
                        else:
                            extents = mesh.extents

                        dimensions = {"x": extents[0], "y": extents[1], "z": extents[2]}
                        scale_factor = self.calculate_scale_factor(dimensions)

                        # ALWAYS apply if max_dimension is set
                        if self.max_dimension > 0:
                            self.log_operation(f"Applying scale factor: {scale_factor}")
                            if isinstance(mesh, trimesh.Scene):
                                for geom in mesh.geometry.values():
                                    if isinstance(geom, trimesh.Trimesh):
                                        geom.apply_scale(scale_factor)
                            else:
                                mesh.apply_scale(scale_factor)

                    # Apply color (if needed)
                    if needs_color:
                        # sRGB picker value → linear (glTF baseColorFactor/COLOR_0
                        # are linear; without this iOS AR shows the color washed out)
                        lr, lg, lb = hex_to_linear_rgb(color)
                        r = int(round(lr * 255))
                        g = int(round(lg * 255))
                        b = int(round(lb * 255))

                        # Create PBR material with the specified color
                        material = trimesh.visual.material.PBRMaterial(
                            baseColorFactor=[lr, lg, lb, 1.0],
                            metallicFactor=0.1,
                            roughnessFactor=0.9,
                        )

                        # Apply color to all meshes
                        if isinstance(mesh, trimesh.Scene):
                            for geom in mesh.geometry.values():
                                if isinstance(geom, trimesh.Trimesh):
                                    geom.visual = trimesh.visual.TextureVisuals(
                                        material=material
                                    )
                                    vertex_colors = np.tile(
                                        [r, g, b, 255], (len(geom.vertices), 1)
                                    )
                                    geom.visual.vertex_colors = vertex_colors.astype(
                                        np.uint8
                                    )
                        elif isinstance(mesh, trimesh.Trimesh):
                            mesh.visual = trimesh.visual.TextureVisuals(
                                material=material
                            )
                            vertex_colors = np.tile(
                                [r, g, b, 255], (len(mesh.vertices), 1)
                            )
                            mesh.visual.vertex_colors = vertex_colors.astype(np.uint8)

                        self.log_operation(f"Color applied: RGB({r}, {g}, {b})")

                    # Save the processed mesh (only once!) atomically: temp +
                    # rename so a failed export can't leave a truncated GLB.
                    tmp_output = f"{output_path}.tmp.{os.getpid()}"
                    mesh.export(tmp_output, file_type="glb")
                    os.replace(tmp_output, output_path)
                    self.log_operation("Post-processing completed successfully")

                except Exception as e:
                    self.log_operation(
                        f"Warning: Post-processing failed: {str(e)}", "WARNING"
                    )
                    import traceback

                    self.log_operation(f"Traceback: {traceback.format_exc()}")
                    # Continue even if post-processing fails
            elif color and (self.mtl_file or self.texture_files):
                self.log_operation(
                    "Color not applied - textures detected, preserving original materials"
                )
            else:
                # No post-processing needed
                self.log_operation(
                    "No post-processing needed - using original obj2gltf output"
                )

            self.log_operation("OBJ file converted successfully")
            return True

        except subprocess.TimeoutExpired:
            self.handle_error("Conversion timed out after 5 minutes")
            return False
        except Exception as e:
            self.handle_error(f"Error during conversion: {str(e)}")
            import traceback

            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return False
        finally:
            # Don't cleanup MTL and texture files here - they're needed for conversion
            # They will be cleaned up when temp_dir is removed
            pass

    def calculate_scale_factor(self, dimensions: dict) -> float:
        """
        Calculate scale factor based on maximum dimension
        Args:
            dimensions: Dictionary containing x, y, z dimensions
        Returns:
            float: Scale factor to apply
        """
        return super().calculate_scale_factor(dimensions)

    def cleanup(self) -> None:
        """Clean up temporary files"""
        super().cleanup()

        # Note: MTL and texture files are NOT deleted here
        # They are in the temp_dir which will be cleaned up by the upload handler
        # This ensures they're available during the entire conversion process

        self.texture_files = []
        self.mtl_file = None

    def handle_error(self, error_message):
        self.update_status("ERROR")
        self.log_operation(f"Error during conversion: {error_message}")
