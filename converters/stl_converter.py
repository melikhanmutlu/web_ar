"""
STL format to GLB format conversion operations using trimesh.
"""
import os
import logging
import trimesh
import numpy as np
from .base_converter import BaseConverter
from .utils.file_utils import ensure_directory

logger = logging.getLogger(__name__)

class STLConverter(BaseConverter):
    """Converter for STL files to GLB format using trimesh."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {'.stl'}
        self.logger = logging.getLogger(__name__)
        
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
            self.log_operation(f"Input: {input_path}")
            self.log_operation(f"Output: {output_path}")
            
            # Create output directory
            ensure_directory(os.path.dirname(output_path))
            
            # Load the STL file
            self.log_operation("Loading STL file...")
            mesh = trimesh.load(input_path)
            
            if not isinstance(mesh, (trimesh.Trimesh, trimesh.Scene)):
                self.handle_error(f"Invalid mesh type: {type(mesh)}")
                return False
            
            # Get model dimensions
            if isinstance(mesh, trimesh.Scene):
                bounds = mesh.bounds
                extents = bounds[1] - bounds[0]
            else:
                extents = mesh.extents
            
            dimensions = {
                'x': extents[0],
                'y': extents[1],
                'z': extents[2]
            }
            
            self.log_operation(f"Model dimensions: {dimensions}")
            
            # Calculate scale factor
            scale_factor = self.calculate_scale_factor(dimensions)
            
            # ALWAYS apply scaling if max_dimension is set (standardize for AR)
            if self.max_dimension > 0:
                self.log_operation(f"Applying scale factor: {scale_factor}")
                if isinstance(mesh, trimesh.Scene):
                    for geom in mesh.geometry.values():
                        if isinstance(geom, trimesh.Trimesh):
                            geom.apply_scale(scale_factor)
                else:
                    mesh.apply_scale(scale_factor)
            
            # Apply color if specified
            if color:
                try:
                    self.log_operation(f"Applying color: {color}")
                    # Convert hex color to RGB (0-255 range)
                    hex_color = color.lstrip('#')
                    if len(hex_color) != 6:
                        raise ValueError(f"Invalid hex color: {color}")
                    
                    r = int(hex_color[0:2], 16)
                    g = int(hex_color[2:4], 16)
                    b = int(hex_color[4:6], 16)
                    
                    # Create PBR material with the specified color
                    material = trimesh.visual.material.PBRMaterial(
                        baseColorFactor=[r/255.0, g/255.0, b/255.0, 1.0],
                        metallicFactor=0.1,
                        roughnessFactor=0.9
                    )
                    
                    # Apply color to all meshes
                    if isinstance(mesh, trimesh.Scene):
                        for geom in mesh.geometry.values():
                            if isinstance(geom, trimesh.Trimesh):
                                # Apply both material and vertex colors for maximum compatibility
                                geom.visual = trimesh.visual.TextureVisuals(material=material)
                                vertex_colors = np.tile([r, g, b, 255], (len(geom.vertices), 1))
                                geom.visual.vertex_colors = vertex_colors.astype(np.uint8)
                    else:
                        # Apply both material and vertex colors for maximum compatibility
                        mesh.visual = trimesh.visual.TextureVisuals(material=material)
                        vertex_colors = np.tile([r, g, b, 255], (len(mesh.vertices), 1))
                        mesh.visual.vertex_colors = vertex_colors.astype(np.uint8)
                    
                    self.log_operation(f"Color applied successfully: RGB({r}, {g}, {b})")
                except Exception as e:
                    self.log_operation(f"Warning: Could not apply color: {str(e)}", "WARNING")
                    import traceback
                    self.log_operation(f"Traceback: {traceback.format_exc()}")
                    # Continue even if color application fails
            else:
                # No color specified - apply default gray material to ensure visibility
                self.log_operation("No color specified - applying default gray material")
                try:
                    default_material = trimesh.visual.material.PBRMaterial(
                        baseColorFactor=[0.8, 0.8, 0.8, 1.0],  # Light gray
                        metallicFactor=0.1,
                        roughnessFactor=0.9
                    )
                    
                    if isinstance(mesh, trimesh.Scene):
                        for geom in mesh.geometry.values():
                            if isinstance(geom, trimesh.Trimesh):
                                geom.visual = trimesh.visual.TextureVisuals(material=default_material)
                    else:
                        mesh.visual = trimesh.visual.TextureVisuals(material=default_material)
                except Exception as e:
                    self.log_operation(f"Warning: Could not apply default material: {str(e)}", "WARNING")

            # Convert to scene if it's a single mesh
            if isinstance(mesh, trimesh.Trimesh):
                self.log_operation("Converting mesh to scene")
                scene = trimesh.Scene([mesh])
            else:
                scene = mesh
                
            # Export as GLB
            self.log_operation("Exporting to GLB format")
            scene.export(output_path)
            
            if not os.path.exists(output_path):
                self.handle_error("Output file was not created")
                return False
            
            file_size = os.path.getsize(output_path)
            self.log_operation(f"STL file converted successfully. Output size: {file_size} bytes")
            return True
            
        except Exception as e:
            self.handle_error(f"Error during conversion: {str(e)}")
            import traceback
            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return False
            
    def handle_error(self, error_message: str) -> None:
        """
        Handle and log error messages
        Args:
            error_message: Error message to be logged
        """
        self.update_status("ERROR")
        self.log_operation(f"Error during conversion: {error_message}")
