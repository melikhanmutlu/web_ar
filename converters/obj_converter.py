"""
OBJ format to GLB format conversion operations.
"""
import os
import subprocess
import logging
import trimesh
import shutil
from typing import Optional, List
from .base_converter import BaseConverter
from .utils.file_utils import ensure_directory, safe_delete_file
from .utils.validation import is_valid_extension
from .utils import scale_model

class OBJConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.supported_extensions = {'.obj'}
        self.npx_path = r"C:\Program Files\nodejs\npx.cmd"
        self.texture_files: List[str] = []
        self.mtl_file: Optional[str] = None

    def validate(self, file_path: str) -> bool:
        """
        Validate OBJ file
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

        return True

    def set_material_file(self, mtl_path: str) -> None:
        """
        Set MTL file
        Args:
            mtl_path: Path of the MTL file
        """
        if os.path.exists(mtl_path):
            self.mtl_file = mtl_path
            self.log_operation(f"MTL file set: {mtl_path}")

    def add_texture_file(self, texture_path: str) -> None:
        """
        Add texture file
        Args:
            texture_path: Path of the texture file
        """
        if os.path.exists(texture_path):
            self.texture_files.append(texture_path)
            self.log_operation(f"Texture file added: {texture_path}")

    def convert(self, input_path: str, output_path: str) -> bool:
        """
        Convert OBJ file to GLB format
        Args:
            input_path: Path of the OBJ file to be converted
            output_path: Path of the output GLB file
        Returns:
            bool: Was the conversion successful
        """
        try:
            self.update_status("CONVERTING")
            
            # Create output directory
            ensure_directory(os.path.dirname(output_path))
            
            # Convert OBJ to GLB with scaling
            if not self.convert_obj_to_glb(input_path, output_path):
                self.handle_error("OBJ to GLB conversion failed")
                return False
            
            self.log_operation("OBJ file converted successfully")
            return True
            
        except Exception as e:
            self.handle_error(f"Error during conversion: {str(e)}")
            return False
        finally:
            self.cleanup()

    def convert_obj_to_glb(self, obj_path, output_path):
        """Convert OBJ file to GLB format."""
        try:
            # First load with trimesh for scaling
            mesh = trimesh.load(obj_path)
            
            # Scale the model if necessary
            mesh = scale_model(mesh)
            
            # Save scaled OBJ temporarily
            temp_obj = obj_path + '.scaled.obj'
            mesh.export(temp_obj)
            
            # Convert scaled OBJ to GLB using obj2gltf
            result = subprocess.run(['obj2gltf', '-i', temp_obj, '-o', output_path], 
                                  capture_output=True, text=True)
            
            # Clean up temporary file
            if os.path.exists(temp_obj):
                os.remove(temp_obj)
                
            return result.returncode == 0
        except Exception as e:
            self.handle_error(f"Error converting OBJ to GLB: {str(e)}")
            return False

    def cleanup(self) -> None:
        """Clean up temporary files"""
        super().cleanup()
        
        # Clean up temporary texture files
        for texture_file in self.texture_files:
            if safe_delete_file(texture_file):
                self.log_operation(f"Texture file deleted: {texture_file}")
            
        # Clean up temporary MTL file
        if self.mtl_file and safe_delete_file(self.mtl_file):
            self.log_operation(f"MTL file deleted: {self.mtl_file}")
            
        self.texture_files = []
        self.mtl_file = None

    def handle_error(self, error_message):
        self.update_status("ERROR")
        self.log_operation(f"Error during conversion: {error_message}")
