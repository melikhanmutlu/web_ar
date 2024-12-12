"""
FBX format to GLB format conversion operations using FBX2glTF.
"""
import os
import subprocess
import logging
import json
import trimesh
from pygltflib import GLTF2
from .utils import scale_model
from .base_converter import BaseConverter
from .utils.file_utils import ensure_directory

logger = logging.getLogger(__name__)

class FBXConverter(BaseConverter):
    """Converter for FBX files to GLB format using FBX2glTF."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {'.fbx'}
        # Path to FBX2glTF executable in tools directory
        self.fbx2gltf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools', 'FBX2glTF.exe')
        
    def validate(self, file_path: str) -> bool:
        """Validate if the file exists and has .fbx extension."""
        if not super().validate(file_path):
            return False
            
        if not os.path.exists(file_path):
            self.handle_error("File does not exist")
            return False
            
        if not os.path.exists(self.fbx2gltf_path):
            self.handle_error(f"FBX2glTF not found at path: {self.fbx2gltf_path}")
            return False
            
        return True

    def convert(self, input_path: str, output_path: str, color: str = None) -> bool:
        """Convert FBX to GLB format with optional color."""
        try:
            self.update_status("CONVERTING")
            self.log_operation(f"Converting FBX file with color: {color}")
            
            # Create output directory
            ensure_directory(os.path.dirname(output_path))
            
            # First convert to GLB
            temp_glb = output_path.replace('.glb', '_temp.glb')
            
            # Convert FBX to GLB
            cmd = [
                self.fbx2gltf_path,
                '--binary',
                '--input', input_path,
                '--output', temp_glb
            ]
            
            self.log_operation(f"Running FBX2glTF command: {' '.join(cmd)}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                self.handle_error(f"FBX2glTF conversion failed: {stderr.decode()}")
                return False
                
            if not os.path.exists(temp_glb):
                self.handle_error("GLB file was not created")
                return False
                
            # Load the GLB with trimesh for scaling
            mesh = trimesh.load(temp_glb)
            
            # Scale the model if necessary
            mesh = scale_model(mesh)
            
            # Save the scaled model
            mesh.export(output_path)
            
            # Clean up temporary file
            if os.path.exists(temp_glb):
                os.remove(temp_glb)
                
            # If color is specified, modify the GLB file
            if color:
                try:
                    # Convert hex color to RGB
                    if color.startswith('#'):
                        color = color[1:]
                    r = int(color[0:2], 16) / 255.0
                    g = int(color[2:4], 16) / 255.0
                    b = int(color[4:6], 16) / 255.0
                    
                    # Load GLB file
                    glb = GLTF2().load(output_path)
                    
                    # Create new material
                    material = {
                        "pbrMetallicRoughness": {
                            "baseColorFactor": [r, g, b, 1.0],
                            "metallicFactor": 0.0,
                            "roughnessFactor": 1.0
                        }
                    }
                    
                    # Add material if not exists
                    if not hasattr(glb, 'materials') or not glb.materials:
                        glb.materials = []
                    material_index = len(glb.materials)
                    glb.materials.append(material)
                    
                    # Apply material to all meshes
                    if hasattr(glb, 'meshes'):
                        for mesh in glb.meshes:
                            if hasattr(mesh, 'primitives'):
                                for primitive in mesh.primitives:
                                    primitive.material = material_index
                    
                    # Save modified GLB
                    glb.save(output_path)
                    self.log_operation(f"Applied color #{color} to GLB")
                    
                except Exception as e:
                    self.handle_error(f"Error applying color: {str(e)}")
                    
            self.log_operation("FBX file converted successfully")
            return True

        except Exception as e:
            self.handle_error(f"FBX conversion error: {str(e)}")
            return False
            
    def handle_error(self, error_message: str) -> None:
        """
        Handle and log error messages
        Args:
            error_message: Error message to be logged
        """
        self.update_status("ERROR")
        self.log_operation(f"Error during conversion: {error_message}")
