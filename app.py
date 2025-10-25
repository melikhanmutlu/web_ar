from datetime import datetime
import os
import json
from flask import Flask, request, jsonify, send_from_directory, render_template, redirect, url_for, flash, session
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import logging
import shutil
import subprocess
from models import db, User, UserModel, Folder
from auth import auth
import re
import traceback
import uuid
from flask_migrate import Migrate
from config import *
from sqlalchemy.orm import Session
import qrcode
from slugify import slugify
import trimesh
from converters import OBJConverter, FBXConverter, STLConverter
import numpy as np

app = Flask(__name__)
app.config.from_object('config')
app.secret_key = 'super secret key'

# Add headers to allow all origins
@app.after_request
def after_request(response):
    return response

# Initialize directories
def create_directories():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(CONVERTED_FOLDER, exist_ok=True)
    os.makedirs(TEMP_FOLDER, exist_ok=True)

create_directories()

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# SQLite thread-safe configuration
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {
        'check_same_thread': False
    }
}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['CONVERTED_FOLDER'] = CONVERTED_FOLDER
app.config['TEMP_FOLDER'] = TEMP_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB limit
app.config['ALLOWED_EXTENSIONS'] = {'obj', 'stl', 'fbx'}

# Constants
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
CONVERTED_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'converted')
TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'temp')
QR_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'qr_codes')
ALLOWED_EXTENSIONS = {'obj', 'stl', 'fbx'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB limit

# Initialize extensions
db.init_app(app)
migrate = Migrate(app, db)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Register blueprints
app.register_blueprint(auth)

# Create database tables
with app.app_context():
    db.create_all()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('app.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_file_info(file_path):
    """Get detailed information about the uploaded file."""
    try:
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(file_path)[1].lower()
        
        info = {
            'size': file_size,
            'extension': file_ext,
            'vertices': 0,
            'faces': 0,
            'is_watertight': False,
            'bounds': None,
            'is_binary': False
        }
        
        # For 3D models, get additional information
        if file_ext[1:] in app.config['ALLOWED_EXTENSIONS']:
            try:
                # For FBX files, we can't get mesh information directly
                if file_ext == '.fbx':
                    logger.info("FBX file detected - mesh information will be updated after conversion")
                    return info
                    
                mesh = trimesh.load(file_path)
                if isinstance(mesh, trimesh.Scene):
                    # For scenes (like OBJ with multiple meshes), combine the statistics
                    total_vertices = 0
                    total_faces = 0
                    for geometry in mesh.geometry.values():
                        if isinstance(geometry, trimesh.Trimesh):
                            total_vertices += len(geometry.vertices)
                            total_faces += len(geometry.faces)
                    info['vertices'] = total_vertices
                    info['faces'] = total_faces
                else:
                    info['vertices'] = len(mesh.vertices)
                    info['faces'] = len(mesh.faces)
                    info['is_watertight'] = mesh.is_watertight
                    info['bounds'] = mesh.bounds.tolist() if hasattr(mesh, 'bounds') else None
                    if hasattr(mesh, 'is_binary'):
                        info['is_binary'] = mesh.is_binary
            except Exception as e:
                logger.warning(f"Could not load mesh information: {str(e)}")
        
        return info
    except Exception as e:
        logger.error(f"Error getting file info: {str(e)}")
        return None

def generate_unique_filename(original_filename):
    """Generate a unique filename while preserving the original extension."""
    ext = os.path.splitext(original_filename)[1]
    return f"{uuid.uuid4()}{ext}"

def apply_color_to_mesh(mesh, color_hex):
    """Apply color to a single mesh using face_colors."""
    try:
        # Convert hex color to RGBA (0-255 range)
        hex_color = color_hex.lstrip('#')
        # Ensure hex string is valid (6 digits)
        if len(hex_color) != 6:
            logger.error(f"Invalid hex color format: {color_hex}")
            return False
        try:
            rgb_255 = [int(hex_color[i:i+2], 16) for i in (0, 2, 4)]
        except ValueError:
             logger.error(f"Invalid characters in hex color: {color_hex}")
             return False
             
        rgba_255 = rgb_255 + [255]  # Add Alpha channel (fully opaque)
        logger.info(f"Applying RGBA(0-255) values: {rgba_255}")
        
        # Ensure the mesh has faces
        if not hasattr(mesh, 'faces') or mesh.faces is None or len(mesh.faces) == 0:
             logger.warning("Mesh has no faces, cannot apply face colors.")
             # Depending on workflow, might want to return True or False
             # If color should always be applied if possible, False is better
             return False
             
        # Ensure the mesh has a visual component, creating one if necessary
        if not hasattr(mesh, 'visual') or mesh.visual is None:
            # If no visual exists, create a basic ColorVisuals
            mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh)
            logger.info("Created new ColorVisuals for mesh.")
        elif not isinstance(mesh.visual, trimesh.visual.ColorVisuals):
            # If visual exists but isn't ColorVisuals, overwrite it cautiously
            # This might discard existing texture/material info, which is intended here
            logger.warning("Overwriting existing non-ColorVisuals visual data with ColorVisuals.")
            # Create new ColorVisuals, potentially losing old visual data
            mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh)
                 
        # Apply the color to all faces
        # Assigning a single color array will broadcast it to all faces
        mesh.visual.face_colors = rgba_255
        
        logger.info("Color applied successfully to mesh face_colors")
        return True
    except Exception as e:
        logger.error(f"Error applying color to mesh face_colors: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def apply_color_to_scene(scene, color_hex):
    """Apply color to all meshes in a scene."""
    try:
        success = True
        # Get all meshes from the scene
        if isinstance(scene, trimesh.Scene):
            logger.info("Processing scene with multiple geometries")
            for name, geometry in scene.geometry.items():
                logger.info(f"Processing geometry: {name}")
                if isinstance(geometry, trimesh.Trimesh):
                    if not apply_color_to_mesh(geometry, color_hex):
                        success = False
                        logger.warning(f"Failed to apply color to geometry: {name}")
        elif isinstance(scene, trimesh.Trimesh):
            logger.info("Processing single mesh")
            success = apply_color_to_mesh(scene, color_hex)
        else:
            logger.error(f"Unsupported scene type: {type(scene)}")
            return False
        
        return success
    except Exception as e:
        logger.error(f"Error applying color to scene: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

def apply_size_limit(mesh, max_size_meters=0.35):
    """Scale the model to fit within the maximum size while maintaining proportions."""
    if isinstance(mesh, trimesh.Scene):
        # Get the overall bounding box of the scene
        bounds = np.zeros((len(mesh.geometry), 2, 3))
        for i, geom in enumerate(mesh.geometry.values()):
            bounds[i] = geom.bounds
        # Correctly calculate scene bounds: min of mins, max of maxs
        min_bound = np.min(bounds[:, 0, :], axis=0)
        max_bound = np.max(bounds[:, 1, :], axis=0)
        bounds = np.array([min_bound, max_bound])
    elif isinstance(mesh, trimesh.Trimesh):
        bounds = mesh.bounds
    else:
        logger.warning("apply_size_limit called with unsupported type. Skipping scaling.")
        return mesh # Return unmodified if not Scene or Trimesh

    # Calculate current dimensions
    dimensions = bounds[1] - bounds[0]
    # Handle potential NaN or Inf values in dimensions gracefully
    dimensions = np.nan_to_num(dimensions, nan=0.0, posinf=0.0, neginf=0.0)
    max_dimension = np.max(dimensions)
    
    # Calculate scale factor ONLY if target size and current size are positive
    if max_size_meters <= 0 or max_dimension <= 1e-9: # Use epsilon for float comparison
        logger.warning(
            f"Skipping scaling: Target size ({max_size_meters:.4f}m) or model dimension "
            f"({max_dimension:.4f}m) is non-positive or too small."
        )
        return mesh # Return the original mesh without scaling
        
    scale_factor = max_size_meters / max_dimension
    logger.info(f"Calculated scale factor: {scale_factor:.4f} (Target: {max_size_meters:.4f}m / Current: {max_dimension:.4f}m)")

    # Define the scaling transformation matrix
    # Using trimesh.transformations is generally preferred and clearer
    # Scaling is applied relative to the mesh's centroid to avoid shifting
    center = mesh.centroid
    T_neg = trimesh.transformations.translation_matrix(-center)
    S = trimesh.transformations.scale_matrix(scale_factor, origin=None) # Scale uniformly
    T_pos = trimesh.transformations.translation_matrix(center)
    transform_matrix = trimesh.transformations.concatenate_matrices(T_pos, S, T_neg)
        
    # Apply scaling transformation
    try:
        mesh.apply_transform(transform_matrix)
        logger.info("Scaling transformation applied successfully.")
    except Exception as e:
        logger.error(f"Error applying scaling transform: {e}")
        # Return original mesh if transform fails
        # (Need to reload original state or handle this more robustly if needed)
        # For now, we might be returning a partially transformed mesh, which isn't ideal.
        # A safer approach would be to work on a copy if scaling might fail.
        pass # Allow process to continue with potentially unscaled/partially scaled mesh

    return mesh

def convert_model_new(input_file, output_path=None, color=None):
    """Convert 3D model to GLB format with optional color application."""
    try:
        # Generate output path if not provided
        if output_path is None:
            output_path = os.path.join(
                app.config['CONVERTED_FOLDER'],
                os.path.splitext(os.path.basename(input_file))[0] + '.glb'
            )

        # Get file extension
        file_ext = os.path.splitext(input_file)[1].lower()

        # For FBX files, first convert to GLB then apply color
        if file_ext == '.fbx':
            # Convert FBX to GLB
            temp_glb = convert_fbx_to_glb(input_file, output_path)
            if not temp_glb:
                return None

            # Apply color if specified
            if color:
                try:
                    mesh = trimesh.load(output_path)
                    if apply_color_to_scene(mesh, color):
                        mesh.export(output_path)
                except Exception as e:
                    logger.error(f"Error applying color to converted FBX: {str(e)}")
                    # Continue even if color application fails
            return output_path

        # For other formats
        try:
            scene = trimesh.load(input_file)
            if color:
                if not apply_color_to_scene(scene, color):
                    logger.warning("Failed to apply color to model")
            scene.export(output_path)
            return output_path
        except Exception as e:
            logger.error(f"Error in color application: {str(e)}")
            # If color application fails, try regular conversion
            return convert_to_glb(input_file)

    except Exception as e:
        logger.error(f"Error in convert_model_new: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

def convert_stl_to_glb(stl_path, output_path):
    """Convert STL file to GLB format using trimesh."""
    try:
        # Load the STL file
        mesh = trimesh.load(stl_path)
        
        # Create a scene with a single geometry
        scene = trimesh.Scene()
        scene.add_geometry(mesh)
        
        # Export as GLB
        scene.export(output_path)
        
        return output_path
        
    except Exception as e:
        app.logger.error(f"Error converting STL to GLB: {str(e)}")
        return None

def convert_fbx_to_glb(fbx_path, output_path):
    """Convert FBX file to GLB format using FBX2glTF."""
    try:
        logger.info("Starting FBX to GLB conversion")
        fbx2gltf_path = os.path.join(TOOLS_DIR, 'FBX2glTF.exe')
        
        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # Construct and run the conversion command
        cmd = [
            fbx2gltf_path,
            '--binary',
            '--input', fbx_path,
            '--output', output_path,
            '--draco'  # Optimize model for better performance
        ]
        
        logger.info(f"Running FBX2glTF command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FBX conversion failed: {result.stderr}")
            return None
            
        logger.info("FBX converted successfully")
        return output_path
        
    except Exception as e:
        logger.error(f"Error in FBX conversion: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

def convert_obj_to_glb(obj_path, output_path):
    """Convert OBJ file to GLB format using obj2gltf."""
    try:
        logger.info("Starting OBJ to GLB conversion")
        
        # Create OBJ converter
        converter = OBJConverter()
        
        # Validate file
        if not converter.validate(obj_path):
            logger.error("OBJ file validation error")
            return None
            
        # Process MTL file
        if 'mtl' in request.files:
            mtl_file = request.files['mtl']
            if mtl_file.filename:
                mtl_path = os.path.join(os.path.dirname(obj_path), secure_filename(mtl_file.filename))
                mtl_file.save(mtl_path)
                converter.set_material_file(mtl_path)
                logger.info(f"MTL file saved: {mtl_path}")
        
        # Process texture files
        if 'textures' in request.files:
            textures = request.files.getlist('textures')
            for texture in textures:
                if texture.filename:
                    texture_path = os.path.join(os.path.dirname(obj_path), secure_filename(texture.filename))
                    texture.save(texture_path)
                    converter.add_texture_file(texture_path)
                    logger.info(f"Texture file saved: {texture_path}")
        
        # Start conversion
        if converter.convert(obj_path, output_path):
            logger.info("OBJ conversion successful")
            return output_path
        else:
            logger.error("OBJ conversion failed")
            return None
            
    except Exception as e:
        logger.error(f"Error during OBJ conversion: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

def convert_to_glb(file_path):
    """Convert uploaded 3D model to GLB format using appropriate converter."""
    try:
        file_ext = os.path.splitext(file_path)[1].lower()[1:]  # Get extension without dot
        output_path = os.path.join(app.config['CONVERTED_FOLDER'], os.path.splitext(os.path.basename(file_path))[0] + '.glb')
        
        if file_ext not in ALLOWED_EXTENSIONS:
            logger.error(f"Unsupported file format: {file_ext}")
            return None
            
        # Create appropriate converter based on file extension
        if file_ext == 'obj':
            converter = OBJConverter()
        elif file_ext == 'stl':
            converter = STLConverter()
        elif file_ext == 'fbx':
            converter = FBXConverter()
        else:
            logger.error(f"No converter available for {file_ext}")
            return None
            
        # Validate and convert the file
        if not converter.validate(file_path):
            logger.error("File validation failed")
            return None
            
        if converter.convert(file_path, output_path):
            logger.info(f"Successfully converted {file_ext.upper()} to GLB")
            return output_path
        else:
            logger.error("Conversion failed")
            return None
            
    except Exception as e:
        logger.error(f"Error in convert_to_glb: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None

def normalize_texture_name(filename):
    """Normalize texture filename for comparison by removing common variations."""
    # Convert to lowercase
    name = filename.lower()
    # Remove common prefixes
    prefixes = ['indoor_', 'indoor']
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix):]
    # Remove underscores and spaces
    name = name.replace('_', '').replace(' ', '')
    return name

def extract_texture_references(mtl_path):
    """Extract texture file references from MTL file."""
    texture_files = set()
    if not mtl_path or not os.path.exists(mtl_path):
        return texture_files
        
    try:
        with open(mtl_path, 'r') as f:
            for line in f:
                line = line.strip().lower()
                # Check for common texture map types
                if any(line.startswith(prefix) for prefix in ['map_', 'bump', 'disp']):
                    parts = line.split()
                    if len(parts) >= 2:
                        # Get the texture filename, removing any path
                        texture_file = os.path.basename(parts[-1])
                        texture_files.add(texture_file)
    except Exception as e:
        app.logger.error(f"Error reading MTL file: {str(e)}")
    
    return texture_files

def process_mtl_file(mtl_path, available_textures, temp_dir):
    """Process MTL file and handle missing textures."""
    if not os.path.exists(mtl_path):
        return None
        
    try:
        with open(mtl_path, 'r') as f:
            mtl_content = f.read()
            
        # Create textures directory in temp folder
        temp_textures_dir = os.path.join(temp_dir, 'textures')
        os.makedirs(temp_textures_dir, exist_ok=True)
        
        # Process each texture reference
        modified_content = []
        for line in mtl_content.splitlines():
            if any(line.strip().lower().startswith(prefix) for prefix in ['map_', 'bump', 'disp']):
                parts = line.strip().split()
                if len(parts) >= 2:
                    texture_name = os.path.basename(parts[-1]).lower()
                    # Case-insensitive texture lookup
                    if texture_name in available_textures:
                        # Copy and reference available texture with original case
                        original_name = available_textures[texture_name]
                        src_path = os.path.join(app.config['UPLOAD_FOLDER'], original_name)
                        dst_path = os.path.join(temp_textures_dir, original_name)
                        shutil.copy2(src_path, dst_path)
                        # Update path in MTL
                        parts[-1] = f"textures/{original_name}"
                        modified_content.append(' '.join(parts))
                        app.logger.info(f"Copied texture file: {original_name}")
                    else:
                        # Skip missing texture line and log warning
                        app.logger.warning(f"Texture file not found in map: {texture_name}")
                        continue
            else:
                modified_content.append(line)
                
        # Write modified MTL
        temp_mtl = os.path.join(temp_dir, os.path.basename(mtl_path))
        with open(temp_mtl, 'w') as f:
            f.write('\n'.join(modified_content))
            
        app.logger.info("Updated MTL content:\n" + '\n'.join(modified_content))
        return temp_mtl
        
    except Exception as e:
        app.logger.error(f"Error processing MTL file: {str(e)}")
        return None

def fix_mtl_paths(content, texture_map):
    """Fix texture paths in MTL content to use only filenames."""
    app.logger.info(f"Original MTL content:\n{content}")
    
    # Split content into lines
    lines = content.split('\n')
    updated_lines = []
    
    for line in lines:
        if line.strip().startswith('map_Kd'):
            # Extract the texture filename from the path
            parts = line.strip().split()
            if len(parts) >= 2:
                old_path = parts[1]
                filename = os.path.basename(old_path).lower()
                if filename in texture_map:
                    # Use the actual filename from our texture map
                    new_line = f"map_Kd textures/{texture_map[filename]}"
                    updated_lines.append(new_line)
                    app.logger.info(f"Updated texture path: {old_path} -> {new_line}")
                else:
                    app.logger.warning(f"Texture file not found in map: {filename}")
                    updated_lines.append(line)
        else:
            updated_lines.append(line)
    
    updated_content = '\n'.join(updated_lines)
    app.logger.info(f"Updated MTL content:\n{updated_content}")
    return updated_content

def generate_qr_code(model_id):
    """Generate QR code for a model."""
    try:
        session = Session(db.engine)
        model = session.get(UserModel, model_id)
        if not model:
            logger.error(f"Model not found with ID: {model_id}")
            return None

        # Generate the absolute URL for the model view
        base_url = request.host_url.rstrip('/')  # Get base URL without trailing slash
        model_url = f"{base_url}{url_for('view_model', model_id=model_id)}"
        
        # Create QR code instance
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        
        # Add data to QR code
        qr.add_data(model_url)
        qr.make(fit=True)

        # Create QR code image with proper coloring
        qr_image = qr.make_image(fill_color="black", back_color="white")
        
        # Generate unique filename for QR code
        qr_filename = f"qr_{model_id}_{uuid.uuid4()}.png"
        qr_path = os.path.join(app.config['CONVERTED_FOLDER'], qr_filename)
        
        # Save QR code image
        qr_image.save(qr_path)
        
        # Update model with QR code filename
        model.qr_code = qr_filename
        db.session.commit()
        
        logger.info(f"QR code generated successfully: {qr_filename}")
        return qr_filename
    except Exception as e:
        logger.error(f"Error generating QR code: {str(e)}")
        return None

def validate_color(color):
    """Validate hex color format."""
    if not color:
        return '#4CAF50'  # Default green
    if not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', color):
        raise ValueError('Invalid color format. Must be a valid hex color (e.g., #FF0000)')
    return color

def hex_to_rgb(hex_color):
    """Convert hex color string to RGB values (0-1 range)."""
    hex_color = hex_color.lstrip('#')
    return [int(hex_color[i:i+2], 16)/255 for i in (0, 2, 4)]

def cleanup_files(*file_paths):
    """Clean up temporary files."""
    for file_path in file_paths:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up file: {file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up file {file_path}: {str(e)}")

def generate_unique_id():
    return str(uuid.uuid4())

def cleanup_missing_models():
    """Clean up database records for models whose files no longer exist."""
    try:
        # Get all models from database
        session = Session(db.engine)
        models = session.query(UserModel).all()
        deleted_count = 0
        
        for model in models:
            # Check if the original uploaded file exists
            if not os.path.exists(model.file_path):
                logger.info(f"Model {model.id} ({model.original_filename}) file not found at: {model.file_path}")
                try:
                    # Also try to delete the converted file if it exists
                    converted_path = os.path.join(app.config['CONVERTED_FOLDER'], f"{model.id}.glb")
                    if os.path.exists(converted_path):
                        os.remove(converted_path)
                        logger.info(f"Deleted converted file: {converted_path}")
                except Exception as e:
                    logger.warning(f"Error deleting converted file for model {model.id}: {str(e)}")
                
                # Delete from database
                session.delete(model)
                deleted_count += 1
                logger.info(f"Deleted model {model.id} from database")
        
        if deleted_count > 0:
            db.session.commit()
            logger.info(f"Cleaned up {deleted_count} missing model records from database")
            flash(f"{deleted_count} missing model(s) were cleaned up from the database", "info")
        
    except Exception as e:
        logger.error(f"Error cleaning up missing models: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        flash("Error cleaning up missing models", "error")

def check_node_installed():
    """Check if Node.js is installed."""
    try:
        result = subprocess.run(['node', '--version'], 
                              capture_output=True, 
                              text=True)
        if result.returncode == 0:
            app.logger.info(f"Node.js is installed: {result.stdout.strip()}")
            return True
        else:
            app.logger.error("Node.js is not installed")
            return False
    except Exception as e:
        app.logger.error(f"Error checking Node.js: {str(e)}")
        return False

def ensure_obj2gltf_installed():
    """Ensure obj2gltf is installed globally."""
    try:
        # Check if obj2gltf is installed using full path to npx
        npx_path = r"C:\Program Files\nodejs\npx.cmd"
        result = subprocess.run([npx_path, 'obj2gltf', '--version'],
                              capture_output=True,
                              text=True)
        if result.returncode == 0:
            app.logger.info(f"obj2gltf is installed: {result.stdout.strip()}")
            return True
        else:
            app.logger.info("Installing obj2gltf globally...")
            install_result = subprocess.run(['npm', 'install', '-g', 'obj2gltf'],
                                         capture_output=True,
                                         text=True)
            if install_result.returncode == 0:
                app.logger.info("obj2gltf installed successfully")
                return True
            else:
                app.logger.error(f"Failed to install obj2gltf: {install_result.stderr}")
                return False
    except Exception as e:
        app.logger.error(f"Error with obj2gltf: {str(e)}")
        return False

def init_app_dependencies():
    """Initialize application dependencies and directories."""
    try:
        # Create necessary directories
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(app.config['CONVERTED_FOLDER'], exist_ok=True)
        os.makedirs(app.config['TEMP_FOLDER'], exist_ok=True)
        app.logger.info("Created necessary directories")

        # Check for Node.js and obj2gltf
        if not check_node_installed():
            app.logger.error("Node.js is required but not installed")
            return False

        if not ensure_obj2gltf_installed():
            app.logger.error("obj2gltf installation failed")
            return False

        app.logger.info("All required tools found")
        return True

    except Exception as e:
        app.logger.error(f"Error initializing dependencies: {str(e)}")
        app.logger.error(traceback.format_exc())
        return False

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    try:
        logger.info("Starting upload process")
        
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['file']
        logger.info(f"File object: {file}")
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'error': 'File type not allowed'}), 400
            
        # Generate unique ID
        unique_id = str(uuid.uuid4())
        logger.info(f"Generated unique ID: {unique_id}")
        
        # Create upload subdirectory
        upload_subdir = os.path.join(app.config['UPLOAD_FOLDER'], unique_id)
        os.makedirs(upload_subdir, exist_ok=True)
        logger.info(f"Created upload subdirectory: {upload_subdir}")
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_subdir, filename)
        file.save(file_path)
        logger.info(f"File saved successfully: {file_path}")
        
        # Get file extension
        file_extension = os.path.splitext(filename)[1].lower()
        logger.info(f"File extension: {file_extension}")
        
        # Get color settings
        # Handle both string and boolean values for useColor
        use_color_raw = request.form.get('useColor', 'false')
        if isinstance(use_color_raw, str):
            use_color = use_color_raw.lower() in ('true', '1', 'yes')
        else:
            use_color = bool(use_color_raw)
        
        color = request.form.get('color', '#4CAF50')
        logger.info(f"Color settings - useColor: {use_color}, color: {color}")
        
        # Get texture removal setting (for FBX)
        remove_textures_raw = request.form.get('removeTextures')
        remove_textures = remove_textures_raw == 'true' if remove_textures_raw else False
        logger.info(f"Remove textures setting: {remove_textures}")
        
        # Get maximum dimension setting (only if checkbox is checked)
        use_max_dimension_raw = request.form.get('useMaxDimension')
        logger.info(f"DEBUG: useMaxDimension raw value: {use_max_dimension_raw}, type: {type(use_max_dimension_raw)}")
        use_max_dimension = use_max_dimension_raw == 'true' if use_max_dimension_raw else False
        logger.info(f"DEBUG: useMaxDimension parsed: {use_max_dimension}")
        
        if use_max_dimension:
            max_dimension = float(request.form.get('maxDimension', '50')) / 100.0
            logger.info(f"Maximum dimension limit enabled: {max_dimension * 100} cm ({max_dimension} m)")
        else:
            max_dimension = 0  # No scaling
            logger.info(f"Maximum dimension limit disabled - model will keep original size")
        
        # Create converted directory
        converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], unique_id)
        os.makedirs(converted_dir, exist_ok=True)
        output_path = os.path.join(converted_dir, 'model.glb')
        
        # Get file info
        file_info = get_file_info(file_path)
        
        # Convert based on file type
        if file_extension == '.obj':
            converter = OBJConverter()
            
            # Handle MTL file for OBJ
            if 'mtl' in request.files:
                mtl_file = request.files['mtl']
                if mtl_file and mtl_file.filename:
                    mtl_filename = secure_filename(mtl_file.filename)
                    mtl_path = os.path.join(upload_subdir, mtl_filename)
                    mtl_file.save(mtl_path)
                    converter.set_material_file(mtl_path)
                    logger.info(f"MTL file saved: {mtl_path}")
            
            # Handle texture files for OBJ
            if 'textures' in request.files:
                texture_files = request.files.getlist('textures')
                for texture_file in texture_files:
                    if texture_file and texture_file.filename:
                        texture_filename = secure_filename(texture_file.filename)
                        texture_path = os.path.join(upload_subdir, texture_filename)
                        texture_file.save(texture_path)
                        converter.add_texture_file(texture_path)
                        logger.info(f"Texture file saved: {texture_path}")
                        
        elif file_extension == '.stl':
            converter = STLConverter()
        elif file_extension == '.fbx':
            converter = FBXConverter()
            # Set texture removal for FBX if requested
            if remove_textures:
                converter.remove_textures = True
                logger.info("FBX texture removal enabled")
        else:
            return jsonify({'error': 'Unsupported file format'}), 400
            
        # Set maximum dimension (convert from meters to cm)
        converter.set_max_dimension(max_dimension * 100)
        
        # Apply color if specified
        if use_color and color:
            success = converter.convert(file_path, output_path, color=color)
        else:
            success = converter.convert(file_path, output_path)
            
        if not success:
            return jsonify({'error': 'Conversion failed'}), 500

        # Save model info to database
        model = UserModel(
            id=unique_id, # Use the same unique_id generated for the folder
            user_id=current_user.id if current_user.is_authenticated else None,
            filename=output_path,  # Store the full path to the GLB file
            file_size=os.path.getsize(output_path),
            file_type=os.path.splitext(filename)[1][1:],  # Remove the dot
            upload_date=datetime.utcnow(),
            color=color if use_color else None
        )
        db.session.add(model)
        db.session.commit()
        logger.info(f"Model info saved to database with ID: {unique_id}")
            
        # Generate QR code
        qr_code_filename = generate_qr_code(unique_id)
        logger.info(f"QR code generated: {qr_code_filename}")
        
        # Return success response
        viewer_url = url_for('view_model', model_id=unique_id)
        return jsonify({
            'success': True,
            'viewer_url': viewer_url,
            'message': 'Model uploaded and converted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error during upload: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/upload_progress')
def upload_progress():
    """Get the current upload progress."""
    progress = session.get('upload_progress', 0)
    return jsonify({'progress': progress})

@app.route('/upload_model', methods=['POST'])
def upload_model():
    """Upload and convert 3D model. Works with or without login."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
        
    original_filename = secure_filename(file.filename)
    if not allowed_file(original_filename):
        return jsonify({'error': 'File type not allowed'}), 400
        
    temp_dir = None # Initialize temp_dir
    try:
        # Get form data
        # Handle both string and boolean values for useColor
        use_color_raw = request.form.get('useColor', 'false')
        if isinstance(use_color_raw, str):
            use_color = use_color_raw.lower() in ('true', '1', 'yes')
        else:
            use_color = bool(use_color_raw)
        
        color = request.form.get('color', '#4CAF50')
        logger.info(f"Color settings - useColor: {use_color}, color: {color}")
        max_dimension_str = request.form.get('maxDimension')
        max_dimension = None
        if max_dimension_str:
            try:
                max_dimension = float(max_dimension_str) / 100.0 # Convert cm to meters
            except ValueError:
                logger.warning(f"Invalid maxDimension value: {max_dimension_str}")
                # Optionally return an error or proceed without scaling

        # --- Start: Consistent File Handling Logic --- 
        unique_id = str(uuid.uuid4())
        logger.info(f"[upload_model - {unique_id}] Generated unique ID")

        # Define temporary save path for uploaded file
        temp_dir = os.path.join(app.config['TEMP_FOLDER'], unique_id)
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, original_filename)
        
        # Save uploaded file temporarily
        file.save(temp_file_path)
        logger.info(f"[upload_model - {unique_id}] Temporary file saved: {temp_file_path}")

        # Define final output path in unique converted directory
        converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], unique_id)
        os.makedirs(converted_dir, exist_ok=True)
        output_path = os.path.join(converted_dir, 'model.glb')
        logger.info(f"[upload_model - {unique_id}] Defined final output path: {output_path}")

        # Get file extension
        file_extension = os.path.splitext(original_filename)[1].lower()

        # Instantiate appropriate converter
        converter = None
        if file_extension == '.obj':
            converter = OBJConverter()
            
            # Handle MTL file for OBJ
            if 'mtl' in request.files:
                mtl_file = request.files['mtl']
                if mtl_file and mtl_file.filename:
                    mtl_filename = secure_filename(mtl_file.filename)
                    mtl_path = os.path.join(temp_dir, mtl_filename)
                    mtl_file.save(mtl_path)
                    converter.set_material_file(mtl_path)
                    logger.info(f"[upload_model - {unique_id}] MTL file saved: {mtl_path}")
            
            # Handle texture files for OBJ
            if 'textures' in request.files:
                texture_files = request.files.getlist('textures')
                for texture_file in texture_files:
                    if texture_file and texture_file.filename:
                        texture_filename = secure_filename(texture_file.filename)
                        texture_path = os.path.join(temp_dir, texture_filename)
                        texture_file.save(texture_path)
                        converter.add_texture_file(texture_path)
                        logger.info(f"[upload_model - {unique_id}] Texture file saved: {texture_path}")
            
        elif file_extension == '.stl':
            converter = STLConverter()
        elif file_extension == '.fbx':
            converter = FBXConverter()
        
        if not converter:
            if temp_dir: shutil.rmtree(temp_dir)
            return jsonify({'error': 'Unsupported file format'}), 400

        # Set max dimension if specified
        if max_dimension:
            converter.set_max_dimension(max_dimension * 100)  # Convert back to cm

        # Perform conversion
        logger.info(f"[upload_model - {unique_id}] Starting conversion using {type(converter).__name__} for {temp_file_path} to {output_path}")
        conversion_success = converter.convert(temp_file_path, output_path, color=color if use_color else None)
        logger.info(f"[upload_model - {unique_id}] Conversion result: {conversion_success}")

        if not conversion_success or not os.path.exists(output_path):
            logger.error(f"[upload_model - {unique_id}] Conversion failed or output file missing for {temp_file_path}")
            if temp_dir: shutil.rmtree(temp_dir)
            return jsonify({'error': 'Conversion failed'}), 500
        else:
            logger.info(f"[upload_model - {unique_id}] Conversion successful, output exists: {output_path}")

        # --- Temporarily Disable Scaling --- 
        logger.info(f"[upload_model - {unique_id}] Skipping scaling step for debugging.")
        # if max_dimension is not None and os.path.exists(output_path):
        #     logger.info(f"[upload_model - {unique_id}] Applying size limit: {max_dimension}m to {output_path}")
        #     try:
        #         # Load the mesh AFTER successful conversion
        #         mesh = trimesh.load(output_path) 
        #         apply_size_limit(mesh, max_dimension) # apply_size_limit modifies the mesh in-place
        #         logger.info(f"[upload_model - {unique_id}] Scaling applied conceptually, attempting export...")
        #         mesh.export(output_path) # Overwrite the file with the scaled version
        #         logger.info(f"[upload_model - {unique_id}] Export after scaling successful.")
        #     except Exception as e:
        #         logger.error(f"[upload_model - {unique_id}] Error scaling or exporting model {output_path}: {str(e)}")
        #         # Decide if scaling failure should stop the process
        #         # For now, log error and continue with unscaled model
        # else:
        #      logger.info(f"[upload_model - {unique_id}] No max dimension specified or output file missing before scaling.")

        # Check file size before saving to DB
        final_file_size = 0
        if os.path.exists(output_path):
            final_file_size = os.path.getsize(output_path)
            logger.info(f"[upload_model - {unique_id}] Final file size of {output_path}: {final_file_size} bytes")
        else:
            logger.error(f"[upload_model - {unique_id}] CRITICAL: Output file {output_path} does not exist before saving to DB!")
            if temp_dir: shutil.rmtree(temp_dir)
            return jsonify({'error': 'Internal server error: Processed file missing'}), 500

        if final_file_size == 0:
             logger.warning(f"[upload_model - {unique_id}] WARNING: Final file size of {output_path} is 0 bytes!")
             # Decide if 0-byte file is an error
             # return jsonify({'error': 'Internal server error: Processed file is empty'}), 500

        # Clean up temporary file and directory
        try:
            if temp_dir: 
                shutil.rmtree(temp_dir)
                logger.info(f"[upload_model - {unique_id}] Cleaned up temporary directory: {temp_dir}")
        except Exception as cleanup_error:
             logger.error(f"[upload_model - {unique_id}] Error cleaning up temp directory {temp_dir}: {cleanup_error}")

        # --- End: Consistent File Handling Logic --- 

        # Calculate model dimensions for database
        model_bounds = None
        
        # For FBX, try to use original dimensions from converter
        # BUT if scaling was applied, we need to scale the dimensions too!
        if file_extension == '.fbx' and hasattr(converter, 'original_dimensions') and converter.original_dimensions:
            try:
                import json
                orig_dims = converter.original_dimensions
                
                # Check if scaling was applied
                scale_factor = 1.0
                if hasattr(converter, 'max_dimension') and converter.max_dimension > 0:
                    # Scaling was applied - calculate the scale factor
                    orig_max_m = orig_dims['max']
                    target_max_m = converter.max_dimension
                    scale_factor = target_max_m / orig_max_m
                    logger.info(f"[upload_model - {unique_id}] FBX was scaled: {scale_factor:.4f}x (orig: {orig_max_m:.4f}m -> target: {target_max_m:.4f}m)")
                
                # Apply scale factor to dimensions
                x_cm = round(orig_dims['x'] * scale_factor * 100, 2)
                y_cm = round(orig_dims['y'] * scale_factor * 100, 2)
                z_cm = round(orig_dims['z'] * scale_factor * 100, 2)
                max_cm = round(orig_dims['max'] * scale_factor * 100, 2)
                
                model_bounds = json.dumps({
                    'extents': [x_cm, y_cm, z_cm],
                    'max': max_cm
                })
                logger.info(f"[upload_model - {unique_id}] Using FBX dimensions (after scaling): {x_cm} x {y_cm} x {z_cm} cm (max: {max_cm} cm)")
            except Exception as e:
                logger.warning(f"[upload_model - {unique_id}] Could not use original FBX dimensions: {str(e)}")
        
        # If not FBX or FBX dimensions failed, try from GLB
        if not model_bounds:
            try:
                import trimesh
                import numpy as np
                import json
                
                mesh = trimesh.load(output_path)
                logger.info(f"[upload_model - {unique_id}] Loaded mesh type: {type(mesh)}")
                
                # Get extents
                if isinstance(mesh, trimesh.Scene):
                    logger.info(f"[upload_model - {unique_id}] Scene has {len(mesh.geometry)} geometries")
                    all_vertices = []
                    for geom in mesh.geometry.values():
                        if isinstance(geom, trimesh.Trimesh):
                            all_vertices.append(geom.vertices)
                    
                    if all_vertices:
                        combined_vertices = np.vstack(all_vertices)
                        logger.info(f"[upload_model - {unique_id}] Combined {len(all_vertices)} vertex arrays, total vertices: {len(combined_vertices)}")
                        min_bounds = combined_vertices.min(axis=0)
                        max_bounds = combined_vertices.max(axis=0)
                        extents = max_bounds - min_bounds
                        logger.info(f"[upload_model - {unique_id}] Extents from vertices: {extents}")
                    else:
                        bounds = mesh.bounds
                        extents = bounds[1] - bounds[0]
                        logger.info(f"[upload_model - {unique_id}] Extents from scene bounds: {extents}")
                else:
                    extents = mesh.extents
                    logger.info(f"[upload_model - {unique_id}] Extents from mesh: {extents}")
            
                # Convert to cm and store
                if max(extents) > 0.001:
                    x_cm = round(float(extents[0]) * 100, 2)
                    y_cm = round(float(extents[1]) * 100, 2)
                    z_cm = round(float(extents[2]) * 100, 2)
                    max_cm = round(float(max(extents)) * 100, 2)
                    
                    model_bounds = json.dumps({
                        'extents': [x_cm, y_cm, z_cm],
                        'max': max_cm
                    })
                    logger.info(f"[upload_model - {unique_id}] Model dimensions: {x_cm} x {y_cm} x {z_cm} cm (max: {max_cm} cm)")
                else:
                    logger.warning(f"[upload_model - {unique_id}] Extents too small or zero: {extents}")
            except Exception as e:
                logger.warning(f"[upload_model - {unique_id}] Could not calculate dimensions: {str(e)}")
        
        # Create model record in database using the unique_id
        # user_id is optional - can be None if user is not logged in
        model = UserModel(
            id=unique_id, # Use the same ID as the directory
            user_id=current_user.id if current_user.is_authenticated else None,
            filename=output_path,  # Store the correct full absolute path
            file_size=final_file_size, # Use the checked size
            file_type=os.path.splitext(original_filename)[1][1:],  # Original extension
            upload_date=datetime.utcnow(),
            color=color if use_color else None,
            bounds=model_bounds  # Store dimensions
        )
        db.session.add(model)
        db.session.commit()
        logger.info(f"[upload_model - {unique_id}] Model info saved to database. User: {'logged in' if current_user.is_authenticated else 'anonymous'}")
        
        # Generate QR code (using the same unique_id)
        # qr_code_filename = generate_qr_code(unique_id)
        # logger.info(f"QR code generated: {qr_code_filename}")
        # Consider generating QR on demand or storing path in DB

        return jsonify({
            'success': True,
            'message': 'Model uploaded and processed successfully (scaling disabled)',
            'viewer_url': url_for('view_model', model_id=unique_id)
        })
        
    except Exception as e:
        # Ensure temporary directory cleanup on any exception
        if temp_dir and os.path.exists(temp_dir):
             try:
                 shutil.rmtree(temp_dir)
             except Exception as cleanup_error:
                 logger.error(f"[upload_model] Error cleaning up temp directory {temp_dir} during exception: {cleanup_error}")
        logger.error(f"[upload_model] Error in upload_model: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/convert', methods=['POST'])
def convert():
    try:
        logger.info("Starting model conversion process")
        data = request.get_json()

        if not data or 'modelId' not in data:
            logger.warning("No model ID provided")
            return jsonify({'error': 'No model ID provided'}), 400

        model_id = data['modelId']
        selected_color = data.get('selectedColor', '#FFFFFF')

        # Find original file
        original_files = [f for f in os.listdir(app.config['UPLOAD_FOLDER']) if f.startswith(model_id)]
        if not original_files:
            logger.error("No valid source file found")
            return jsonify({'error': 'No valid source file found'}), 404

        source_file = os.path.join(app.config['UPLOAD_FOLDER'], original_files[0])
        
        # Create model-specific directory
        model_dir = os.path.join(app.config['CONVERTED_FOLDER'], model_id)
        os.makedirs(model_dir, exist_ok=True)
        output_file = os.path.join(model_dir, 'model.glb')

        # Convert the model
        file_ext = os.path.splitext(source_file)[1].lower()
        if not convert_model_new(source_file, output_file):
            logger.error(f"Model conversion failed for {model_id}")
            return jsonify({'error': 'Model conversion failed'}), 500

        logger.info(f"Model converted successfully: {output_file}")

        # Update database if user is authenticated
        if current_user.is_authenticated:
            session = Session(db.engine)
            model = session.get(UserModel, model_id)
            if model:
                model.converted = True
                model.conversion_date = datetime.utcnow()
                db.session.commit()
                logger.info(f"Model conversion status updated in database: {model_id}")

        return jsonify({
            'message': 'Model converted successfully',
            'model_id': model_id
        }), 200

    except Exception as e:
        logger.error(f"Error in convert: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/view/<model_id>')
def view_model(model_id):
    """View a specific model."""
    app.logger.info(f"Accessing view_model with ID: {model_id}")
    
    # Check if model exists in database
    model = UserModel.query.get(model_id)
    if not model:
        flash('Model not found', 'error')
        return redirect(url_for('index'))
    
    # Check if converted file exists
    if not model.filename or not os.path.exists(model.filename):
        app.logger.error(f"Converted GLB file not found at path: {model.filename}")
        flash('Converted model file not found', 'error')
        return redirect(url_for('index'))
    
    # Get model dimensions - try database first, then GLB file
    model_dimensions = None
    
    # First, try to get from database (faster)
    if model.bounds:
        try:
            import json
            bounds_data = json.loads(model.bounds)
            if 'extents' in bounds_data:
                db_extents = bounds_data['extents']
                model_dimensions = {
                    'x': round(float(db_extents[0]), 2),
                    'y': round(float(db_extents[1]), 2),
                    'z': round(float(db_extents[2]), 2),
                    'max': round(float(bounds_data.get('max', max(db_extents))), 2)
                }
                app.logger.info(f"Using dimensions from database: {model_dimensions}")
        except Exception as db_e:
            app.logger.warning(f"Could not parse bounds from database: {db_e}")
    
    # If not in database, calculate from GLB file
    if not model_dimensions:
        try:
            import trimesh
            import numpy as np
            
            mesh = trimesh.load(model.filename)
            app.logger.info(f"Loaded mesh type: {type(mesh)}")
            
            # Get extents based on mesh type
            if isinstance(mesh, trimesh.Scene):
                # Prefer scene.bounds which includes node transforms (AABB of entire scene)
                # This fixes FBX2glTF cases where geometry is at origin but transforms are in nodes
                bounds = mesh.bounds
                extents = bounds[1] - bounds[0]
                app.logger.info(f"Scene extents from scene.bounds (AABB): {extents}")
                
                # If bounds also gives zero, try dump(concatenate=True) as fallback
                if max(extents) <= 0.001:
                    try:
                        combined_mesh = mesh.dump(concatenate=True)
                        extents = combined_mesh.extents
                        app.logger.info(f"Scene extents from dump(concatenate=True): {extents}")
                    except Exception as _e:
                        app.logger.info(f"dump(concatenate=True) failed: {_e}")
                        # Final fallback: stack raw vertices
                        all_vertices = []
                        for geom in mesh.geometry.values():
                            if isinstance(geom, trimesh.Trimesh):
                                all_vertices.append(geom.vertices)
                        if all_vertices:
                            combined_vertices = np.vstack(all_vertices)
                            min_bounds = combined_vertices.min(axis=0)
                            max_bounds = combined_vertices.max(axis=0)
                            extents = max_bounds - min_bounds
                            app.logger.info(f"Scene extents from stacked vertices: {extents}")
            else:
                extents = mesh.extents
                app.logger.info(f"Mesh extents: {extents}")
            
            # Convert to cm and round to 2 decimal places (show even if zero for FBX debugging)
            model_dimensions = {
                'x': round(float(extents[0]) * 100, 2),
                'y': round(float(extents[1]) * 100, 2),
                'z': round(float(extents[2]) * 100, 2),
                'max': round(float(max(extents)) * 100, 2)
            }
            app.logger.info(f"Model dimensions (cm): {model_dimensions}")
            
            if max(extents) <= 0.001:
                app.logger.warning(f"Warning: Extents are zero or very small: {extents} - GLB may be corrupted")
        except Exception as e:
            app.logger.error(f"Error getting model dimensions: {str(e)}")
            import traceback
            app.logger.error(traceback.format_exc())

    # Parse the path to get unique_id and actual filename for URL generation
    try:
        full_path = model.filename
        app.logger.info(f"Model full path from DB: {full_path}")
        converted_folder_abs = os.path.abspath(app.config['CONVERTED_FOLDER'])
        
        if full_path.startswith(converted_folder_abs):
            relative_path = os.path.relpath(full_path, converted_folder_abs)
            # Use os.path.normpath to handle mixed slashes if any, then split
            parts = os.path.normpath(relative_path).split(os.sep)
            if len(parts) == 2:
                model_unique_id = parts[0]
                actual_filename = parts[1]
                app.logger.info(f"Extracted ID: {model_unique_id}, Filename: {actual_filename}")
            else:
                app.logger.error(f"Could not parse unique_id and filename from relative path: {relative_path}")
                raise ValueError(f"Invalid model path structure: {relative_path}")
        else:
            app.logger.error(f"Model path {full_path} does not start with converted folder {converted_folder_abs}")
            raise ValueError("Model path is not within the expected converted folder")

    except Exception as e:
        import traceback as tb
        app.logger.error(f"Error parsing model path '{model.filename}': {e}")
        app.logger.error(tb.format_exc())
        flash('Error processing model path.', 'error')
        return redirect(url_for('index'))
    
    return render_template('view.html', 
                           model_id=model_id, 
                           model=model, 
                           model_unique_id=model_unique_id, 
                           actual_filename=actual_filename,
                           model_dimensions=model_dimensions)

# Route to serve converted model files
@app.route('/converted_files/<path:unique_id>/<path:filename>')
def serve_converted_file(unique_id, filename):
    directory = os.path.join(app.config['CONVERTED_FOLDER'], unique_id)
    app.logger.info(f"Attempting to serve file: {filename} from directory: {directory}")
    # Basic security check: ensure filename is just a filename, not trying to escape
    if os.path.basename(filename) != filename:
        app.logger.warning(f"Potential unsafe filename detected: {filename}")
        return "Not Found", 404
    try:
        return send_from_directory(directory, filename, as_attachment=False)
    except FileNotFoundError:
        app.logger.error(f"File not found in serve_converted_file: {directory}/{filename}")
        return "File not found", 404
    except Exception as e:
        app.logger.error(f"Error serving file: {e}")
        return "Server error", 500

@app.route('/my_models')
@app.route('/my_models/<folder_id>')
@login_required
def my_models(folder_id=None):
    try:
        if folder_id:
            current_folder = Folder.query.get_or_404(folder_id)
            folders = Folder.query.filter_by(parent_id=folder_id).all()
            models = UserModel.query.filter_by(folder_id=folder_id).all()
        else:
            current_folder = None
            folders = Folder.query.filter_by(parent_id=None).all()
            models = UserModel.query.filter_by(folder_id=None).all()

        # Get model counts for each folder
        folder_model_counts = {}
        for folder in folders:
            folder_model_counts[folder.id] = UserModel.query.filter_by(folder_id=folder.id).count()

        return render_template('my_models.html',
                            folders=folders,
                            models=models,
                            current_folder=current_folder,
                            folder_model_counts=folder_model_counts)
    except Exception as e:
        app.logger.error(f"Error in my_models: {str(e)}")
        return redirect('/')

@app.route('/converted/<path:filename>')
def get_converted_file(filename):
    """Serve converted model files."""
    try:
        # Get model from database
        model = UserModel.query.filter_by(filename=os.path.join(app.config['CONVERTED_FOLDER'], filename)).first()
        if not model:
            app.logger.error(f"Model not found for file: {filename}")
            return "File not found", 404

        # Check if file exists
        if not os.path.exists(model.filename):
            app.logger.error(f"File not found: {model.filename}")
            return "File not found", 404

        # Get directory and filename from full path
        directory = os.path.dirname(model.filename)
        basename = os.path.basename(model.filename)

        return send_from_directory(directory, basename)
    except Exception as e:
        app.logger.error(f"Error serving file: {str(e)}")
        return "Error serving file", 500

@app.route('/download/<model_id>')
@login_required
def download_model(model_id):
    """Download the converted model file."""
    try:
        # Get the model from database
        session = Session(db.engine)
        model = session.get(UserModel, model_id)

        # Check if user owns this model
        if model.user_id != current_user.id:
            return "Unauthorized", 403

        file_path = os.path.join(app.config['CONVERTED_FOLDER'], f"{model_id}.glb")
        if not os.path.exists(file_path):
            return "Dosya bulunamadı", 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=model.original_filename,
            mimetype='application/octet-stream'
        )
    except Exception as e:
        logger.error(f"Error in download_model: {str(e)}")
        return "Dosya indirilirken bir hata oluştu", 500

@app.route('/api/model-info/<int:model_id>')
@login_required
def get_model_info_api(model_id):
    session = Session(db.engine)
    model = session.get(UserModel, model_id)
    if model.user_id != current_user.id:
        flash('Bu modele erişim izniniz yok.', 'error')
        return redirect(url_for('auth.profile'))

    model_info = get_file_info(model.file_path)
    if model_info is None:
        return jsonify({'error': 'Model not found'}), 404

    return jsonify(model_info)

@app.route('/api/update-model-color', methods=['POST'])
@login_required
def update_model_color():
    try:
        data = request.get_json()
        model_id = data.get('model_id')
        color = data.get('color')

        if not model_id or not color:
            return jsonify({'error': 'Gerekli alanlar eksik'}), 400

        # Get the model
        session = Session(db.engine)
        model = session.get(UserModel, model_id)
        if not model or model.user_id != current_user.id:
            return jsonify({'error': 'Model bulunamadı veya yetkisiz erişim'}), 404

        # Update the model's color
        model.color = color
        db.session.commit()

        # Convert the model with the new color
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], model.filename)
        try:
            convert_model_new(input_path, os.path.join(app.config['CONVERTED_FOLDER'], f"{model_id}.glb"), color=color)
            return jsonify({'success': True}), 200
        except Exception as e:
            logger.error(f"Error converting model with new color: {str(e)}")
            return jsonify({'error': 'Model rengi güncellenirken bir hata oluştu'}), 500

    except Exception as e:
        logger.error(f"Error in update_model_color: {str(e)}")
        return jsonify({'error': 'Sunucu hatası'}), 500

@app.route('/temp/<filename>')
def get_temp_file(filename):
    """Serve temporary files (like QR codes)."""
    try:
        temp_path = os.path.join(app.config['CONVERTED_FOLDER'], filename)
        if os.path.exists(temp_path):
            return send_file(temp_path)
        else:
            logger.error(f"Temp file not found: {temp_path}")
            return "Dosya bulunamadı", 404
    except Exception as e:
        logger.error(f"Error serving temp file: {str(e)}")
        return str(e), 500

@app.route('/qr/<filename>')
def get_qr_code(filename):
    """Serve QR code files."""
    try:
        return send_from_directory(app.config['CONVERTED_FOLDER'], filename)
    except Exception as e:
        logger.error(f"Error serving QR code: {str(e)}")
        return "QR code not found", 404

@app.route('/delete_model/<string:model_id>', methods=['POST'])
def delete_model(model_id):
    session = None
    try:
        logger.info(f"Attempting to delete model with ID: {model_id}")
        session = Session(db.engine)
        
        # Get the model and log its details
        model = session.get(UserModel, model_id)
        if not model:
            logger.warning(f"Model {model_id} not found in database")
            return jsonify({"error": "Model not found"}), 404
        
        logger.info(f"Found model: ID={model.id}")

        # Delete the files
        try:
            # Delete files in converted folder
            converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], str(model_id))
            if os.path.exists(converted_dir):
                shutil.rmtree(converted_dir)
                logger.info(f"Deleted converted directory: {converted_dir}")

            # Delete files in uploads folder
            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], str(model_id))
            if os.path.exists(upload_dir):
                shutil.rmtree(upload_dir)
                logger.info(f"Deleted upload directory: {upload_dir}")

        except Exception as e:
            logger.error(f"Error deleting files for model {model_id}: {str(e)}")
            logger.error(traceback.format_exc())
            # Continue to delete from database even if file deletion fails

        # Delete from database
        try:
            session.delete(model)
            session.commit()
            logger.info(f"Deleted model {model_id} from database")
            return jsonify({"success": True}), 200
        except Exception as e:
            session.rollback()
            logger.error(f"Database error while deleting model {model_id}: {str(e)}")
            logger.error(traceback.format_exc())
            return jsonify({"error": "Database error"}), 500

    except Exception as e:
        logger.error(f"Unexpected error deleting model {model_id}: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": "Unexpected error"}), 500
    finally:
        # ALWAYS close the session
        if session:
            session.close()
            logger.debug(f"Session closed for model {model_id}")

@app.route('/delete_all_models', methods=['POST'])
@login_required
def delete_all_models():
    try:
        # Get all models for the current user
        session = Session(db.engine)
        models = session.query(UserModel).filter_by(user_id=current_user.id).all()
        deleted_count = 0
        failed_count = 0

        # Delete files for each model
        for model in models:
            try:
                # Delete files in converted folder
                converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], model.id)
                if os.path.exists(converted_dir):
                    shutil.rmtree(converted_dir)
                    logger.info(f"Deleted converted directory: {converted_dir}")

                # Delete files in uploads folder
                upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], model.id)
                if os.path.exists(upload_dir):
                    shutil.rmtree(upload_dir)
                    logger.info(f"Deleted upload directory: {upload_dir}")

                # Delete from database
                session.delete(model)
                deleted_count += 1
                
            except Exception as e:
                failed_count += 1
                logger.error(f"Error deleting model {model.id}: {str(e)}")
                logger.error(f"Traceback: {traceback.format_exc()}")

        # Commit database changes
        session.commit()
        logger.info(f"Deleted {deleted_count} models, failed to delete {failed_count} models")

        if failed_count > 0:
            return jsonify({
                "message": f"Partially successful: deleted {deleted_count} models, failed to delete {failed_count} models"
            }), 207
        return jsonify({"message": f"Successfully deleted {deleted_count} models"}), 200

    except Exception as e:
        logger.error(f"Error deleting all models: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Error deleting models"}), 500

@app.route('/delete_selected_models', methods=['POST'])
@login_required
def delete_selected_models():
    try:
        data = request.get_json()
        model_ids = data.get('model_ids', [])
        
        if not model_ids:
            return jsonify({'success': False, 'message': 'No models selected'})
        
        # Get all models that belong to the current user
        models = UserModel.query.filter(
            UserModel.id.in_(model_ids),
            UserModel.user_id == current_user.id
        ).all()
        
        if not models:
            return jsonify({'success': False, 'message': 'No valid models found'})
        
        for model in models:
            # Delete the model files
            model_dir = os.path.join(app.config['UPLOAD_FOLDER'], model.id)
            converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], model.id)
            
            try:
                if os.path.exists(model_dir):
                    shutil.rmtree(model_dir)
                if os.path.exists(converted_dir):
                    shutil.rmtree(converted_dir)
            except Exception as e:
                app.logger.error(f"Error deleting files for model {model.id}: {e}")
            
            # Delete from database
            db.session.delete(model)
        
        db.session.commit()
        return jsonify({'success': True, 'message': f'Successfully deleted {len(models)} models'})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting models: {str(e)}")
        return jsonify({'success': False, 'message': str(e)})

@app.route('/create_folder', methods=['POST'])
@login_required
def create_folder():
    try:
        folder_name = request.form.get('folder_name')
        parent_id = request.form.get('parent_id')
        
        if not folder_name:
            flash('Folder name is required', 'error')
            return redirect(url_for('my_models'))

        # Convert parent_id to int if it exists, otherwise None
        parent_id = int(parent_id) if parent_id else None
        
        # Create a URL-friendly slug from the folder name
        slug = slugify(folder_name)
        
        # Check if folder with same name exists in the same parent
        existing_folder = Folder.query.filter_by(
            name=folder_name,
            parent_id=parent_id,
            user_id=current_user.id
        ).first()
        
        if existing_folder:
            flash('A folder with this name already exists', 'error')
            return redirect(url_for('my_models', folder_id=parent_id) if parent_id else url_for('my_models'))
        
        new_folder = Folder(
            name=folder_name,
            slug=slug,
            parent_id=parent_id,
            user_id=current_user.id
        )
        
        db.session.add(new_folder)
        db.session.commit()
        
        flash('Folder created successfully', 'success')
        return redirect(url_for('my_models', folder_id=parent_id) if parent_id else url_for('my_models'))
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating folder: {str(e)}")
        flash('An error occurred while creating the folder', 'error')
        return redirect(url_for('my_models'))

def delete_folder_recursive(folder):
    # First, recursively delete all subfolders
    for subfolder in Folder.query.filter_by(parent_id=folder.id).all():
        delete_folder_recursive(subfolder)
    
    # Delete all models in this folder
    UserModel.query.filter_by(folder_id=folder.id).update({'folder_id': None})
    
    # Delete the folder itself
    db.session.delete(folder)

@app.route('/delete_folder/<int:folder_id>', methods=['POST'])
@login_required
def delete_folder(folder_id):
    try:
        folder = Folder.query.get_or_404(folder_id)
        
        # Check if folder belongs to current user
        if folder.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Recursively delete folder and its contents
        delete_folder_recursive(folder)
        
        db.session.commit()
        app.logger.info(f"Folder {folder_id} deleted successfully")
        return jsonify({'success': True, 'message': 'Folder deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting folder {folder_id}: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/move_model', methods=['POST'])
@login_required
def move_model():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data received'}), 400
            
        model_id = data.get('model_id')
        folder_id = data.get('folder_id')
        
        if not model_id:
            return jsonify({'success': False, 'error': 'Model ID is required'}), 400
            
        # Convert folder_id to int if it exists, otherwise None
        folder_id = int(folder_id) if folder_id else None
        
        # Get the model
        model = UserModel.query.get_or_404(model_id)
        
        # Check if the model belongs to the current user
        if model.user_id != current_user.id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
            
        # If folder_id is provided, check if the folder exists and belongs to the user
        if folder_id:
            folder = Folder.query.get_or_404(folder_id)
            if folder.user_id != current_user.id:
                return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Update model's folder
        model.folder_id = folder_id
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Model moved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error moving model: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/move_selected_models', methods=['POST'])
@login_required
def move_selected_models():
    try:
        data = request.get_json()
        model_ids = data.get('model_ids', [])
        folder_id = data.get('folder_id')

        if not model_ids:
            return jsonify({'success': False, 'error': 'No models selected'}), 400

        # Verify folder exists and belongs to user if folder_id is provided
        if folder_id:
            folder = Folder.query.get_or_404(folder_id)
            if folder.user_id != current_user.id:
                return jsonify({'success': False, 'error': 'Unauthorized'}), 403

        # Move all selected models
        models = UserModel.query.filter(
            UserModel.id.in_(model_ids),
            UserModel.user_id == current_user.id
        ).all()

        if len(models) != len(model_ids):
            return jsonify({'success': False, 'error': 'Some models were not found or do not belong to you'}), 403

        for model in models:
            model.folder_id = folder_id

        db.session.commit()
        return jsonify({
            'success': True,
            'message': f'Successfully moved {len(models)} models'
        })

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error moving models: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to move models'}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'Dosya boyutu çok büyük. Maksimum dosya boyutu 100MB.'}), 413

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Sunucu hatası. Lütfen daha sonra tekrar deneyin.'}), 500

def check_model_files():
    """Check if model files exist and update database accordingly."""
    try:
        session = Session(db.engine)
        models = session.query(UserModel).all()
        
        for model in models:
            # Check if model files exist
            converted_dir = os.path.join(app.config['CONVERTED_FOLDER'], model.id)
            upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], model.id)
            
            # If neither directory exists, delete the model from database
            if not os.path.exists(converted_dir) and not os.path.exists(upload_dir):
                logger.info(f"Files for model {model.id} not found, removing from database")
                session.delete(model)
        
        session.commit()
    except Exception as e:
        logger.error(f"Error checking model files: {str(e)}")
        session.rollback()

@app.before_request
def before_request():
    """Run before each request to ensure database is in sync with files."""
    if request.endpoint == 'my_models':
        check_model_files()

if __name__ == '__main__':
    if init_app_dependencies():
        app.logger.info("Dependencies initialized successfully")
        # Railway/Heroku için PORT environment variable
        port = int(os.environ.get('PORT', 5000))
        app.run(host='0.0.0.0', port=port, debug=app.config.get('DEBUG', True))
    else:
        app.logger.error("Failed to initialize dependencies")
