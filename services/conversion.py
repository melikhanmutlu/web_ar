import logging
import os
import shutil

import trimesh
from pygltflib import GLTF2, Node

from converters import FBXConverter, OBJConverter, STLConverter, STEPConverter
from converters.glb_optimizer import glb_needs_decompression, optimize_glb, readable_glb
from converters.glb_quality import finalize_glb
from glb_modifier import normalize_model_to_center
from services.conversion_errors import UserFacingConversionError, friendly_conversion_error

logger = logging.getLogger(__name__)


class ConversionService:
    """Format dispatch and deterministic GLB post-processing."""

    def __init__(self, asset_quality_service):
        self.asset_quality = asset_quality_service

    @staticmethod
    def _converter(payload):
        extension = payload["file_extension"]
        if extension == ".obj":
            converter = OBJConverter()
            converter.set_source_unit(payload.get("source_unit") or "cm")
            if payload.get("mtl_path"):
                converter.set_material_file(payload["mtl_path"])
            for texture in payload.get("texture_paths") or []:
                converter.add_texture_file(texture)
            return converter
        if extension == ".stl":
            converter = STLConverter()
            converter.set_source_unit(payload.get("source_unit") or "cm")
            return converter
        if extension == ".fbx":
            return FBXConverter()
        if extension in {".step", ".stp"}:
            # STEP embeds its own units; do not apply the upload unit selector.
            return STEPConverter()
        if extension in {".glb", ".gltf"}:
            return None
        raise RuntimeError(f"Unsupported file format: {extension}")

    @staticmethod
    def _assert_valid_gltf(path, extension):
        """Fail clearly when a GLB/glTF upload is corrupt or has no geometry.

        A GLB with a valid header and garbage after it used to "convert"
        successfully and open an empty viewer.
        """
        label = "GLB" if extension == ".glb" else "glTF"
        corrupt = UserFacingConversionError(
            f"This {label} file is corrupt or incomplete and could not be read. "
            "Please re-export it and try again."
        )
        if extension == ".glb":
            with open(path, "rb") as fh:
                if fh.read(4) != b"glTF":
                    raise corrupt
        try:
            gltf = GLTF2().load(path)
        except Exception as exc:
            raise corrupt from exc
        if gltf is None:
            raise corrupt
        has_geometry = False
        for mesh in gltf.meshes or []:
            for primitive in mesh.primitives or []:
                position = getattr(primitive.attributes, "POSITION", None)
                if position is None or position >= len(gltf.accessors or []):
                    continue
                if (gltf.accessors[position].count or 0) > 0:
                    has_geometry = True
        if not has_geometry:
            raise UserFacingConversionError(
                f"This {label} file contains no 3D geometry (no meshes with vertices)."
            )
        if extension == ".glb":
            # Embedded buffer must actually be present in full.
            for buffer in gltf.buffers or []:
                if buffer.uri is None:
                    blob = gltf.binary_blob() or b""
                    if len(blob) < (buffer.byteLength or 0):
                        raise corrupt

    @staticmethod
    def _geometry_extents_m(path):
        """(vertex_count, extents) of the node-baked scene, or None if the
        file cannot be inspected (do not judge it then)."""
        try:
            with readable_glb(path) as readable:
                scene = trimesh.load(readable, force="scene")
                geometry = list(getattr(scene, "geometry", {}).values())
                vertices = sum(len(getattr(g, "vertices", [])) for g in geometry)
                if not vertices:
                    return 0, None
                bounds = scene.bounds
                if bounds is None:
                    return vertices, None
                return vertices, bounds[1] - bounds[0]
        except Exception as exc:
            logger.warning("Extent check skipped for %s: %s", path, exc)
            return None

    @classmethod
    def _assert_not_empty_output(cls, path):
        """Zero-extent (or empty) output is a failed conversion, not a model."""
        measured = cls._geometry_extents_m(path)
        if measured is None:
            return
        vertices, extents = measured
        if vertices and extents is not None and float(max(extents)) > 1e-9:
            return
        # A meshopt/draco file we could not decompress reads as empty: unknown.
        if glb_needs_decompression(path):
            return
        raise UserFacingConversionError(
            "The converted model has no usable geometry (zero size). The file may "
            "be empty or contain only degenerate triangles."
        )

    @staticmethod
    def dimensions_cm_from_extents(extents_m):
        """Dimension dict in cm from metre extents; None when there is no size.

        Sub-centimetre models keep 4 decimals (a 0.5 mm part is 0.05 cm) so
        they are not stored as 0 / missing.
        """
        largest = float(max(extents_m))
        if not largest > 1e-9:
            return None
        digits = 2 if largest * 100 >= 1 else 4
        return {
            "x": round(float(extents_m[0]) * 100, digits),
            "y": round(float(extents_m[1]) * 100, digits),
            "z": round(float(extents_m[2]) * 100, digits),
            "max": round(largest * 100, digits),
        }

    @staticmethod
    def _copy_or_pack_gltf(source_path, output_path, extension):
        if extension == ".glb":
            shutil.copy2(source_path, output_path)
        else:
            trimesh.load(source_path).export(output_path, file_type="glb")

    @staticmethod
    def _limit_dimension(path, maximum):
        """Shrink-only "Limit Model Size" for GLB/glTF input.

        Measures the node-transform-baked extents (trimesh scene bounds), then
        applies the scale on a new root node with pygltflib. Nothing is
        re-exported through trimesh, so animations, skins, morph targets and
        extensions survive and the scale is applied exactly once.
        """
        with readable_glb(path) as readable:
            scene = trimesh.load(readable, force="scene")
            bounds = scene.bounds if scene.geometry else None
        if bounds is None:
            return
        current = float(max(bounds[1] - bounds[0]))
        if not current > maximum or current <= 0:
            return
        scale = maximum / current
        gltf = GLTF2().load(path)
        if not gltf.scenes:
            return
        scene_def = gltf.scenes[gltf.scene or 0]
        roots = list(scene_def.nodes or [])
        if not roots:
            return
        # trimesh reserves the node name "world" for its own base frame; a
        # node of that name (trimesh's own GLB export uses it) under a scaled
        # parent would make trimesh mis-resolve the graph when measuring.
        for node in gltf.nodes:
            if node.name == "world":
                node.name = "world_root"
        wrapper = Node(name="Size limit", scale=[scale, scale, scale], children=roots)
        gltf.nodes.append(wrapper)
        scene_def.nodes = [len(gltf.nodes) - 1]
        gltf.save(path)

    def convert(self, payload, output_path, *, progress=None):
        """Convert an uploaded model to GLB. Failures surface as RuntimeError
        with a user-safe message (no module names or server paths)."""
        try:
            return self._convert(payload, output_path, progress=progress)
        except UserFacingConversionError:
            raise
        except Exception as exc:
            raise RuntimeError(
                friendly_conversion_error(exc, payload.get("file_extension"))
            ) from exc

    def _convert(self, payload, output_path, *, progress=None):
        report = progress or (lambda *_: None)
        extension = payload["file_extension"]
        source_path = payload["temp_file_path"]
        converter = self._converter(payload)
        report(48, "Reading source", f"Inspecting {payload['original_filename']} and conversion options.")

        if extension in {".glb", ".gltf"}:
            report(56, "Preparing GLB", "Copying or repacking the uploaded glTF asset.")
            self._assert_valid_gltf(source_path, extension)
            self._copy_or_pack_gltf(source_path, output_path, extension)
            success = os.path.isfile(output_path)
        else:
            maximum = payload.get("max_dimension")
            if maximum is not None:
                converter.set_max_dimension(maximum)
            report(58, "Converting geometry", f"Running {type(converter).__name__} and building the GLB file.")
            success = converter.convert(
                source_path,
                output_path,
                color=payload.get("color") if payload.get("use_color") else None,
            )
        if not success or not os.path.isfile(output_path):
            errors = getattr(converter, "errors", None) if converter else None
            raise RuntimeError("Conversion failed" + (f": {errors[-1]}" if errors else ""))
        self._assert_not_empty_output(output_path)

        if extension in {".glb", ".gltf"} and payload.get("max_dimension") is not None:
            report(68, "Scaling model", "Applying the requested maximum dimension limit.")
            self._limit_dimension(output_path, float(payload["max_dimension"]))

        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Processed file missing or empty")

        try:
            report(78, "Normalizing pivot", "Centering the model for predictable rotation and viewing.")
            gltf = normalize_model_to_center(GLTF2().load(output_path))
            gltf.save(output_path)
        except Exception as exc:
            logger.warning("Pivot normalization skipped for %s: %s", output_path, exc)

        warnings = []
        try:
            report(84, "Checking materials", "Embedding textures and validating material settings.")
            search_dirs = [os.path.dirname(output_path), payload.get("temp_dir")]
            warnings = finalize_glb(output_path, search_dirs=[item for item in search_dirs if item])
        except Exception as exc:
            logger.warning("GLB quality pass skipped for %s: %s", output_path, exc)
            warnings.append(f"Quality pass failed: {exc}")
        try:
            asset_report = self.asset_quality.inspect(output_path, warnings)
        except Exception as exc:
            asset_report = {"valid": False, "warnings": [f"Inspection failed: {exc}"]}

        # Measure dimensions HERE, on the uncompressed geometry, before the
        # compression step below. Measuring after meshopt compression is
        # unreliable: KHR_mesh_quantization stores positions as integers with
        # the dequantization scale in the node transform, so naive vertex
        # reads report quantized-space extents (tens of km). dump(concatenate)
        # bakes node transforms → real-world coordinates.
        dimensions_cm = self._measure_dimensions_cm(output_path)

        # Compression MUST be the last GLB-modifying step. gltfpack's meshopt/
        # draco output is only decodable by model-viewer's own decoder; any
        # later pygltflib save (normalize/finalize) or trimesh read corrupts
        # the compressed buffers ("buffer too short"), which is why this used
        # to run before normalize/finalize and produced broken, unmeasurable,
        # unsliceable models. Everything above ran on uncompressed geometry;
        # compress now, and nothing else touches the file afterward.
        report(90, "Optimizing GLB", "Checking compression and viewer compatibility.")
        compression = payload.get("compression")
        optimize_glb(
            output_path,
            enabled=None if compression is None else compression in {"meshopt", "draco"},
            mode=compression if compression in {"meshopt", "draco"} else "meshopt",
        )
        if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
            raise RuntimeError("Processed file missing or empty")

        # Unit actually applied to unitless input ("auto" resolves to the
        # detected one); None for formats that carry their own units.
        resolved_unit = (
            getattr(converter, "source_unit", None)
            if extension in {".obj", ".stl"} else None
        )
        return {
            "converter": converter,
            "source_unit": resolved_unit,
            "file_size": os.path.getsize(output_path),
            "quality_warnings": warnings,
            "asset_report": asset_report,
            "dimensions_cm": dimensions_cm,
        }

    @staticmethod
    def _measure_dimensions_cm(glb_path):
        """AABB extents in cm from node-transform-baked geometry, or None.
        Uses dump(concatenate=True) so node transforms (incl. any scale) are
        applied — a naive per-geometry vertex read would miss them."""
        try:
            loaded = trimesh.load(glb_path, force="scene")
            if isinstance(loaded, trimesh.Scene):
                combined = loaded.dump(concatenate=True)
            else:
                combined = loaded
            if combined is None or len(getattr(combined, "vertices", [])) == 0:
                return None
            bounds = combined.bounds
            if bounds is None:
                return None
            return ConversionService.dimensions_cm_from_extents(bounds[1] - bounds[0])
        except Exception as exc:
            logger.warning("Dimension measurement failed for %s: %s", glb_path, exc)
            return None
