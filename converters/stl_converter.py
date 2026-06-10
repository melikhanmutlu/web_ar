"""
STL format to GLB format conversion operations using trimesh.
"""

import os
import logging
import trimesh
import numpy as np
from .base_converter import BaseConverter, hex_to_linear_rgb

# Complexity guards: reject meshes that would exhaust memory during processing.
# Overridable via environment for bigger deployments.
MAX_MESH_FACES = int(os.environ.get("MAX_MESH_FACES", 2_000_000))
MAX_MESH_VERTICES = int(os.environ.get("MAX_MESH_VERTICES", 2_000_000))


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


class STLConverter(BaseConverter):
    """Converter for STL files to GLB format using trimesh."""

    # STL files are unitless; map the user-declared source unit to metres
    # (GLB standard). "cm" stays the default for backward compatibility.
    _UNIT_TO_METERS = {"mm": 0.001, "cm": 0.01, "m": 1.0}

    def __init__(self):
        super().__init__()
        self.supported_extensions = {".stl"}
        self.logger = logging.getLogger(__name__)
        self.source_unit = "cm"

    def set_source_unit(self, unit: str) -> None:
        """Set the assumed source unit of the STL file (mm | cm | m)."""
        unit = (unit or "").strip().lower()
        if unit in self._UNIT_TO_METERS:
            self.source_unit = unit
            self.log_operation(f"STL source unit set to '{unit}'")
        else:
            self.log_operation(
                f"Unknown STL source unit '{unit}', keeping '{self.source_unit}'",
                "WARNING",
            )

    def validate(self, file_path: str) -> bool:
        """
        Validate STL file
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

        try:
            # Try to load the STL file to validate it
            mesh = trimesh.load(file_path)
            if not isinstance(mesh, (trimesh.Trimesh, trimesh.Scene)):
                self.handle_error("Invalid STL file format")
                return False
        except Exception as e:
            self.handle_error(f"Error validating STL file: {str(e)}")
            return False

        return True

    def convert(self, input_path: str, output_path: str, color: str = None) -> bool:
        """
        Convert STL file to GLB format using trimesh
        Args:
            input_path: Path of the STL file to be converted
            output_path: Path of the output GLB file
            color: Optional color to apply to the mesh
        Returns:
            bool: Was the conversion successful
        """
        try:
            self.update_status("CONVERTING")
            self.log_operation("Starting STL to GLB conversion")
            self.log_operation(f"Input: {input_path}")
            self.log_operation(f"Output: {output_path}")

            # Create output directory
            ensure_directory(os.path.dirname(output_path))

            # Load the STL file
            self.log_operation("Loading STL file...")
            mesh = trimesh.load(input_path)

            if not isinstance(mesh, (trimesh.Trimesh, trimesh.Scene)):
                self.handle_error(f"Invalid mesh type: {type(mesh)}")
                return False

            # Ensure we have a scene to process and flatten all node transforms
            if isinstance(mesh, trimesh.Trimesh):
                scene = trimesh.Scene([mesh])
            else:
                scene = mesh

            flattened_meshes = []
            for node_name in scene.graph.nodes_geometry:
                transform, geom_name = scene.graph[node_name]
                geometry = scene.geometry.get(geom_name)
                if geometry is None:
                    continue
                geom_copy = geometry.copy()
                geom_copy.apply_transform(transform)
                flattened_meshes.append(geom_copy)

            if not flattened_meshes:
                self.handle_error("No geometry found in STL scene")
                return False

            if len(flattened_meshes) == 1:
                mesh = flattened_meshes[0]
            else:
                mesh = trimesh.util.concatenate(flattened_meshes)

            self.log_operation(
                f"Flattened scene: {len(flattened_meshes)} geometries merged into single mesh"
            )

            # Complexity guard — fail fast with a clear message instead of OOM
            n_faces = len(mesh.faces)
            n_verts = len(mesh.vertices)
            if n_faces > MAX_MESH_FACES or n_verts > MAX_MESH_VERTICES:
                self.handle_error(
                    f"Model too complex: {n_faces:,} faces / {n_verts:,} vertices "
                    f"(limits: {MAX_MESH_FACES:,} faces, {MAX_MESH_VERTICES:,} vertices). "
                    "Please decimate the mesh and re-upload."
                )
                return False

            # Apply basis correction once (Z-up -> Y-up) directly to vertices
            basis_correction = trimesh.transformations.rotation_matrix(
                angle=np.radians(-90), direction=[1, 0, 0]
            )
            mesh.apply_transform(basis_correction)
            self.log_operation("Applied basis correction: -90° around X (Z-up to Y-up)")

            # STL files are unitless; GLB standard requires meters. Convert from the
            # user-declared source unit (default cm) so the model appears at the correct
            # real-world scale in model-viewer and AR.
            unit_scale = self._UNIT_TO_METERS.get(self.source_unit, 0.01)
            mesh.apply_scale(unit_scale)
            self.log_operation(
                f"Applied {self.source_unit}->m unit conversion: scale {unit_scale}"
            )

            # Get model dimensions (now in meters, consistent with GLB standard)
            extents = mesh.extents

            dimensions = {"x": extents[0], "y": extents[1], "z": extents[2]}

            self.log_operation(f"Model dimensions (meters): {dimensions}")

            # Calculate scale factor only if max_dimension was explicitly set by user
            # Default max_dimension is 0.5 but we only scale if user checked the checkbox
            if self.max_dimension > 0:
                scale_factor = self.calculate_scale_factor(dimensions)
                if scale_factor != 1.0:
                    self.log_operation(f"Applying scale factor: {scale_factor}")
                    if isinstance(mesh, trimesh.Scene):
                        for geom in mesh.geometry.values():
                            if isinstance(geom, trimesh.Trimesh):
                                geom.apply_scale(scale_factor)
                    else:
                        mesh.apply_scale(scale_factor)
                else:
                    self.log_operation(
                        "No scaling needed - model already at target size"
                    )
            else:
                self.log_operation("No scaling applied - max_dimension not set by user")

            # Apply color using vertex colors (no UV coordinates needed)
            # STL meshes have no UV data, so TextureVisuals would create phantom TEXCOORD_0
            # causing purple striped texture in AR (iOS Quick Look, Android Scene Viewer)
            # Use ColorVisuals with vertex colors instead
            if color:
                try:
                    self.log_operation(f"Applying color: {color}")
                    # Color picker gives sRGB; glTF COLOR_0 vertex data is linear.
                    # Convert so renderers (and especially iOS AR) show the picked color.
                    lr, lg, lb = hex_to_linear_rgb(color)
                    r = int(round(lr * 255))
                    g = int(round(lg * 255))
                    b = int(round(lb * 255))

                    # Apply vertex colors only (no TextureVisuals, no phantom UV data)
                    if isinstance(mesh, trimesh.Scene):
                        for geom in mesh.geometry.values():
                            if isinstance(geom, trimesh.Trimesh):
                                vertex_colors = np.tile(
                                    [r, g, b, 255], (len(geom.vertices), 1)
                                )
                                geom.visual = trimesh.visual.ColorVisuals(
                                    vertex_colors=vertex_colors.astype(np.uint8)
                                )
                    else:
                        vertex_colors = np.tile([r, g, b, 255], (len(mesh.vertices), 1))
                        mesh.visual = trimesh.visual.ColorVisuals(
                            vertex_colors=vertex_colors.astype(np.uint8)
                        )

                    self.log_operation(
                        f"Color applied successfully: RGB({r}, {g}, {b}) using vertex colors (no UV)"
                    )
                except Exception as e:
                    self.log_operation(
                        f"Warning: Could not apply color: {str(e)}", "WARNING"
                    )
                    import traceback

                    self.log_operation(f"Traceback: {traceback.format_exc()}")
                    # Continue even if color application fails
            else:
                # No color specified - apply default gray using vertex colors
                self.log_operation(
                    "No color specified - applying default gray using vertex colors"
                )
                try:
                    # Default light gray sRGB #cccccc, stored as linear (glTF COLOR_0
                    # expects linear values): linear(0.8) ≈ 0.604 → 154
                    default_r, default_g, default_b = 154, 154, 154

                    if isinstance(mesh, trimesh.Scene):
                        for geom in mesh.geometry.values():
                            if isinstance(geom, trimesh.Trimesh):
                                vertex_colors = np.tile(
                                    [default_r, default_g, default_b, 255],
                                    (len(geom.vertices), 1),
                                )
                                geom.visual = trimesh.visual.ColorVisuals(
                                    vertex_colors=vertex_colors.astype(np.uint8)
                                )
                    else:
                        vertex_colors = np.tile(
                            [default_r, default_g, default_b, 255], (len(mesh.vertices), 1)
                        )
                        mesh.visual = trimesh.visual.ColorVisuals(
                            vertex_colors=vertex_colors.astype(np.uint8)
                        )

                    self.log_operation(
                        f"Default gray applied using vertex colors (no UV/texture data)"
                    )
                except Exception as e:
                    self.log_operation(
                        f"Warning: Could not apply default color: {str(e)}",
                        "WARNING",
                    )

            # Note: Basis correction (Z-up to Y-up) is NOT applied here
            # It will be handled in glb_modifier during normalization
            # This keeps the model in its original orientation on upload

            # Convert to scene if it's a single mesh
            if isinstance(mesh, trimesh.Trimesh):
                self.log_operation("Converting mesh to scene")
                scene = trimesh.Scene([mesh])
            else:
                scene = mesh

            # Export as GLB
            self.log_operation("Exporting to GLB format")
            scene.export(output_path)

            if not os.path.exists(output_path):
                self.handle_error("Output file was not created")
                return False

            file_size = os.path.getsize(output_path)
            self.log_operation(
                f"STL file converted successfully. Output size: {file_size} bytes"
            )
            return True

        except Exception as e:
            self.handle_error(f"Error during conversion: {str(e)}")
            import traceback

            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return False

    def handle_error(self, error_message: str) -> None:
        """
        Handle and log error messages
        Args:
            error_message: Error message to be logged
        """
        self.update_status("ERROR")
        self.log_operation(f"Error during conversion: {error_message}")
