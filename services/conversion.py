import logging
import os
import shutil

import trimesh
from pygltflib import GLTF2

from converters import FBXConverter, OBJConverter, STLConverter, STEPConverter
from converters.glb_optimizer import optimize_glb
from converters.glb_quality import finalize_glb
from glb_modifier import normalize_model_to_center

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
            converter.set_source_unit(payload.get("source_unit") or "m")
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
    def _copy_or_pack_gltf(source_path, output_path, extension):
        if extension == ".glb":
            shutil.copy2(source_path, output_path)
        else:
            trimesh.load(source_path).export(output_path, file_type="glb")

    @staticmethod
    def _limit_dimension(path, maximum):
        mesh = trimesh.load(path)
        bounds = mesh.bounds
        current = float(max(bounds[1] - bounds[0]))
        if current > maximum and current > 0:
            mesh.apply_scale(maximum / current)
            mesh.export(path)

    def convert(self, payload, output_path, *, progress=None):
        report = progress or (lambda *_: None)
        extension = payload["file_extension"]
        source_path = payload["temp_file_path"]
        converter = self._converter(payload)
        report(48, "Reading source", f"Inspecting {payload['original_filename']} and conversion options.")

        if extension in {".glb", ".gltf"}:
            report(56, "Preparing GLB", "Copying or repacking the uploaded glTF asset.")
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

        return {
            "converter": converter,
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
            ext = bounds[1] - bounds[0]
            if float(max(ext)) <= 0.001:
                return None
            return {
                "x": round(float(ext[0]) * 100, 2),
                "y": round(float(ext[1]) * 100, 2),
                "z": round(float(ext[2]) * 100, 2),
                "max": round(float(max(ext)) * 100, 2),
            }
        except Exception as exc:
            logger.warning("Dimension measurement failed for %s: %s", glb_path, exc)
            return None
