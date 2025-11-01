"""
FBX format to GLB format conversion operations using FBX2glTF.
"""
import os
import subprocess
import logging
import trimesh
import tempfile
import numpy as np
import platform
from pathlib import Path
from .base_converter import BaseConverter
from .utils.file_utils import ensure_directory

logger = logging.getLogger(__name__)

class FBXConverter(BaseConverter):
    """Converter for FBX files to GLB format using FBX2glTF."""
    
    def __init__(self):
        super().__init__()
        self.supported_extensions = {'.fbx'}
        
        # Platform-aware FBX2glTF path
        tools_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools')
        if platform.system() == 'Windows':
            self.fbx2gltf_path = os.path.join(tools_dir, 'FBX2glTF.exe')
        else:
            self.fbx2gltf_path = os.path.join(tools_dir, 'FBX2glTF')
        
        self.remove_textures = False  # Option to remove existing textures
        
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
            
            # Remove existing textures if requested
            if self.remove_textures:
                self.log_operation("Removing existing textures and applying solid color")
                mesh.visual = None
            
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
            
            self.log_operation(f"Solid color applied successfully: RGB({r}, {g}, {b})")
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
                    
                    # EXTRACT EMBEDDED TEXTURES
                    if hasattr(scene, 'textures') and scene.textures:
                        self.log_operation(f"Found {len(scene.textures)} embedded textures")
                        texture_dir = os.path.dirname(input_path)
                        
                        for idx, texture in enumerate(scene.textures):
                            try:
                                # Get texture data
                                if hasattr(texture, 'achFormatHint'):
                                    format_hint = texture.achFormatHint.decode('utf-8') if isinstance(texture.achFormatHint, bytes) else texture.achFormatHint
                                    ext = f".{format_hint}" if format_hint else ".png"
                                else:
                                    ext = ".png"
                                
                                # Save texture to file
                                texture_filename = f"texture_{idx}{ext}"
                                texture_path = os.path.join(texture_dir, texture_filename)
                                
                                if hasattr(texture, 'pcData') and texture.pcData:
                                    with open(texture_path, 'wb') as f:
                                        f.write(texture.pcData)
                                    self.log_operation(f"Extracted texture: {texture_filename}")
                            except Exception as tex_error:
                                self.log_operation(f"Warning: Could not extract texture {idx}: {tex_error}", "WARNING")
                    
                    all_vertices = []
                    all_faces = []
                    all_uvs = []  # Store UV coordinates
                    all_materials = []  # Store material info
                    
                    # Try different pyassimp API approaches
                    # Approach 1: Direct meshes attribute (newer pyassimp)
                    if hasattr(scene, 'meshes') and scene.meshes:
                        self.log_operation(f"Using scene.meshes (found {len(scene.meshes)} meshes)")
                        for mesh_idx, mesh in enumerate(scene.meshes):
                            if hasattr(mesh, 'vertices') and len(mesh.vertices) > 0:
                                all_vertices.append(np.array(mesh.vertices))
                                self.log_operation(f"Added {len(mesh.vertices)} vertices from mesh {mesh_idx}")
                                
                                # Collect UV coordinates (texture coordinates)
                                if hasattr(mesh, 'texturecoords') and mesh.texturecoords is not None:
                                    # texturecoords[0] is the first UV channel
                                    if len(mesh.texturecoords) > 0 and mesh.texturecoords[0] is not None:
                                        uvs = np.array(mesh.texturecoords[0])[:, :2]  # Take only U,V (ignore W)
                                        all_uvs.append(uvs)
                                        self.log_operation(f"Added {len(uvs)} UV coordinates from mesh {mesh_idx}")
                                    else:
                                        all_uvs.append(None)
                                else:
                                    all_uvs.append(None)
                                
                                # Collect material index
                                if hasattr(mesh, 'materialindex'):
                                    all_materials.append(mesh.materialindex)
                                    self.log_operation(f"Mesh {mesh_idx} uses material index: {mesh.materialindex}")
                                else:
                                    all_materials.append(None)
                                
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
                                        self.log_operation(f"Added {len(mesh_faces)} faces from mesh {mesh_idx}")
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
                        
                        # Store UV coordinates
                        if all_uvs and any(uv is not None for uv in all_uvs):
                            combined_uvs = []
                            for idx, uv in enumerate(all_uvs):
                                if uv is not None:
                                    combined_uvs.append(uv)
                                else:
                                    # If a mesh has no UVs, create dummy UVs
                                    combined_uvs.append(np.zeros((len(all_vertices[idx]), 2)))
                            
                            self._fbx_uvs = np.vstack(combined_uvs)
                            self.log_operation(f"Stored {len(self._fbx_uvs)} UV coordinates")
                        else:
                            self._fbx_uvs = None
                            self.log_operation("No UV coordinates found in FBX")
                        
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
                    # Use -i and -o parameters (based on working project)
                    # NOTE: Draco compression disabled - it corrupts textures and geometry
                    cmd = [
                        str(self.fbx2gltf_path),
                        '-i', str(input_path),
                        '-o', str(output_path),
                        '--binary'
                    ]
                    
                    self.log_operation(f"Running command: {' '.join(cmd)}")
                    result = subprocess.run(cmd, 
                                         capture_output=True, 
                                         text=True, 
                                         check=False,
                                         stdin=subprocess.DEVNULL,  # Don't wait for input
                                         timeout=300)  # 5 minute timeout
                    
                    # Check conversion result
                    if result.returncode != 0:
                        error_msg = f"FBX2glTF conversion failed (exit code {result.returncode})\n"
                        error_msg += f"STDERR: {result.stderr}\n"
                        error_msg += f"STDOUT: {result.stdout}"
                        self.handle_error(error_msg)
                        return False
                    
                    self.log_operation(f"FBX2glTF output: {result.stdout}")
                    
                    # Post-processing: Only if color or scaling needed
                    self.log_operation(f"Post-processing - color: {color}, max_dimension: {self.max_dimension}")
                    
                    # Check if we need post-processing
                    needs_processing = False
                    
                    # Check if color application needed
                    if color:
                        needs_processing = True
                        self.log_operation("Post-processing needed: color application")
                    
                    # Check if scaling needed
                    if original_dimensions and self.max_dimension > 0:
                        max_dim_m = original_dimensions['max']
                        max_allowed_m = self.max_dimension
                        scale_factor = max_allowed_m / max_dim_m
                        if scale_factor != 1.0:
                            needs_processing = True
                            self.log_operation(f"Post-processing needed: scaling from original FBX dims (factor: {scale_factor:.4f})")
                            self.log_operation(f"Original max: {max_dim_m:.4f}m, Target: {max_allowed_m:.4f}m")
                    
                    # If no post-processing needed, embed external textures into GLB
                    if not needs_processing:
                        self.log_operation("No post-processing needed - embedding external textures into GLB")
                        try:
                            self._embed_external_textures(output_path, input_path)
                        except Exception as tex_error:
                            self.log_operation(f"Warning: Could not embed textures: {tex_error}", "WARNING")
                        self.update_status("COMPLETED")
                        return True
                    
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
                            scene_or_mesh = trimesh.load(output_path)
                            self.log_operation(f"Loaded GLB for post-processing")
                            
                            # NEW APPROACH: Work with Scene directly to preserve textures
                            if isinstance(scene_or_mesh, trimesh.Scene):
                                self.log_operation("Processing Scene from FBX2glTF")
                                
                                # Check if scene has valid geometry (not all zeros)
                                has_valid_geometry = False
                                for name, geom in scene_or_mesh.geometry.items():
                                    if isinstance(geom, trimesh.Trimesh) and geom.bounds is not None:
                                        extents = geom.bounds[1] - geom.bounds[0]
                                        if np.any(extents > 0):
                                            has_valid_geometry = True
                                            break
                                
                                if not has_valid_geometry:
                                    self.log_operation("WARNING: FBX2glTF GLB has zero geometry - using original FBX data")
                                    # Use original FBX vertices instead
                                    if hasattr(self, '_fbx_vertices') and self._fbx_vertices is not None:
                                        if hasattr(self, '_fbx_faces') and self._fbx_faces is not None:
                                            mesh = trimesh.Trimesh(vertices=self._fbx_vertices, faces=self._fbx_faces)
                                            self.log_operation(f"Created mesh from original FBX: {len(mesh.vertices)} vertices")
                                            
                                            # Apply scaling
                                            if original_dimensions and self.max_dimension > 0:
                                                max_dim_m = original_dimensions['max']
                                                max_allowed_m = self.max_dimension
                                                scale_factor = max_allowed_m / max_dim_m
                                                self.log_operation(f"Applying scale factor {scale_factor:.4f}")
                                                mesh.apply_scale(scale_factor)
                                                
                                                extents = mesh.bounds[1] - mesh.bounds[0]
                                                self.log_operation(f"Mesh extents after scaling: {extents}")
                                            
                                            # Apply color if needed
                                            if color:
                                                self.apply_color(mesh, color)
                                            
                                            # Export
                                            self.log_operation(f"Exporting mesh to: {output_path}")
                                            if os.path.exists(output_path):
                                                os.remove(output_path)
                                            mesh.export(output_path, file_type='glb')
                                            
                                            if os.path.exists(output_path):
                                                file_size = os.path.getsize(output_path)
                                                self.log_operation(f"Mesh exported: {file_size} bytes")
                                            
                                            self.update_status("COMPLETED")
                                            return True
                                
                                # If scene has valid geometry, scale it
                                self.log_operation("Scene has valid geometry - applying scaling")
                                if original_dimensions and self.max_dimension > 0:
                                    max_dim_m = original_dimensions['max']
                                    max_allowed_m = self.max_dimension
                                    scale_factor = max_allowed_m / max_dim_m
                                    self.log_operation(f"Applying scale factor {scale_factor:.4f} to all scene geometries")
                                    
                                    for name, geom in scene_or_mesh.geometry.items():
                                        if isinstance(geom, trimesh.Trimesh):
                                            geom.apply_scale(scale_factor)
                                            self.log_operation(f"Scaled geometry '{name}': {len(geom.vertices)} vertices")
                                            # Log bounds after scaling
                                            if geom.bounds is not None:
                                                extents = geom.bounds[1] - geom.bounds[0]
                                                self.log_operation(f"  Extents after scaling: {extents}")
                                
                                # Apply color if requested
                                if color:
                                    self.log_operation("Removing textures and applying solid color to all geometries")
                                    # Convert hex to RGB
                                    hex_color = color.lstrip('#')
                                    r = int(hex_color[0:2], 16)
                                    g = int(hex_color[2:4], 16)
                                    b = int(hex_color[4:6], 16)
                                    
                                    material = trimesh.visual.material.PBRMaterial(
                                        baseColorFactor=[r/255.0, g/255.0, b/255.0, 1.0],
                                        metallicFactor=0.1,
                                        roughnessFactor=0.9
                                    )
                                    
                                    for name, geom in scene_or_mesh.geometry.items():
                                        if isinstance(geom, trimesh.Trimesh):
                                            geom.visual = trimesh.visual.TextureVisuals(material=material)
                                            vertex_colors = np.tile([r, g, b, 255], (len(geom.vertices), 1))
                                            geom.visual.vertex_colors = vertex_colors.astype(np.uint8)
                                    
                                    self.log_operation(f"Applied color RGB({r}, {g}, {b}) to all geometries")
                                
                                # Export: Concatenate to single mesh (best compromise)
                                # Note: This may affect texture quality but preserves geometry
                                self.log_operation("Concatenating scene to single mesh for export")
                                try:
                                    # Concatenate all geometries into single mesh
                                    mesh = scene_or_mesh.dump(concatenate=True)
                                    self.log_operation(f"Concatenated mesh: {len(mesh.vertices)} vertices")
                                    
                                    # Verify mesh has correct size
                                    if mesh.bounds is not None:
                                        extents = mesh.bounds[1] - mesh.bounds[0]
                                        self.log_operation(f"Final mesh extents: {extents}")
                                    
                                    # Export concatenated mesh
                                    self.log_operation(f"Exporting mesh to: {output_path}")
                                    if os.path.exists(output_path):
                                        os.remove(output_path)
                                    mesh.export(output_path, file_type='glb')
                                    
                                    # Verify export
                                    if os.path.exists(output_path):
                                        file_size = os.path.getsize(output_path)
                                        self.log_operation(f"Mesh exported successfully: {file_size} bytes")
                                    else:
                                        self.log_operation("ERROR: Mesh export failed!", "ERROR")
                                        return False
                                    
                                    self.update_status("COMPLETED")
                                    return True
                                    
                                except Exception as export_error:
                                    self.log_operation(f"ERROR exporting mesh: {export_error}", "ERROR")
                                    import traceback
                                    self.log_operation(f"Traceback: {traceback.format_exc()}")
                                    return False
                            
                            else:
                                # Single mesh (not scene)
                                self.log_operation("Processing single mesh")
                                mesh = scene_or_mesh
                                
                                # Check if mesh has valid vertices
                                if len(mesh.vertices) == 0 and hasattr(self, '_fbx_vertices'):
                                    self.log_operation("WARNING: Mesh has zero vertices, using original FBX data")
                                    if self._fbx_vertices is not None and hasattr(self, '_fbx_faces') and self._fbx_faces is not None:
                                        mesh = trimesh.Trimesh(vertices=self._fbx_vertices, faces=self._fbx_faces)
                                        self.log_operation(f"Created mesh from original FBX ({len(mesh.vertices)} vertices)")
                                
                                # Apply scaling to single mesh
                                if original_dimensions and self.max_dimension > 0:
                                    max_dim_m = original_dimensions['max']
                                    max_allowed_m = self.max_dimension
                                    scale_factor = max_allowed_m / max_dim_m
                                    self.log_operation(f"Applying scale factor from original FBX: {scale_factor:.4f}")
                                    
                                    bounds_before = mesh.bounds
                                    if bounds_before is not None:
                                        extents_before = bounds_before[1] - bounds_before[0]
                                        self.log_operation(f"Bounds before scaling: {bounds_before}")
                                        self.log_operation(f"Extents before scaling: {extents_before}")
                                    else:
                                        self.log_operation("Bounds before scaling: None")
                                        extents_before = None
                                    
                                    mesh.apply_scale(scale_factor)
                                    
                                    bounds_after = mesh.bounds
                                    if bounds_after is not None:
                                        extents_after = bounds_after[1] - bounds_after[0]
                                        self.log_operation(f"Bounds after scaling: {bounds_after}")
                                        self.log_operation(f"Extents after scaling: {extents_after}")
                                    else:
                                        self.log_operation("Bounds after scaling: None")
                                
                                # Apply color if needed (for single mesh)
                                if color:
                                    self.apply_color(mesh, color)
                                
                                # Export single mesh
                                self.log_operation(f"Exporting single mesh to: {output_path}")
                                if os.path.exists(output_path):
                                    os.remove(output_path)
                                mesh.export(output_path, file_type='glb')
                                self.log_operation(f"Single mesh exported successfully")
                                self.update_status("COMPLETED")
                                return True
                        
                        except Exception as e:
                            self.handle_error(f"Error post-processing GLB: {str(e)}")
                            import traceback
                            self.log_operation(f"Traceback: {traceback.format_exc()}")
                            return False
                    
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

    def _embed_external_textures(self, glb_path: str, fbx_path: str) -> None:
        """Embed external texture files into GLB."""
        try:
            from pygltflib import GLTF2
            import base64
            
            self.log_operation(f"Loading GLB to embed textures: {glb_path}")
            gltf = GLTF2().load(glb_path)
            
            if not gltf.images:
                self.log_operation("No images found in GLB")
                return
            
            fbx_dir = os.path.dirname(fbx_path)
            glb_dir = os.path.dirname(glb_path)
            modified = False
            
            for i, image in enumerate(gltf.images):
                # Check if image has external URI (not embedded)
                if image.uri and not image.uri.startswith('data:'):
                    self.log_operation(f"Found external texture: {image.uri}")
                    
                    # Try multiple locations for texture file
                    texture_path = None
                    search_paths = [
                        os.path.join(glb_dir, image.uri),  # Same dir as GLB
                        os.path.join(fbx_dir, image.uri),  # Same dir as FBX
                        os.path.join(glb_dir, os.path.basename(image.uri)),  # GLB dir, filename only
                        os.path.join(fbx_dir, os.path.basename(image.uri)),  # FBX dir, filename only
                    ]
                    
                    for path in search_paths:
                        if os.path.exists(path):
                            texture_path = path
                            break
                    
                    if not texture_path:
                        self.log_operation(f"Warning: Texture file not found in any location: {image.uri}", "WARNING")
                        self.log_operation(f"Searched: {search_paths}", "WARNING")
                        continue
                    
                    self.log_operation(f"Embedding texture: {texture_path}")
                    
                    # Read texture file
                    with open(texture_path, 'rb') as f:
                        texture_data = f.read()
                    
                    # Determine MIME type
                    ext = os.path.splitext(texture_path)[1].lower()
                    mime_type = {
                        '.png': 'image/png',
                        '.jpg': 'image/jpeg',
                        '.jpeg': 'image/jpeg',
                        '.webp': 'image/webp'
                    }.get(ext, 'image/png')
                    
                    # Convert to data URI
                    data_uri = f"data:{mime_type};base64,{base64.b64encode(texture_data).decode('utf-8')}"
                    image.uri = data_uri
                    modified = True
                    self.log_operation(f"Embedded texture {i}: {len(texture_data)} bytes")
            
            if modified:
                self.log_operation("Saving GLB with embedded textures")
                gltf.save(glb_path)
                self.log_operation("✅ Textures embedded successfully")
            else:
                self.log_operation("No external textures to embed")
                
        except Exception as e:
            self.log_operation(f"Error embedding textures: {e}", "ERROR")
            import traceback
            self.log_operation(f"Traceback: {traceback.format_exc()}")
            raise

    def handle_error(self, error_message: str) -> None:
        """Handle and log error messages."""
        self.update_status("ERROR")
        logger.error(error_message)
        self.log_operation(f"Error: {error_message}")
