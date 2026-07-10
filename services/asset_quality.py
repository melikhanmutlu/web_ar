import os

import trimesh
from pygltflib import GLTF2


class AssetQualityService:
    """Generate a stable, API-friendly quality report for a published GLB."""

    def __init__(self, *, warning_triangles=250_000, warning_bytes=25 * 1024 * 1024):
        self.warning_triangles = warning_triangles
        self.warning_bytes = warning_bytes

    def inspect(self, path, quality_warnings=()):
        size = os.path.getsize(path)
        gltf = GLTF2().load(path)
        scene = trimesh.load(path, force="scene")
        geometries = list(scene.geometry.values()) if isinstance(scene, trimesh.Scene) else [scene]
        vertices = sum(len(mesh.vertices) for mesh in geometries)
        triangles = sum(len(mesh.faces) for mesh in geometries)
        external_images = [
            image.uri for image in (gltf.images or [])
            if image.uri and not image.uri.startswith("data:")
        ]
        warnings = list(quality_warnings or [])
        if triangles > self.warning_triangles:
            warnings.append(
                f"Triangle budget exceeded: {triangles:,} > {self.warning_triangles:,}"
            )
        if size > self.warning_bytes:
            warnings.append(
                f"File budget exceeded: {size / 1024 / 1024:.1f}MB > {self.warning_bytes / 1024 / 1024:.1f}MB"
            )
        if external_images:
            warnings.append("External texture references remain")
        return {
            "valid": not quality_warnings and not external_images,
            "file_size_bytes": size,
            "vertices": vertices,
            "triangles": triangles,
            "meshes": len(gltf.meshes or []),
            "materials": len(gltf.materials or []),
            "textures": len(gltf.textures or []),
            "animations": len(gltf.animations or []),
            "extensions_used": list(gltf.extensionsUsed or []),
            "external_images": external_images,
            "warnings": warnings,
            "budgets": {
                "warning_triangles": self.warning_triangles,
                "warning_bytes": self.warning_bytes,
            },
        }
