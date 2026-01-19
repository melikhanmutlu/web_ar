"""
OBJ format to GLB format conversion operations.
"""
import os
import subprocess
import logging
import trimesh
import numpy as np
import platform
import shutil
from typing import Optional, List
from .base_converter import BaseConverter
from .utils.file_utils import ensure_directory, safe_delete_file
from .utils.validation import is_valid_extension

class OBJConverter(BaseConverter):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(__name__)
        self.supported_extensions = {'.obj'}
        
        # Platform-aware npx path
        if platform.system() == 'Windows':
            self.npx_path = r"C:\Program Files\nodejs\npx.cmd"
        else:
            # Linux/Mac - use npx from PATH
            npx_location = shutil.which('npx')
            self.npx_path = npx_location if npx_location else 'npx'
        
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

    def convert(self, input_path: str, output_path: str, color: Optional[str] = None) -> bool:
        """
        Convert OBJ file to GLB format
        Args:
            input_path: Path of the OBJ file to be converted
            output_path: Path of the output GLB file
            color: Optional hex color to apply to the model
        Returns:
            bool: Was the conversion successful
        """
        temp_input = None
        try:
            self.update_status("CONVERTING")
            self.log_operation(f"Starting OBJ to GLB conversion")
            self.log_operation(f"Input: {input_path}")
            self.log_operation(f"Output: {output_path}")
            
            # Create output directory
            ensure_directory(os.path.dirname(output_path))
            
            # Get the directory where the OBJ file is located
            obj_dir = os.path.dirname(input_path)
            obj_filename = os.path.basename(input_path)
            
            # Log MTL and texture files if present
            if self.mtl_file:
                self.log_operation(f"MTL file: {self.mtl_file}")
            if self.texture_files:
                self.log_operation(f"Texture files: {', '.join(self.texture_files)}")
            
            # obj2gltf automatically looks for MTL and textures in the same directory as the OBJ file
            # So we need to ensure all files are in the same directory
            
            # If color is specified, we'll apply it after conversion
            # Otherwise, use the original materials
            if color:
                self.log_operation(f"Color will be applied after conversion: {color}")
            
            # Prepare obj2gltf command
            cmd = [
                self.npx_path,
                'obj2gltf',
                '-i', input_path,
                '-o', output_path,
                '--checkTransparency',  # Handle transparent textures
                '--binary'  # Embed textures in GLB
            ]
            
            # Run the command
            self.log_operation(f"Running conversion command: {' '.join(cmd)}")
            result = subprocess.run(cmd, 
                                  capture_output=True, 
                                  text=True,
                                  cwd=obj_dir,  # Run in the OBJ directory
                                  timeout=300)  # 5 minute timeout
            
            # Log output
            if result.stdout:
                self.log_operation(f"obj2gltf stdout: {result.stdout}")
            if result.stderr:
                self.log_operation(f"obj2gltf stderr: {result.stderr}")
            
            # Check the result
            if result.returncode != 0:
                self.handle_error(f"Conversion failed (exit code {result.returncode}): {result.stderr}")
                return False
            
            # Verify output file exists
            if not os.path.exists(output_path):
                self.handle_error("Output GLB file was not created")
                return False
            
            # Post-processing: Apply color and/or scaling
            # BUT only if there are no textures (don't override textures with solid color)
            self.log_operation(f"Post-processing check - color: {color}, mtl_file: {self.mtl_file}, texture_files: {len(self.texture_files) if self.texture_files else 0}")
            
            # Determine if we need post-processing
            needs_color = color and not (self.mtl_file or self.texture_files)
            needs_scaling = False
            
            # Check if scaling is needed
            try:
                temp_mesh = trimesh.load(output_path)
                if isinstance(temp_mesh, trimesh.Scene):
                    bounds = temp_mesh.bounds
                    extents = bounds[1] - bounds[0]
                else:
                    extents = temp_mesh.extents
                
                dimensions = {'x': extents[0], 'y': extents[1], 'z': extents[2]}
                self.log_operation(f"Model dimensions: {dimensions}")
                
                # Only scale if max_dimension was explicitly set by user
                if self.max_dimension > 0:
                    scale_factor = self.calculate_scale_factor(dimensions)
                    if scale_factor != 1.0:
                        needs_scaling = True
                        self.log_operation(f"Scaling needed - factor: {scale_factor}")
                    else:
                        self.log_operation("No scaling needed - model already at target size")
                else:
                    self.log_operation("No scaling applied - max_dimension not set by user")
                
                del temp_mesh
            except Exception as e:
                self.log_operation(f"Warning: Could not check dimensions: {str(e)}", "WARNING")
            
            # Only reload and process if needed
            if needs_color or needs_scaling:
                try:
                    self.log_operation(f"Post-processing GLB - color: {needs_color}, scaling: {needs_scaling}")
                    mesh = trimesh.load(output_path)
                    
                    # Apply scaling first (if needed)
                    if needs_scaling:
                        if isinstance(mesh, trimesh.Scene):
                            bounds = mesh.bounds
                            extents = bounds[1] - bounds[0]
                        else:
                            extents = mesh.extents
                        
                        dimensions = {'x': extents[0], 'y': extents[1], 'z': extents[2]}
                        scale_factor = self.calculate_scale_factor(dimensions)
                        
                        # ALWAYS apply if max_dimension is set
                        if self.max_dimension > 0:
                            self.log_operation(f"Applying scale factor: {scale_factor}")
                            if isinstance(mesh, trimesh.Scene):
                                for geom in mesh.geometry.values():
                                    if isinstance(geom, trimesh.Trimesh):
                                        geom.apply_scale(scale_factor)
                            else:
                                mesh.apply_scale(scale_factor)
                    
                    # Apply color (if needed)
                    if needs_color:
                        # Convert hex color to RGB
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
                                    geom.visual = trimesh.visual.TextureVisuals(material=material)
                                    vertex_colors = np.tile([r, g, b, 255], (len(geom.vertices), 1))
                                    geom.visual.vertex_colors = vertex_colors.astype(np.uint8)
                        elif isinstance(mesh, trimesh.Trimesh):
                            mesh.visual = trimesh.visual.TextureVisuals(material=material)
                            vertex_colors = np.tile([r, g, b, 255], (len(mesh.vertices), 1))
                            mesh.visual.vertex_colors = vertex_colors.astype(np.uint8)
                        
                        self.log_operation(f"Color applied: RGB({r}, {g}, {b})")
                    
                    # Save the processed mesh (only once!)
                    mesh.export(output_path)
                    self.log_operation("Post-processing completed successfully")
                    
                except Exception as e:
                    self.log_operation(f"Warning: Post-processing failed: {str(e)}", "WARNING")
                    import traceback
                    self.log_operation(f"Traceback: {traceback.format_exc()}")
                    # Continue even if post-processing fails
            elif color and (self.mtl_file or self.texture_files):
                self.log_operation("Color not applied - textures detected, preserving original materials")
            else:
                # No post-processing needed
                self.log_operation("No post-processing needed - using original obj2gltf output")
                
            self.log_operation("OBJ file converted successfully")
            return True
            
        except subprocess.TimeoutExpired:
            self.handle_error("Conversion timed out after 5 minutes")
            return False
        except Exception as e:
            self.handle_error(f"Error during conversion: {str(e)}")
            import traceback
            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return False
        finally:
            # Don't cleanup MTL and texture files here - they're needed for conversion
            # They will be cleaned up when temp_dir is removed
            pass

    def calculate_scale_factor(self, dimensions: dict) -> float:
        """
        Calculate scale factor based on maximum dimension
        Args:
            dimensions: Dictionary containing x, y, z dimensions
        Returns:
            float: Scale factor to apply
        """
        return super().calculate_scale_factor(dimensions)

    def cleanup(self) -> None:
        """Clean up temporary files"""
        super().cleanup()
        
        # Note: MTL and texture files are NOT deleted here
        # They are in the temp_dir which will be cleaned up by the upload handler
        # This ensures they're available during the entire conversion process
        
        self.texture_files = []
        self.mtl_file = None

    def handle_error(self, error_message):
        self.update_status("ERROR")
        self.log_operation(f"Error during conversion: {error_message}")
