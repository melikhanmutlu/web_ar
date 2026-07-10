import logging
import os
import shutil

import trimesh
from pygltflib import GLTF2

from converters import FBXConverter, OBJConverter, STLConverter
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

        report(72, "Optimizing GLB", "Checking compression and viewer compatibility.")
        compression = payload.get("compression")
        optimize_glb(
            output_path,
            enabled=None if compression is None else compression in {"meshopt", "draco"},
            mode=compression if compression in {"meshopt", "draco"} else "meshopt",
        )
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
        return {
            "converter": converter,
            "file_size": os.path.getsize(output_path),
            "quality_warnings": warnings,
            "asset_report": asset_report,
        }
