"""
STEP (ISO 10303-21, .step/.stp) to GLB conversion using cascadio.

cascadio wraps OpenCASCADE: it tessellates the B-rep solids and writes a GLB
in metres, still Z-up, with one node per part (assembly instances named after
their OCAF label, e.g. "=>[0:1:1:4]") and one material per STEP colour.

OpenCASCADE runs in a child process (converters/step_cli.py) so a crash or a
memory blow-up on a hostile file cannot take the web/worker process down. The
output is then edited with pygltflib only — never re-exported through trimesh,
which would merge every part into one mesh and lose the assembly's layers:

* part nodes get their real part names,
* uncoloured primitives get a default material; the picker colour applies only
  when the file carried no colours of its own,
* a root node turns Z-up into glTF's Y-up and applies the max-dimension scale,
* every part (repeats of one part together) gets its own named material, so the
  viewer's Layers panel and the slicer work per part (converters/layers.py).
"""

import logging
import os
import subprocess
import sys

from pygltflib import GLTF2, Node, Scene

from .base_converter import BaseConverter, hex_to_linear_rgb
from .layers import default_material, normalize_layers
from .stl_converter import (
    MAX_MESH_FACES,
    MAX_MESH_VERTICES,
    ensure_directory,
    safe_delete_file,
)

logger = logging.getLogger(__name__)

# -90 degrees about X (glTF quaternion x, y, z, w): STEP is Z-up, glTF and
# model-viewer (and therefore AR floor placement) are Y-up.
Z_UP_TO_Y_UP = [-0.70710678, 0.0, 0.0, 0.70710678]

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _attempt_timeout():
    """Seconds one OpenCASCADE tessellation attempt may run."""
    try:
        value = int(os.environ.get("STEP_CONVERT_TIMEOUT", 180))
    except (TypeError, ValueError):
        return 180
    return value if value > 0 else 180


def _glb_complexity(glb_path):
    """(faces, vertices) of a GLB read from accessor counts alone — no
    trimesh geometry decode, so huge tessellations can be rejected without
    paying their full memory cost."""
    # load_binary explicitly: GLTF2.load() dispatches on file extension.
    gltf = GLTF2().load_binary(glb_path)
    faces = verts = 0
    for mesh in (gltf.meshes or []):
        for prim in (mesh.primitives or []):
            pos = getattr(prim.attributes, "POSITION", None)
            if pos is None:
                continue
            verts += gltf.accessors[pos].count
            if prim.indices is not None:
                faces += gltf.accessors[prim.indices].count // 3
            else:
                faces += gltf.accessors[pos].count // 3
    return faces, verts


class STEPConverter(BaseConverter):
    """Converter for STEP files to GLB format using cascadio (OpenCASCADE)."""

    # (tol_linear, tol_angular) tessellation qualities, finest first. The
    # first entry matches cascadio's defaults; later (coarser) entries are
    # only used when the resulting mesh exceeds the complexity limits (or the
    # attempt times out) — STEP is a B-rep format, so triangle count is a
    # property of the tessellation tolerance, not of the file itself.
    TESSELLATION_LADDER = [(0.01, 0.5), (0.05, 0.8), (0.2, 1.0), (1.0, 1.5)]

    def __init__(self):
        super().__init__()
        self.supported_extensions = {".step", ".stp"}
        self.logger = logging.getLogger(__name__)
        # Viewer layers found in the assembly ([] for single-part models).
        self.layers = []

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

    def convert(self, input_path: str, output_path: str, color: str = None) -> bool:
        """
        Convert STEP file to GLB format using cascadio
        Args:
            input_path: Path of the STEP file to be converted
            output_path: Path of the output GLB file
            color: Optional colour, used only when the STEP carries none
        Returns:
            bool: Was the conversion successful
        """
        # Work beside the target and move into place only on success, so a
        # failed run never leaves a truncated or half-edited GLB to be served.
        # The .glb suffix matters: pygltflib picks GLB vs glTF by extension.
        work_glb = f"{output_path}.step.{os.getpid()}.glb"
        self.layers = []
        try:
            self.update_status("CONVERTING")
            self.log_operation("Starting STEP to GLB conversion")
            self.log_operation(f"Input: {input_path}")
            self.log_operation(f"Output: {output_path}")

            if not self.validate(input_path):
                return False

            out_dir = os.path.dirname(output_path)
            if out_dir:
                ensure_directory(out_dir)

            if not self._tessellate(input_path, work_glb):
                return False
            if not self._post_process(work_glb, color):
                return False

            self.layers = normalize_layers(work_glb)
            if self.layers:
                self.log_operation(f"Assembly layers: {len(self.layers)}")

            os.replace(work_glb, output_path)
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
            safe_delete_file(work_glb)

    def _run_cascadio(self, input_path, output_path, tol_linear, tol_angular):
        """One tessellation attempt in a child process.

        Returns "ok", "timeout" or "failed".
        """
        command = [
            sys.executable, "-m", "converters.step_cli",
            os.path.abspath(input_path), os.path.abspath(output_path),
            "--tol-linear", str(tol_linear),
            "--tol-angular", str(tol_angular),
        ]
        try:
            result = subprocess.run(
                command, cwd=_REPO_ROOT, capture_output=True, text=True,
                timeout=_attempt_timeout(),
            )
        except subprocess.TimeoutExpired:
            return "timeout"
        if result.returncode != 0 or not os.path.exists(output_path):
            self.log_operation(
                f"cascadio exited with {result.returncode}: "
                f"{(result.stderr or '').strip()[-500:]}",
                "WARNING",
            )
            return "failed"
        return "ok"

    def _tessellate(self, input_path, work_glb):
        """Tessellate the B-rep solids to GLB. If the default-quality mesh
        blows past the complexity limits (or takes too long), retry with
        coarser deflection tolerances instead of bouncing the upload."""
        n_faces = n_verts = 0
        for tol_linear, tol_angular in self.TESSELLATION_LADDER:
            self.log_operation(
                f"Tessellating STEP file with cascadio/OpenCASCADE "
                f"(tol_linear={tol_linear}, tol_angular={tol_angular})..."
            )
            safe_delete_file(work_glb)
            outcome = self._run_cascadio(input_path, work_glb, tol_linear, tol_angular)
            if outcome == "timeout":
                self.log_operation(
                    "Tessellation timed out at this tolerance — retrying coarser",
                    "WARNING",
                )
                continue
            if outcome == "failed":
                self.handle_error(
                    "STEP conversion failed. The file may be corrupt or use "
                    "unsupported STEP features."
                )
                return False

            # Complexity guard on accessor counts — no geometry decode, so an
            # over-limit tessellation is rejected cheaply.
            n_faces, n_verts = _glb_complexity(work_glb)
            if n_faces <= MAX_MESH_FACES and n_verts <= MAX_MESH_VERTICES:
                if (tol_linear, tol_angular) != self.TESSELLATION_LADDER[0]:
                    self.log_operation(
                        f"Kept automatically coarsened tessellation: "
                        f"{n_faces:,} faces / {n_verts:,} vertices"
                    )
                return True
            self.log_operation(
                f"Too complex at this tolerance: {n_faces:,} faces / "
                f"{n_verts:,} vertices (limits {MAX_MESH_FACES:,} faces, "
                f"{MAX_MESH_VERTICES:,} vertices) — retrying coarser",
                "WARNING",
            )

        if n_faces or n_verts:
            self.handle_error(
                f"Model too complex: {n_faces:,} faces / {n_verts:,} vertices "
                f"even at the coarsest tessellation (limits: {MAX_MESH_FACES:,} "
                f"faces, {MAX_MESH_VERTICES:,} vertices). "
                "Please simplify the model and re-upload."
            )
        else:
            self.handle_error(
                "STEP conversion timed out. Try simplifying the assembly or "
                "exporting fewer parts."
            )
        return False

    def _scale_factor(self, glb_path):
        """max_dimension scale for the tessellated model (1.0 when unset)."""
        if self.max_dimension <= 0:
            return 1.0
        import trimesh

        extents = trimesh.load(glb_path, force="scene").extents
        dimensions = {"x": extents[0], "y": extents[1], "z": extents[2]}
        self.log_operation(f"Model dimensions (meters): {dimensions}")
        return self.calculate_scale_factor(dimensions)

    def _post_process(self, glb_path, color):
        gltf = GLTF2.load(glb_path)
        if not gltf.meshes or _glb_complexity(glb_path)[0] == 0:
            self.handle_error("This STEP file contains no solid geometry to display.")
            return False

        # Assembly instances come out named after their OCAF label
        # ("=>[0:1:1:2]"); the part's real name is on its mesh.
        for node in gltf.nodes or []:
            name = (node.name or "").strip()
            if node.mesh is not None and (not name or name.startswith("=>[")):
                node.name = gltf.meshes[node.mesh].name or node.name

        # Colour: a STEP's own colours always win (they tell the parts apart);
        # the picker colour only applies when the file carried none.
        if gltf.materials is None:
            gltf.materials = []
        has_own_colour = any(
            p.material is not None for m in gltf.meshes for p in m.primitives
        )
        default_index = None
        for mesh in gltf.meshes:
            for primitive in mesh.primitives:
                if primitive.material is None:
                    if default_index is None:
                        gltf.materials.append(default_material("Default"))
                        default_index = len(gltf.materials) - 1
                    primitive.material = default_index
        if color:
            if has_own_colour:
                self.log_operation("STEP carries its own part colours; picker colour ignored")
            else:
                r, g, b = hex_to_linear_rgb(color)
                for material in gltf.materials:
                    material.pbrMetallicRoughness.baseColorFactor = [r, g, b, 1.0]
                self.log_operation(f"Applying color: {color}")

        # Z-up -> Y-up (and the max-dimension scale) on a new root node, so
        # every part keeps its own node, name and transform.
        if not gltf.scenes:
            children = {c for n in gltf.nodes for c in (n.children or [])}
            gltf.scenes = [Scene(nodes=[i for i in range(len(gltf.nodes)) if i not in children])]
            gltf.scene = 0
        scene = gltf.scenes[gltf.scene or 0]
        scale = self._scale_factor(glb_path)
        root = Node(name="STEP root", rotation=list(Z_UP_TO_Y_UP), children=list(scene.nodes))
        if scale != 1.0:
            self.log_operation(f"Applying scale factor: {scale}")
            root.scale = [scale, scale, scale]
        gltf.nodes.append(root)
        scene.nodes = [len(gltf.nodes) - 1]
        gltf.save(glb_path)

        # Centre the model on the origin through the root's translation. The
        # pipeline's normalize_model_to_center shifts vertex data instead and
        # has to skip assemblies whose repeated parts share one POSITION
        # accessor (e.g. 4 bolts) — leaving the model off-centre, so the
        # slicer's server-side bounds no longer matched the viewer.
        import trimesh

        bounds = trimesh.load(glb_path, force="scene").bounds
        if bounds is not None:
            root.translation = [-float(c) for c in (bounds[0] + bounds[1]) / 2.0]
            gltf.save(glb_path)
        return True

    def handle_error(self, error_message: str) -> None:
        """
        Handle and log error messages
        Args:
            error_message: Error message to be logged
        """
        self.update_status("ERROR")
        self.errors.append(error_message)
        self.log_operation(f"Error during conversion: {error_message}")
