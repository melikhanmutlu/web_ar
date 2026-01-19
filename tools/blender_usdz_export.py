import bpy
import sys
import os

def export_usdz(input_path, output_path):
    # Clear existing mesh objects
    bpy.ops.wm.read_factory_settings(use_empty=True)
    
    # Import the model based on extension
    ext = os.path.splitext(input_path)[1].lower()
    
    try:
        if ext == '.glb' or ext == '.gltf':
            bpy.ops.import_scene.gltf(filepath=input_path)
        elif ext == '.fbx':
            bpy.ops.import_scene.fbx(filepath=input_path, use_anim=True)
        elif ext == '.obj':
            bpy.ops.import_scene.obj(filepath=input_path)
        elif ext == '.stl':
            bpy.ops.import_mesh.stl(filepath=input_path)
        else:
            print(f"Unsupported file extension: {ext}")
            sys.exit(1)
            
        # Ensure output path ends with .usdz
        if not output_path.lower().endswith('.usdz'):
            output_path += '.usdz'
            
        print(f"Exporting to {output_path}...")
        
        # Select all objects
        bpy.ops.object.select_all(action='SELECT')
        
        # Export as USDZ
        # Blender 3.5+ supports .usdz extension directly in usd_export
        # Note: older versions might need 'usdc' or 'usda', but let's assume modern blender in nixpacks
        
        bpy.ops.wm.usd_export(
            filepath=output_path,
            selected_objects_only=False,
            export_animation=True,
            export_hair=False,
            export_uvmaps=True,
            export_normals=True,
            export_materials=True
        )
        
        print("Export successful.")
        
    except Exception as e:
        print(f"Error during conversion: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    # argv usually contains [--, arg1, arg2, ...]
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    else:
        # Fallback if -- is not used but arguments are passed
        pass
        
    if len(argv) < 2:
        print("Usage: blender --background --python script.py -- <input_file> <output_file>")
        # Don't exit here if running inside blender manually, but for automation we need args
        if "--" in sys.argv:
             sys.exit(1)
        else:
             print("Warning: No arguments found after --")

    if len(argv) >= 2:
        input_file = argv[0]
        output_file = argv[1]
        export_usdz(input_file, output_file)
