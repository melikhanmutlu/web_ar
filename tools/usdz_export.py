"""Blender batch script: GLB -> USDZ for iOS Quick Look.

Usage (invoked by webar.conversion.export_usdz):
    blender --background --factory-startup --python tools/usdz_export.py \
        -- input.glb output.usdz
"""

import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

# Blender packages USD into .usdz automatically when the extension is .usdz.
bpy.ops.wm.usd_export(
    filepath=dst,
    export_materials=True,
    export_textures=True,
    selected_objects_only=False,
)
