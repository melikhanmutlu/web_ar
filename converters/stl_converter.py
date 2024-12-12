"""
STL format to GLB format conversion operations using trimesh.
"""
import os
import logging
import trimesh
import numpy as np
from pygltflib import GLTF2
from .base_converter import BaseConverter
from .utils.file_utils import ensure_directory
from .utils import scale_model

logger = logging.getLogger(__name__)

class STLConverter(BaseConverter):
    """Converter for STL files to GLB format using trimesh."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {'.stl'}
        
    def validate(self, file_path: str) -> bool:
        """
        Validate STL file
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
            
        try:
            # Try to load the STL file to validate it
            mesh = trimesh.load(file_path)
            if not isinstance(mesh, (trimesh.Trimesh, trimesh.Scene)):
                self.handle_error("Invalid STL file format")
                return False
        except Exception as e:
            self.handle_error(f"Error validating STL file: {str(e)}")
            return False
            
        return True
        
    def convert(self, input_path: str, output_path: str, color: str = None) -> bool:
        """
        Convert STL file to GLB format using trimesh
        Args:
            input_path: Path of the STL file to be converted
            output_path: Path of the output GLB file
            color: Optional color to apply to the mesh
        Returns:
            bool: Was the conversion successful
        """
        try:
            self.update_status("CONVERTING")
            self.log_operation("Starting STL to GLB conversion")
            
            # Create output directory
            ensure_directory(os.path.dirname(output_path))
            
            # Load the STL file
            mesh = trimesh.load(input_path)
            
            # Scale the model if necessary
            mesh = scale_model(mesh)
            
            # Apply color if specified
            if color:
                try:
                    # Convert hex color to RGB
                    if color.startswith('#'):
                        color = color[1:]
                    r = int(color[0:2], 16) / 255.0
                    g = int(color[2:4], 16) / 255.0
                    b = int(color[4:6], 16) / 255.0
                    
                    # Create vertex colors array (normalized RGB values)
                    vertex_colors = np.tile([r, g, b, 1.0], (len(mesh.vertices), 1))
                    mesh.visual.vertex_colors = vertex_colors
                    
                    self.log_operation(f"Applied color #{color} to mesh")
                except Exception as e:
                    self.handle_error(f"Error applying color: {str(e)}")

            # Convert to scene if it's a single mesh
            if isinstance(mesh, trimesh.Trimesh):
                scene = trimesh.Scene([mesh])
            else:
                scene = mesh
                
            # Export as GLB
            self.log_operation("Exporting to GLB format")
            scene.export(output_path)
            
            if not os.path.exists(output_path):
                self.handle_error("Output file was not created")
                return False
                
            self.log_operation("STL file converted successfully")
            return True
            
        except Exception as e:
            self.handle_error(f"Error during conversion: {str(e)}")
            return False
            
    def handle_error(self, error_message: str) -> None:
        """
        Handle and log error messages
        Args:
            error_message: Error message to be logged
        """
        self.update_status("ERROR")
        self.log_operation(f"Error during conversion: {error_message}")
