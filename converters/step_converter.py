"""
STEP (ISO 10303-21, .step/.stp) to GLB format conversion using cascadio.

cascadio wraps OpenCASCADE: it tessellates the B-rep solids and writes a GLB
directly. Unlike STL/OBJ, STEP files carry real units — OpenCASCADE converts
them to meters and remaps Z-up to Y-up while writing the GLB, so no
source-unit selection or basis correction is needed here.
"""

import os
import logging

import cascadio
import numpy as np
import trimesh

from .base_converter import BaseConverter, hex_to_linear_rgb
from .stl_converter import (
    MAX_MESH_FACES,
    MAX_MESH_VERTICES,
    ensure_directory,
    safe_delete_file,
)

logger = logging.getLogger(__name__)


class STEPConverter(BaseConverter):
    """Converter for STEP files to GLB format using cascadio (OpenCASCADE)."""

    def __init__(self):
        super().__init__()
        self.supported_extensions = {".step", ".stp"}
        self.logger = logging.getLogger(__name__)

    def validate(self, file_path: str) -> bool:
        """
        Validate STEP file
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

        # Cheap sanity check before handing untrusted input to the OpenCASCADE
        # parser: every STEP Part 21 file starts with an 'ISO-10303-21' header.
        try:
            with open(file_path, "rb") as f:
                header = f.read(128)
            if b"ISO-10303-21" not in header:
                self.handle_error(
                    "Not a valid STEP file (missing ISO-10303-21 header)"
                )
                return False
        except Exception as e:
            self.handle_error(f"Error validating STEP file: {str(e)}")
            return False

        return True

    @staticmethod
    def _geometry_rgba(geometry):
        """Read a part's flat color (glTF baseColorFactor, linear) as RGBA 0-255.

        Falls back to the same default gray the STL converter uses (sRGB
        #cccccc stored as linear) when the part carries no color.
        """
        material = getattr(geometry.visual, "material", None)
        factor = getattr(material, "baseColorFactor", None)
        if factor is not None:
            arr = np.asarray(factor, dtype=np.float64).flatten()
            if arr.size >= 3:
                if arr.max() <= 1.0:
                    arr = arr * 255.0
                rgba = np.full(4, 255.0)
                rgba[: min(4, arr.size)] = arr[:4]
                return np.clip(np.round(rgba), 0, 255).astype(np.uint8)
        return np.array([154, 154, 154, 255], dtype=np.uint8)

    def convert(self, input_path: str, output_path: str, color: str = None) -> bool:
        """
        Convert STEP file to GLB format using cascadio
        Args:
            input_path: Path of the STEP file to be converted
            output_path: Path of the output GLB file
            color: Optional color to apply to the mesh
        Returns:
            bool: Was the conversion successful
        """
        tmp_glb = f"{output_path}.cascadio.{os.getpid()}"
        try:
            self.update_status("CONVERTING")
            self.log_operation("Starting STEP to GLB conversion")
            self.log_operation(f"Input: {input_path}")
            self.log_operation(f"Output: {output_path}")

            out_dir = os.path.dirname(output_path)
            if out_dir:
                ensure_directory(out_dir)

            # Tessellate the B-rep solids straight to GLB via OpenCASCADE.
            self.log_operation("Tessellating STEP file with cascadio/OpenCASCADE...")
            result = cascadio.step_to_glb(input_path, tmp_glb)
            if result != 0 or not os.path.exists(tmp_glb):
                self.handle_error(
                    f"cascadio failed to convert STEP file (exit code {result})"
                )
                return False

            # Load the tessellated GLB for the complexity guard and any edits
            scene = trimesh.load(tmp_glb, file_type="glb")
            if isinstance(scene, trimesh.Trimesh):
                scene = trimesh.Scene([scene])
            if not isinstance(scene, trimesh.Scene):
                self.handle_error(f"Invalid mesh type: {type(scene)}")
                return False

            meshes = [
                g
                for g in scene.geometry.values()
                if isinstance(g, trimesh.Trimesh)
            ]
            if not meshes:
                self.handle_error("No geometry found in STEP file")
                return False

            # Complexity guard — fail fast with a clear message instead of OOM
            n_faces = sum(len(g.faces) for g in meshes)
            n_verts = sum(len(g.vertices) for g in meshes)
            if n_faces > MAX_MESH_FACES or n_verts > MAX_MESH_VERTICES:
                self.handle_error(
                    f"Model too complex: {n_faces:,} faces / {n_verts:,} vertices "
                    f"(limits: {MAX_MESH_FACES:,} faces, {MAX_MESH_VERTICES:,} vertices). "
                    "Please simplify the model and re-upload."
                )
                return False

            # STEP units are already converted to meters by OpenCASCADE
            extents = scene.extents
            dimensions = {"x": extents[0], "y": extents[1], "z": extents[2]}
            self.log_operation(f"Model dimensions (meters): {dimensions}")

            scale_factor = 1.0
            if self.max_dimension > 0:
                scale_factor = self.calculate_scale_factor(dimensions)

            # Without edits, keep the OpenCASCADE-authored GLB untouched: it
            # preserves per-part STEP colors that a trimesh re-export would
            # drop (trimesh bakes materials back to default vertex colors).
            if not color and scale_factor == 1.0:
                self.log_operation(
                    "No color/scaling requested - keeping cascadio GLB as-is"
                )
                os.replace(tmp_glb, output_path)
                file_size = os.path.getsize(output_path)
                self.log_operation(
                    f"STEP file converted successfully. Output size: {file_size} bytes"
                )
                return True

            # Edits requested: flatten node transforms into the vertices and
            # bake each part's color as linear vertex colors (COLOR_0), the
            # same AR-safe representation the STL converter uses (no phantom
            # TEXCOORD_0 from textureless materials).
            if color:
                lr, lg, lb = hex_to_linear_rgb(color)
                user_rgba = np.array(
                    [
                        int(round(lr * 255)),
                        int(round(lg * 255)),
                        int(round(lb * 255)),
                        255,
                    ],
                    dtype=np.uint8,
                )
                self.log_operation(f"Applying color: {color}")
            else:
                user_rgba = None

            flattened_meshes = []
            for node_name in scene.graph.nodes_geometry:
                transform, geom_name = scene.graph[node_name]
                geometry = scene.geometry.get(geom_name)
                if not isinstance(geometry, trimesh.Trimesh):
                    continue
                geom_copy = geometry.copy()
                geom_copy.apply_transform(transform)
                rgba = user_rgba if user_rgba is not None else self._geometry_rgba(
                    geometry
                )
                vertex_colors = np.tile(rgba, (len(geom_copy.vertices), 1))
                geom_copy.visual = trimesh.visual.ColorVisuals(
                    vertex_colors=vertex_colors.astype(np.uint8)
                )
                flattened_meshes.append(geom_copy)

            if not flattened_meshes:
                self.handle_error("No geometry found in STEP scene")
                return False

            if len(flattened_meshes) == 1:
                mesh = flattened_meshes[0]
            else:
                mesh = trimesh.util.concatenate(flattened_meshes)
            self.log_operation(
                f"Flattened scene: {len(flattened_meshes)} geometries merged into single mesh"
            )

            if scale_factor != 1.0:
                self.log_operation(f"Applying scale factor: {scale_factor}")
                mesh.apply_scale(scale_factor)

            # Export as GLB atomically: write to a temp file then rename, so a
            # crash/failure mid-export never leaves a truncated GLB to be served.
            self.log_operation("Exporting to GLB format")
            tmp_output = f"{output_path}.tmp.{os.getpid()}"
            trimesh.Scene([mesh]).export(tmp_output, file_type="glb")
            os.replace(tmp_output, output_path)

            if not os.path.exists(output_path):
                self.handle_error("Output file was not created")
                return False

            file_size = os.path.getsize(output_path)
            self.log_operation(
                f"STEP file converted successfully. Output size: {file_size} bytes"
            )
            return True

        except Exception as e:
            self.handle_error(f"Error during conversion: {str(e)}")
            import traceback

            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return False
        finally:
            safe_delete_file(tmp_glb)

    def handle_error(self, error_message: str) -> None:
        """
        Handle and log error messages
        Args:
            error_message: Error message to be logged
        """
        self.update_status("ERROR")
        self.errors.append(error_message)
        self.log_operation(f"Error during conversion: {error_message}")
