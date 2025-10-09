"""
FBX format to GLB format conversion operations using FBX2glTF.
"""
import os
import subprocess
import logging
import trimesh
import tempfile
import numpy as np
from pathlib import Path
from .base_converter import BaseConverter
from .utils.file_utils import ensure_directory

logger = logging.getLogger(__name__)

class FBXConverter(BaseConverter):
    """Converter for FBX files to GLB format using FBX2glTF."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {'.fbx'}
        self.fbx2gltf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools', 'FBX2glTF.exe')
        
    def validate(self, file_path: str) -> bool:
        """Validate if the file exists and has .fbx extension."""
        if not super().validate(file_path):
            return False
            
        if not os.path.exists(file_path):
            self.handle_error(f"File does not exist: {file_path}")
            return False
        
        file_ext = os.path.splitext(file_path)[1].lower()
        if file_ext not in self.supported_extensions:
            self.handle_error(f"Unsupported file format: {file_ext}")
            return False
            
        if not os.path.exists(self.fbx2gltf_path):
            self.handle_error(f"FBX2glTF not found at path: {self.fbx2gltf_path}")
            self.log_operation("Please ensure FBX2glTF.exe is in the tools directory")
            return False
            
        return True

    def calculate_scale_factor(self, mesh) -> float:
        """Calculate scale factor to fit model within maximum dimensions."""
        try:
            # Get the current dimensions
            extents = mesh.extents
            max_dimension = max(extents)
            
            # Calculate scale factor if needed
            if max_dimension > self.max_dimension:
                return self.max_dimension / max_dimension
                
            return 1.0
            
        except Exception as e:
            self.handle_error(f"Error calculating scale factor: {str(e)}")
            return 1.0

    def apply_color(self, mesh, color_str: str) -> trimesh.Trimesh:
        """Apply color to the mesh."""
        try:
            if not color_str:
                return mesh

            # Convert hex color to RGB (0-255 range)
            hex_color = color_str.lstrip('#')
            if len(hex_color) != 6:
                raise ValueError(f"Invalid hex color: {color_str}")
            
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            
            self.log_operation(f"Applying color RGB({r}, {g}, {b}) to mesh")
            
            # Create PBR material with the specified color
            material = trimesh.visual.material.PBRMaterial(
                baseColorFactor=[r/255.0, g/255.0, b/255.0, 1.0],
                metallicFactor=0.1,
                roughnessFactor=0.9
            )
            
            # Apply both material and vertex colors for maximum compatibility
            mesh.visual = trimesh.visual.TextureVisuals(material=material)
            vertex_colors = np.tile([r, g, b, 255], (len(mesh.vertices), 1))
            mesh.visual.vertex_colors = vertex_colors.astype(np.uint8)
            
            self.log_operation(f"Color applied successfully: RGB({r}, {g}, {b})")
            return mesh
            
        except Exception as e:
            self.handle_error(f"Error applying color: {str(e)}")
            import traceback
            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return mesh

    def convert(self, input_path: str, output_path: str, color: str = None) -> bool:
        """Convert FBX to GLB format."""
        try:
            self.update_status("CONVERTING")
            self.log_operation("Starting FBX conversion")
            
            # FIRST: Read original FBX dimensions before conversion using pyassimp
            original_dimensions = None
            try:
                import pyassimp
                from pyassimp import postprocess
                
                # Use context manager (with statement) for pyassimp
                with pyassimp.load(input_path, processing=postprocess.aiProcess_Triangulate) as scene:
                    self.log_operation(f"Scene type: {type(scene)}, has mMeshes: {hasattr(scene, 'mMeshes')}")
                    if hasattr(scene, 'mNumMeshes'):
                        self.log_operation(f"Number of meshes: {scene.mNumMeshes}")
                    all_vertices = []
                    all_faces = []
                    
                    # Try different pyassimp API approaches
                    # Approach 1: Direct meshes attribute (newer pyassimp)
                    if hasattr(scene, 'meshes') and scene.meshes:
                        self.log_operation(f"Using scene.meshes (found {len(scene.meshes)} meshes)")
                        for mesh in scene.meshes:
                            if hasattr(mesh, 'vertices') and len(mesh.vertices) > 0:
                                all_vertices.append(np.array(mesh.vertices))
                                self.log_operation(f"Added {len(mesh.vertices)} vertices from mesh")
                                
                                # Also collect faces (triangles)
                                if hasattr(mesh, 'faces') and len(mesh.faces) > 0:
                                    # Faces are stored as arrays of vertex indices
                                    mesh_faces = []
                                    for face in mesh.faces:
                                        if len(face) >= 3:  # Triangle or polygon
                                            # Convert to triangle indices
                                            mesh_faces.append([face[0], face[1], face[2]])
                                    if mesh_faces:
                                        all_faces.append(np.array(mesh_faces))
                                        self.log_operation(f"Added {len(mesh_faces)} faces from mesh")
                    # Approach 2: mMeshes ctypes array (older pyassimp)
                    elif hasattr(scene, 'mMeshes') and scene.mMeshes:
                        self.log_operation(f"Using scene.mMeshes (found {scene.mNumMeshes} meshes)")
                        for i in range(scene.mNumMeshes):
                            mesh = scene.mMeshes[i].contents
                            if hasattr(mesh, 'mVertices') and mesh.mNumVertices > 0:
                                vertices = np.array([[mesh.mVertices[j].x, mesh.mVertices[j].y, mesh.mVertices[j].z] 
                                                    for j in range(mesh.mNumVertices)])
                                all_vertices.append(vertices)
                                self.log_operation(f"Added {mesh.mNumVertices} vertices from mesh {i}")
                    
                    if all_vertices:
                        combined_vertices = np.vstack(all_vertices)
                        min_bounds = combined_vertices.min(axis=0)
                        max_bounds = combined_vertices.max(axis=0)
                        extents = max_bounds - min_bounds
                        
                        # Store original vertices for later use (in case GLB has zero vertices)
                        self._fbx_vertices = combined_vertices / 1000.0  # Convert mm to m
                        self.log_operation(f"Stored {len(combined_vertices)} original FBX vertices for mesh creation")
                        
                        # Store original faces if available
                        if all_faces:
                            # Combine all faces, adjusting indices for combined vertex array
                            combined_faces = []
                            vertex_offset = 0
                            for i, faces in enumerate(all_faces):
                                # Adjust face indices by vertex offset
                                adjusted_faces = faces + vertex_offset
                                combined_faces.append(adjusted_faces)
                                vertex_offset += len(all_vertices[i])
                            
                            self._fbx_faces = np.vstack(combined_faces)
                            self.log_operation(f"Stored {len(self._fbx_faces)} original FBX faces for mesh creation")
                        else:
                            self._fbx_faces = None
                            self.log_operation("No faces found in FBX, will use vertices only")
                        
                        if max(extents) > 0.001:
                            # FBX units are often in mm, convert to meters
                            # Divide by 1000 to get meters (pyassimp reads raw units)
                            extents_m = extents / 1000.0
                            
                            # Store in meters (app.py will convert to cm)
                            original_dimensions = {
                                'x': float(extents_m[0]),
                                'y': float(extents_m[1]),
                                'z': float(extents_m[2]),
                                'max': float(max(extents_m))
                            }
                            self.log_operation(f"Original FBX dimensions (raw units): {extents}")
                            self.log_operation(f"Original FBX dimensions (m, assuming mm units): {extents_m}")
                            self.log_operation(f"Will be converted to cm in app.py: {extents_m * 100}")
                        else:
                            self.log_operation(f"Warning: Original FBX has zero dimensions: {extents}")
                    else:
                        self.log_operation("Warning: No vertices found in FBX file")
                        self._fbx_vertices = None
            except Exception as e:
                import traceback
                self.log_operation(f"Warning: Could not read original FBX dimensions with pyassimp: {str(e)}", "WARNING")
                self.log_operation(f"Traceback: {traceback.format_exc()}")
            
            # Store dimensions for later use
            self.original_dimensions = original_dimensions
            
            # Create output directory
            ensure_directory(os.path.dirname(output_path))
            
            # Create a temporary directory for intermediate files
            with tempfile.TemporaryDirectory() as temp_dir:
                try:
                    # First convert FBX to GLB using FBX2glTF
                    cmd = [
                        str(self.fbx2gltf_path),
                        '--binary',
                        '--input', str(input_path),
                        '--output', str(output_path)
                    ]
                    
                    # Add draco compression only if no color is specified
                    # (draco can interfere with color application)
                    if not color:
                        cmd.append('--draco')
                    
                    self.log_operation(f"Running command: {' '.join(cmd)}")
                    result = subprocess.run(cmd, 
                                         capture_output=True, 
                                         text=True, 
                                         check=False,
                                         timeout=300)  # 5 minute timeout
                    
                    # Check conversion result
                    if result.returncode != 0:
                        error_msg = f"FBX2glTF conversion failed (exit code {result.returncode})\n"
                        error_msg += f"STDERR: {result.stderr}\n"
                        error_msg += f"STDOUT: {result.stdout}"
                        self.handle_error(error_msg)
                        return False
                    
                    self.log_operation(f"FBX2glTF output: {result.stdout}")
                    
                    # Post-processing: ALWAYS needed for FBX (to fix vertex issues from FBX2glTF)
                    self.log_operation(f"Post-processing - color: {color}")
                    
                    # Check if we need post-processing
                    # For FBX, ALWAYS do post-processing (FBX2glTF often produces GLB with zero vertices)
                    needs_processing = True
                    self.log_operation("Post-processing needed: FBX requires concatenation to fix vertex issues")
                    
                    if color:
                        self.log_operation("Post-processing needed: color application")
                    
                    # For FBX, check scaling using original dimensions (GLB may have zero vertices)
                    if original_dimensions and self.max_dimension > 0:
                        max_dim_m = original_dimensions['max']
                        max_allowed_m = self.max_dimension
                        # ALWAYS scale if max_dimension is set (both up and down)
                        scale_factor = max_allowed_m / max_dim_m
                        if scale_factor != 1.0:
                            needs_processing = True
                            self.log_operation(f"Post-processing needed: scaling from original FBX dims (factor: {scale_factor:.4f})")
                            self.log_operation(f"Original max: {max_dim_m:.4f}m, Target: {max_allowed_m:.4f}m")
                    
                    # Check if scaling is needed (fallback for non-FBX or if original_dimensions failed)
                    if os.path.exists(output_path):
                        try:
                            # Quick check for dimensions without full reload
                            temp_mesh = trimesh.load(output_path)
                            if isinstance(temp_mesh, trimesh.Scene):
                                # For Scene, combine all vertices for accurate bounds
                                all_vertices = []
                                for geom in temp_mesh.geometry.values():
                                    if isinstance(geom, trimesh.Trimesh):
                                        all_vertices.append(geom.vertices)
                                
                                if all_vertices:
                                    combined_vertices = np.vstack(all_vertices)
                                    min_bounds = combined_vertices.min(axis=0)
                                    max_bounds = combined_vertices.max(axis=0)
                                    extents = max_bounds - min_bounds
                                else:
                                    bounds = temp_mesh.bounds
                                    extents = bounds[1] - bounds[0]
                            else:
                                extents = temp_mesh.extents
                            
                            dimensions = {'x': extents[0], 'y': extents[1], 'z': extents[2]}
                            scale_factor = super().calculate_scale_factor(dimensions)
                            
                            # Always apply scaling if max_dimension is set (standardize for AR)
                            if self.max_dimension > 0 and scale_factor != 1.0:
                                needs_processing = True
                                self.log_operation(f"Post-processing needed: scaling (factor: {scale_factor})")
                            
                            del temp_mesh  # Free memory
                            
                        except Exception as e:
                            self.log_operation(f"Warning: Could not check dimensions: {str(e)}", "WARNING")
                    
                    # Only reload and re-export if necessary
                    if needs_processing and os.path.exists(output_path):
                        try:
                            mesh = trimesh.load(output_path)
                            self.log_operation(f"Loaded GLB for post-processing")
                            
                            # For FBX, GLB from FBX2glTF often has zero vertices
                            # Use original FBX vertices to create proper mesh
                            if isinstance(mesh, trimesh.Scene) and original_dimensions:
                                try:
                                    # GLB has zero vertices, create mesh from original FBX data
                                    self.log_operation("GLB has zero vertices, creating mesh from original FBX vertices")
                                    
                                    # Get vertices and faces from original FBX (already stored during dimension reading)
                                    if hasattr(self, '_fbx_vertices') and self._fbx_vertices is not None:
                                        # Create new mesh from original vertices and faces
                                        if hasattr(self, '_fbx_faces') and self._fbx_faces is not None:
                                            mesh = trimesh.Trimesh(vertices=self._fbx_vertices, faces=self._fbx_faces)
                                            self.log_operation(f"Created mesh from original FBX ({len(mesh.vertices)} vertices, {len(mesh.faces)} faces)")
                                        else:
                                            # Fallback: vertices only (trimesh will try to create faces)
                                            mesh = trimesh.Trimesh(vertices=self._fbx_vertices)
                                            self.log_operation(f"Created mesh from original FBX vertices only ({len(mesh.vertices)} vertices, no faces)")
                                    else:
                                        # Fallback: try concatenate
                                        self.log_operation("No original vertices stored, trying concatenate")
                                        mesh = mesh.dump(concatenate=True)
                                        self.log_operation(f"Concatenated to single mesh ({len(mesh.vertices)} vertices)")
                                except Exception as concat_error:
                                    self.log_operation(f"Warning: Could not create mesh from FBX: {concat_error}", "WARNING")
                                    # Final fallback
                                    try:
                                        mesh = mesh.dump(concatenate=True)
                                        self.log_operation(f"Fallback concatenated mesh ({len(mesh.vertices)} vertices)")
                                    except:
                                        self.log_operation("ERROR: All mesh creation methods failed!", "ERROR")
                            
                            # Apply scaling if needed
                            # For FBX, use original dimensions
                            if original_dimensions and self.max_dimension > 0:
                                max_dim_m = original_dimensions['max']
                                max_allowed_m = self.max_dimension
                                # ALWAYS scale to target (both up and down)
                                scale_factor = max_allowed_m / max_dim_m
                                self.log_operation(f"Applying scale factor from original FBX: {scale_factor:.4f}")
                                
                                # Debug: Check bounds before scaling
                                bounds_before = mesh.bounds
                                if bounds_before is not None:
                                    extents_before = bounds_before[1] - bounds_before[0]
                                    self.log_operation(f"Bounds before scaling: {bounds_before}")
                                    self.log_operation(f"Extents before scaling: {extents_before}")
                                else:
                                    self.log_operation("Bounds before scaling: None (will be calculated after scaling)")
                                    extents_before = None
                                
                                mesh.apply_scale(scale_factor)
                                
                                # Debug: Check bounds after scaling
                                bounds_after = mesh.bounds
                                if bounds_after is not None:
                                    extents_after = bounds_after[1] - bounds_after[0]
                                    self.log_operation(f"Bounds after scaling: {bounds_after}")
                                    self.log_operation(f"Extents after scaling: {extents_after}")
                                    if extents_before is not None:
                                        self.log_operation(f"Expected extents: {extents_before * scale_factor}")
                                else:
                                    self.log_operation("Bounds after scaling: None")
                            else:
                                # Fallback: try to get dimensions from GLB
                                if isinstance(mesh, trimesh.Scene):
                                    # For Scene, combine all vertices for accurate bounds
                                    all_vertices = []
                                    for geom in mesh.geometry.values():
                                        if isinstance(geom, trimesh.Trimesh):
                                            all_vertices.append(geom.vertices)
                                    
                                    if all_vertices:
                                        combined_vertices = np.vstack(all_vertices)
                                        min_bounds = combined_vertices.min(axis=0)
                                        max_bounds = combined_vertices.max(axis=0)
                                        extents = max_bounds - min_bounds
                                    else:
                                        bounds = mesh.bounds
                                        extents = bounds[1] - bounds[0]
                                    
                                    dimensions = {'x': extents[0], 'y': extents[1], 'z': extents[2]}
                                    scale_factor = super().calculate_scale_factor(dimensions)
                                    
                                    # ALWAYS apply if max_dimension is set
                                    if self.max_dimension > 0:
                                        self.log_operation(f"Applying scale factor from GLB: {scale_factor}")
                                        for geom in mesh.geometry.values():
                                            if isinstance(geom, trimesh.Trimesh):
                                                geom.apply_scale(scale_factor)
                                elif isinstance(mesh, trimesh.Trimesh):
                                    extents = mesh.extents
                                    dimensions = {'x': extents[0], 'y': extents[1], 'z': extents[2]}
                                    scale_factor = super().calculate_scale_factor(dimensions)
                                    
                                    # ALWAYS apply if max_dimension is set
                                    if self.max_dimension > 0:
                                        self.log_operation(f"Applying scale factor: {scale_factor}")
                                        mesh.apply_scale(scale_factor)
                            
                            # Apply color (use default gray if not specified)
                            # apply_color() MUST be called for GLB export to work properly!
                            if not color:
                                self.log_operation("No color specified, using default gray #CCCCCC for GLB export")
                                color = '#CCCCCC'  # Light gray
                            
                            self.log_operation(f"Applying color: {color}")
                            self.apply_color(mesh, color)
                            
                            # Save the processed mesh back to GLB
                            # At this point, mesh is always Trimesh (concatenated if it was Scene)
                            try:
                                self.log_operation(f"Exporting mesh to: {output_path}")
                                self.log_operation(f"Mesh type before export: {type(mesh)}")
                                vertex_count = len(mesh.vertices) if hasattr(mesh, 'vertices') else 0
                                self.log_operation(f"Vertex count before export: {vertex_count}")
                                
                                # Delete old file first to ensure clean write
                                if os.path.exists(output_path):
                                    os.remove(output_path)
                                    self.log_operation(f"Deleted old GLB file")
                                
                                # Export as GLB using direct mesh export
                                mesh.export(output_path, file_type='glb')
                                self.log_operation(f"Exported using mesh.export(file_type='glb')")
                                
                                # Verify file was written
                                if os.path.exists(output_path):
                                    file_size = os.path.getsize(output_path)
                                    self.log_operation(f"Successfully saved processed mesh to GLB ({vertex_count} vertices, {file_size} bytes)")
                                else:
                                    self.log_operation("ERROR: Export completed but file does not exist!", "ERROR")
                            except Exception as export_error:
                                self.log_operation(f"ERROR exporting mesh: {export_error}", "ERROR")
                                import traceback
                                self.log_operation(f"Export traceback: {traceback.format_exc()}")
                            
                        except Exception as e:
                            self.handle_error(f"Error post-processing GLB: {str(e)}")
                            import traceback
                            self.log_operation(f"Traceback: {traceback.format_exc()}")
                            # Continue even if post-processing fails
                    else:
                        self.log_operation("No post-processing needed - using original FBX2glTF output")
                    
                    # Verify output file exists
                    if not os.path.exists(output_path):
                        self.handle_error("GLB file was not created")
                        return False
                    
                    file_size = os.path.getsize(output_path)
                    self.log_operation(f"Conversion completed successfully. Output size: {file_size} bytes")
                    return True
                    
                except subprocess.TimeoutExpired:
                    self.handle_error("FBX conversion timed out after 5 minutes")
                    return False
                except Exception as e:
                    self.handle_error(f"Error during conversion: {str(e)}")
                    import traceback
                    self.log_operation(f"Traceback: {traceback.format_exc()}")
                    return False
                    
        except Exception as e:
            self.handle_error(f"Conversion failed: {str(e)}")
            import traceback
            self.log_operation(f"Traceback: {traceback.format_exc()}")
            return False

    def handle_error(self, error_message: str) -> None:
        """Handle and log error messages."""
        self.update_status("ERROR")
        logger.error(error_message)
        self.log_operation(f"Error: {error_message}")
