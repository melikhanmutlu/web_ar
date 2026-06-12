from datetime import datetime
import os
import json
from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    make_response,
    abort,
)
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.utils import secure_filename
import logging
import shutil
import subprocess
import threading
from models import db, User, UserModel, Folder, ModelVersion, ModelLike, ModelSave, ModelHotspot, CameraView, AIGenerationJob, ConversionJob
from auth import auth
import re
import traceback
import uuid
from flask_migrate import Migrate
from config import *
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
import qrcode
from slugify import slugify
import trimesh
from converters import OBJConverter, FBXConverter, STLConverter
from converters.glb_optimizer import optimize_glb
from converters.glb_quality import finalize_glb
import numpy as np
from glb_modifier import modify_glb, normalize_model_to_center
from mesh_slicer import slice_mesh, get_mesh_bounds
from pygltflib import GLTF2
import time
from version_manager import (
    create_version,
    get_version_history,
    restore_version,
    delete_version,
)

app = Flask(__name__)
app.config.from_object("config")


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

# Database URI comes from config.py (DATABASE_URL on Railway -> postgres,
# local fallback sqlite). The old hardcoded "sqlite:///app.db" here silently
# overrode DATABASE_URL, so production never actually used postgres.
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
    # SQLite: thread-safe connect args; postgres pool options don't apply
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "connect_args": {"check_same_thread": False}
    }

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["CONVERTED_FOLDER"] = CONVERTED_FOLDER
app.config["TEMP_FOLDER"] = TEMP_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB limit
app.config["ALLOWED_EXTENSIONS"] = {"obj", "stl", "fbx", "glb", "gltf"}

# Constants
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
CONVERTED_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "converted")
TEMP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp")
QR_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qr_codes")
ALLOWED_EXTENSIONS = {"obj", "stl", "fbx", "glb", "gltf"}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB limit

# Initialize extensions
db.init_app(app)
migrate = Migrate(app, db)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# Rate limiting — keyed by user id when logged in, client IP otherwise.
# Default storage is in-process memory (fine for the single-worker gunicorn
# setup); point RATELIMIT_STORAGE_URI at redis:// when scaling out.
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


def _rate_limit_key():
    try:
        if current_user.is_authenticated:
            return f"user:{current_user.id}"
    except Exception:
        pass
    return get_remote_address()


limiter = Limiter(
    key_func=_rate_limit_key,
    app=app,
    default_limits=[],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(
        {"success": False, "error": f"Rate limit exceeded: {e.description}"}
    ), 429


def check_model_mutation_allowed(model_id, require_exists=True):
    """Owner guard for model mutation endpoints.

    Anonymous models (user_id is None) stay editable by anyone — anonymous
    usage is an intentional product decision. Models owned by a user can only
    be mutated by that user. Returns a (response, status) tuple to return from
    the view, or None when the mutation is allowed.
    """
    model = UserModel.query.get(model_id)
    if model is None:
        if require_exists:
            return jsonify({"success": False, "error": "Model not found"}), 404
        return None
    if model.user_id is not None:
        is_owner = (
            current_user.is_authenticated and current_user.id == model.user_id
        )
        if not is_owner:
            return jsonify(
                {"success": False, "error": "Forbidden: you do not own this model"}
            ), 403
    return None


# Register blueprints
app.register_blueprint(auth)

# Configure logging FIRST (before database operations)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Database bootstrap (migration-aware).
# Once an alembic_version table exists, Alembic (flask db upgrade in the
# deploy start command) owns the schema and this block does nothing. For
# fresh or legacy DBs it bootstraps via create_all and then stamps the
# alembic baseline so future `flask db upgrade` runs start from the right
# revision. SKIP_DB_BOOTSTRAP=1 disables it entirely (used when generating
# migrations against an empty DB).
if os.environ.get("SKIP_DB_BOOTSTRAP", "").lower() not in ("1", "true", "yes"):
    with app.app_context():
        try:
            from sqlalchemy import inspect as _sa_inspect

            _inspector = _sa_inspect(db.engine)
            _has_alembic = _inspector.has_table("alembic_version")
        except Exception as e:
            logger.warning(f"DB inspection failed: {e}")
            _has_alembic = False

        if _has_alembic:
            logger.info("Alembic owns the schema (alembic_version found); skipping create_all")
        else:
            try:
                db.create_all()
            except Exception as e:
                # "table already exists" is expected under multi-worker gunicorn
                # (race between workers calling create_all at startup).
                if "already exists" in str(e).lower():
                    logger.debug(f"DB init (expected race): {e}")
                else:
                    logger.warning(f"Database initialization warning: {e}")

            # Legacy column adds for old sqlite DBs created before these fields
            if db.engine.dialect.name == "sqlite":
                try:
                    with db.engine.connect() as conn:
                        result = conn.execute(db.text("PRAGMA table_info(user_model)"))
                        columns = [row[1] for row in result]

                        if "original_dimensions" not in columns:
                            conn.execute(
                                db.text(
                                    "ALTER TABLE user_model ADD COLUMN original_dimensions TEXT"
                                )
                            )
                            conn.commit()
                            logger.info("Added original_dimensions column")

                        if "cumulative_scale" not in columns:
                            conn.execute(
                                db.text(
                                    "ALTER TABLE user_model ADD COLUMN cumulative_scale REAL DEFAULT 1.0"
                                )
                            )
                            conn.commit()
                            logger.info("Added cumulative_scale column")
                except Exception as migration_error:
                    logger.error(f"Migration error: {migration_error}")

            # Stamp the baseline so `flask db upgrade` treats this schema as current
            try:
                _migrations_dir = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), "migrations"
                )
                if os.path.isdir(_migrations_dir):
                    from flask_migrate import stamp as _alembic_stamp

                    _alembic_stamp()
                    logger.info("Alembic: stamped bootstrapped DB at head")
            except Exception as e:
                logger.warning(f"Alembic stamp skipped: {e}")


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in app.config["ALLOWED_EXTENSIONS"]
    )


def get_file_info(file_path):
    """Get detailed information about the uploaded file."""
    try:
        file_size = os.path.getsize(file_path)
        file_ext = os.path.splitext(file_path)[1].lower()

        info = {
            "size": file_size,
            "extension": file_ext,
            "vertices": 0,
            "faces": 0,
            "is_watertight": False,
            "bounds": None,
            "is_binary": False,
        }

        # For 3D models, get additional information
        if file_ext[1:] in app.config["ALLOWED_EXTENSIONS"]:
            try:
                # For FBX files, we can't get mesh information directly
                if file_ext == ".fbx":
                    logger.info(
                        "FBX file detected - mesh information will be updated after conversion"
                    )
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
                    info["vertices"] = total_vertices
                    info["faces"] = total_faces
                else:
                    info["vertices"] = len(mesh.vertices)
                    info["faces"] = len(mesh.faces)
                    info["is_watertight"] = mesh.is_watertight
                    info["bounds"] = (
                        mesh.bounds.tolist() if hasattr(mesh, "bounds") else None
                    )
                    if hasattr(mesh, "is_binary"):
                        info["is_binary"] = mesh.is_binary
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
        hex_color = color_hex.lstrip("#")
        # Ensure hex string is valid (6 digits)
        if len(hex_color) != 6:
            logger.error(f"Invalid hex color format: {color_hex}")
            return False
        try:
            rgb_255 = [int(hex_color[i : i + 2], 16) for i in (0, 2, 4)]
        except ValueError:
            logger.error(f"Invalid characters in hex color: {color_hex}")
            return False

        rgba_255 = rgb_255 + [255]  # Add Alpha channel (fully opaque)
        logger.info(f"Applying RGBA(0-255) values: {rgba_255}")

        # Ensure the mesh has faces
        if not hasattr(mesh, "faces") or mesh.faces is None or len(mesh.faces) == 0:
            logger.warning("Mesh has no faces, cannot apply face colors.")
            # Depending on workflow, might want to return True or False
            # If color should always be applied if possible, False is better
            return False

        # Ensure the mesh has a visual component, creating one if necessary
        if not hasattr(mesh, "visual") or mesh.visual is None:
            # If no visual exists, create a basic ColorVisuals
            mesh.visual = trimesh.visual.ColorVisuals(mesh=mesh)
            logger.info("Created new ColorVisuals for mesh.")
        elif not isinstance(mesh.visual, trimesh.visual.ColorVisuals):
            # If visual exists but isn't ColorVisuals, overwrite it cautiously
            # This might discard existing texture/material info, which is intended here
            logger.warning(
                "Overwriting existing non-ColorVisuals visual data with ColorVisuals."
            )
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
        logger.warning(
            "apply_size_limit called with unsupported type. Skipping scaling."
        )
        return mesh  # Return unmodified if not Scene or Trimesh

    # Calculate current dimensions
    dimensions = bounds[1] - bounds[0]
    # Handle potential NaN or Inf values in dimensions gracefully
    dimensions = np.nan_to_num(dimensions, nan=0.0, posinf=0.0, neginf=0.0)
    max_dimension = np.max(dimensions)

    # Calculate scale factor ONLY if target size and current size are positive
    if (
        max_size_meters <= 0 or max_dimension <= 1e-9
    ):  # Use epsilon for float comparison
        logger.warning(
            f"Skipping scaling: Target size ({max_size_meters:.4f}m) or model dimension "
            f"({max_dimension:.4f}m) is non-positive or too small."
        )
        return mesh  # Return the original mesh without scaling

    scale_factor = max_size_meters / max_dimension
    logger.info(
        f"Calculated scale factor: {scale_factor:.4f} (Target: {max_size_meters:.4f}m / Current: {max_dimension:.4f}m)"
    )

    # Define the scaling transformation matrix
    # Using trimesh.transformations is generally preferred and clearer
    # Scaling is applied relative to the mesh's centroid to avoid shifting
    center = mesh.centroid
    T_neg = trimesh.transformations.translation_matrix(-center)
    S = trimesh.transformations.scale_matrix(
        scale_factor, origin=None
    )  # Scale uniformly
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
        pass  # Allow process to continue with potentially unscaled/partially scaled mesh

    return mesh


def convert_model_new(input_file, output_path=None, color=None):
    """Convert 3D model to GLB format using converter classes with optional color."""
    try:
        if output_path is None:
            output_path = os.path.join(
                app.config["CONVERTED_FOLDER"],
                os.path.splitext(os.path.basename(input_file))[0] + ".glb",
            )

        file_ext = os.path.splitext(input_file)[1].lower()

        # Select appropriate converter class
        if file_ext == ".fbx":
            converter = FBXConverter()
        elif file_ext == ".stl":
            converter = STLConverter()
        elif file_ext == ".obj":
            converter = OBJConverter()
        elif file_ext in (".glb", ".gltf"):
            # Direct copy/re-export for GLB/GLTF
            try:
                scene = trimesh.load(input_file)
                if color:
                    apply_color_to_scene(scene, color)
                scene.export(output_path)
                return output_path
            except Exception as e:
                logger.error(f"Error processing GLB/GLTF: {str(e)}")
                return None
        else:
            logger.error(f"Unsupported format: {file_ext}")
            return None

        if not converter.validate(input_file):
            logger.error(f"Validation failed for {file_ext}")
            return None

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        success = converter.convert(input_file, output_path, color=color) if color else converter.convert(input_file, output_path)

        if success and os.path.exists(output_path):
            return output_path

        logger.error(f"Conversion failed for {file_ext}")
        return None

    except Exception as e:
        logger.error(f"Error in convert_model_new: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return None


def convert_stl_to_glb(stl_path, output_path):
    """DEPRECATED: Use STLConverter class instead. Kept for backward compatibility."""
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
    """DEPRECATED: Use FBXConverter class instead. Kept for backward compatibility."""
    try:
        logger.info("Starting FBX to GLB conversion")
        # Platform-aware FBX2glTF path
        import platform

        if platform.system() == "Windows":
            fbx2gltf_path = os.path.join(TOOLS_DIR, "FBX2glTF.exe")
        else:
            fbx2gltf_path = os.path.join(TOOLS_DIR, "FBX2glTF")

        # Ensure output directory exists
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Construct and run the conversion command
        cmd = [
            fbx2gltf_path,
            "--binary",
            "--input",
            fbx_path,
            "--output",
            output_path,
            # "--draco",  # Disabled: Draco compression corrupts textures and geometry
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
    """DEPRECATED: Use OBJConverter class instead. Kept for backward compatibility."""
    try:
        logger.info("Starting OBJ to GLB conversion")

        # Create OBJ converter
        converter = OBJConverter()

        # Validate file
        if not converter.validate(obj_path):
            logger.error("OBJ file validation error")
            return None

        # Process MTL file
        if "mtl" in request.files:
            mtl_file = request.files["mtl"]
            if mtl_file.filename:
                mtl_path = os.path.join(
                    os.path.dirname(obj_path), secure_filename(mtl_file.filename)
                )
                mtl_file.save(mtl_path)
                converter.set_material_file(mtl_path)
                logger.info(f"MTL file saved: {mtl_path}")

        # Process texture files
        if "textures" in request.files:
            textures = request.files.getlist("textures")
            for texture in textures:
                if texture.filename:
                    texture_path = os.path.join(
                        os.path.dirname(obj_path), secure_filename(texture.filename)
                    )
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
    """DEPRECATED: Use convert_model_new() instead. Kept for backward compatibility."""
    try:
        file_ext = os.path.splitext(file_path)[1].lower()[
            1:
        ]  # Get extension without dot
        output_path = os.path.join(
            app.config["CONVERTED_FOLDER"],
            os.path.splitext(os.path.basename(file_path))[0] + ".glb",
        )

        if file_ext not in ALLOWED_EXTENSIONS:
            logger.error(f"Unsupported file format: {file_ext}")
            return None

        # Create appropriate converter based on file extension
        if file_ext == "obj":
            converter = OBJConverter()
        elif file_ext == "stl":
            converter = STLConverter()
        elif file_ext == "fbx":
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
    prefixes = ["indoor_", "indoor"]
    for prefix in prefixes:
        if name.startswith(prefix):
            name = name[len(prefix) :]
    # Remove underscores and spaces
    name = name.replace("_", "").replace(" ", "")
    return name


def extract_texture_references(mtl_path):
    """Extract texture file references from MTL file."""
    texture_files = set()
    if not mtl_path or not os.path.exists(mtl_path):
        return texture_files

    try:
        with open(mtl_path, "r") as f:
            for line in f:
                line = line.strip().lower()
                # Check for common texture map types
                if any(line.startswith(prefix) for prefix in ["map_", "bump", "disp"]):
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
        with open(mtl_path, "r") as f:
            mtl_content = f.read()

        # Create textures directory in temp folder
        temp_textures_dir = os.path.join(temp_dir, "textures")
        os.makedirs(temp_textures_dir, exist_ok=True)

        # Process each texture reference
        modified_content = []
        for line in mtl_content.splitlines():
            if any(
                line.strip().lower().startswith(prefix)
                for prefix in ["map_", "bump", "disp"]
            ):
                parts = line.strip().split()
                if len(parts) >= 2:
                    texture_name = os.path.basename(parts[-1]).lower()
                    # Case-insensitive texture lookup
                    if texture_name in available_textures:
                        # Copy and reference available texture with original case
                        original_name = available_textures[texture_name]
                        src_path = os.path.join(
                            app.config["UPLOAD_FOLDER"], original_name
                        )
                        dst_path = os.path.join(temp_textures_dir, original_name)
                        shutil.copy2(src_path, dst_path)
                        # Update path in MTL
                        parts[-1] = f"textures/{original_name}"
                        modified_content.append(" ".join(parts))
                        app.logger.info(f"Copied texture file: {original_name}")
                    else:
                        # Skip missing texture line and log warning
                        app.logger.warning(
                            f"Texture file not found in map: {texture_name}"
                        )
                        continue
            else:
                modified_content.append(line)

        # Write modified MTL
        temp_mtl = os.path.join(temp_dir, os.path.basename(mtl_path))
        with open(temp_mtl, "w") as f:
            f.write("\n".join(modified_content))

        app.logger.info("Updated MTL content:\n" + "\n".join(modified_content))
        return temp_mtl

    except Exception as e:
        app.logger.error(f"Error processing MTL file: {str(e)}")
        return None


def fix_mtl_paths(content, texture_map):
    """Fix texture paths in MTL content to use only filenames."""
    app.logger.info(f"Original MTL content:\n{content}")

    # Split content into lines
    lines = content.split("\n")
    updated_lines = []

    for line in lines:
        if line.strip().startswith("map_Kd"):
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

    updated_content = "\n".join(updated_lines)
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
        base_url = request.host_url.rstrip("/")  # Get base URL without trailing slash
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
        qr_path = os.path.join(app.config["CONVERTED_FOLDER"], qr_filename)

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
        return "#4CAF50"  # Default green
    if not re.match(r"^#(?:[0-9a-fA-F]{3}){1,2}$", color):
        raise ValueError(
            "Invalid color format. Must be a valid hex color (e.g., #FF0000)"
        )
    return color


def hex_to_rgb(hex_color):
    """Convert hex color string to RGB values (0-1 range)."""
    hex_color = hex_color.lstrip("#")
    return [int(hex_color[i : i + 2], 16) / 255 for i in (0, 2, 4)]


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
                logger.info(
                    f"Model {model.id} ({model.original_filename}) file not found at: {model.file_path}"
                )
                try:
                    # Also try to delete the converted file if it exists
                    converted_path = os.path.join(
                        app.config["CONVERTED_FOLDER"], f"{model.id}.glb"
                    )
                    if os.path.exists(converted_path):
                        os.remove(converted_path)
                        logger.info(f"Deleted converted file: {converted_path}")
                except Exception as e:
                    logger.warning(
                        f"Error deleting converted file for model {model.id}: {str(e)}"
                    )

                # Delete from database
                session.delete(model)
                deleted_count += 1
                logger.info(f"Deleted model {model.id} from database")

        if deleted_count > 0:
            db.session.commit()
            logger.info(
                f"Cleaned up {deleted_count} missing model records from database"
            )
            flash(
                f"{deleted_count} missing model(s) were cleaned up from the database",
                "info",
            )

    except Exception as e:
        logger.error(f"Error cleaning up missing models: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        db.session.rollback()
        flash("Error cleaning up missing models", "error")


def check_node_installed():
    """Check if Node.js is installed."""
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
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
        project_dir = os.path.dirname(os.path.abspath(__file__))
        local_obj2gltf = os.path.join(
            project_dir, "node_modules", "obj2gltf", "bin", "obj2gltf.js"
        )

        if os.path.exists(local_obj2gltf):
            result = subprocess.run(
                ["node", local_obj2gltf, "--version"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                app.logger.info(f"obj2gltf is installed locally: {result.stdout.strip()}")
                return True

        npx_path = shutil.which("npx.cmd") or shutil.which("npx") or "npx"

        # Check if obj2gltf is installed
        result = subprocess.run(
            [npx_path, "obj2gltf", "--version"], capture_output=True, text=True
        )
        if result.returncode == 0:
            app.logger.info(f"obj2gltf is installed: {result.stdout.strip()}")
            return True
        else:
            app.logger.info("Installing obj2gltf globally...")
            npm_path = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
            install_result = subprocess.run(
                [npm_path, "install", "-g", "obj2gltf"], capture_output=True, text=True
            )
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
        os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
        os.makedirs(app.config["CONVERTED_FOLDER"], exist_ok=True)
        os.makedirs(app.config["TEMP_FOLDER"], exist_ok=True)
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


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


def convert_to_usdz(input_glb_path, output_usdz_path):
    """
    Convert GLB to USDZ using Blender script.
    Returns True if successful, False otherwise.
    """
    try:
        logger.info(f"Starting USDZ conversion: {input_glb_path} -> {output_usdz_path}")

        # Path to the blender script
        blender_script = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "tools",
            "blender_usdz_export.py",
        )

        # Check for blender executable
        blender_exec = "blender"
        # On Windows, try to find commonly used paths if not in PATH
        if os.name == "nt":
            possible_paths = [
                r"C:\Program Files\Blender Foundation\Blender 3.6\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.1\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
                r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
            ]
            # Check if 'blender' is in PATH first
            if shutil.which("blender"):
                blender_exec = "blender"
            else:
                for p in possible_paths:
                    if os.path.exists(p):
                        blender_exec = p
                        break

        # Construct command
        cmd = [
            blender_exec,
            "--background",
            "--python",
            blender_script,
            "--",
            input_glb_path,
            output_usdz_path,
        ]

        logger.info(f"Running Blender command: {cmd}")

        # Run conversion
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        if process.returncode == 0 and os.path.exists(output_usdz_path):
            logger.info(f"USDZ conversion successful: {output_usdz_path}")
            return True
        else:
            logger.warning(f"USDZ conversion failed. Return code: {process.returncode}")
            logger.warning(f"Stdout: {process.stdout}")
            logger.warning(f"Stderr: {process.stderr}")
            return False

    except Exception as e:
        logger.error(f"Error during USDZ conversion: {e}")
        return False


def convert_usdz_async(model_id, input_glb_path, output_usdz_path):
    """
    Background task to convert GLB to USDZ and update database.
    This runs in a separate thread to not block the upload response.
    """
    try:
        logger.info(f"[USDZ Async - {model_id}] Starting background USDZ conversion")

        success = convert_to_usdz(input_glb_path, output_usdz_path)

        if success:
            # Update database with USDZ path
            with app.app_context():
                model = UserModel.query.get(model_id)
                if model:
                    model.usdz_filename = output_usdz_path
                    db.session.commit()
                    logger.info(
                        f"[USDZ Async - {model_id}] Database updated with USDZ path"
                    )
                else:
                    logger.warning(
                        f"[USDZ Async - {model_id}] Model not found in database"
                    )
        else:
            logger.warning(f"[USDZ Async - {model_id}] USDZ conversion failed")

    except Exception as e:
        logger.error(f"[USDZ Async - {model_id}] Error in background conversion: {e}")


def refresh_usdz_after_edit(model_id, glb_path):
    """Regenerate the iOS USDZ in the background after model.glb is rewritten.

    Quick Look serves the USDZ (ios-src), not the GLB — without this, scale/
    material/slice edits show up in the viewer and on Android but iPhone AR
    keeps placing the model at its original size and look.
    """
    usdz_path = os.path.join(app.config["CONVERTED_FOLDER"], model_id, "model.usdz")
    try:
        threading.Thread(
            target=convert_usdz_async,
            args=(model_id, glb_path, usdz_path),
            daemon=True,
        ).start()
        logger.info(f"[usdz-refresh - {model_id}] Regeneration thread started")
    except Exception as e:
        logger.error(f"[usdz-refresh - {model_id}] Failed to start thread: {e}")


def generate_thumbnail_async(model_id, input_glb_path, color=None):
    """
    Background task to generate a thumbnail image for a 3D model.
    This runs in a separate thread to not block the upload response.
    """
    try:
        logger.info(
            f"[Thumbnail Async - {model_id}] Starting background thumbnail generation"
        )

        thumbnail_path = os.path.join(
            app.config["CONVERTED_FOLDER"], model_id, "thumbnail.png"
        )

        # If thumbnail already exists, skip
        if os.path.exists(thumbnail_path):
            logger.info(
                f"[Thumbnail Async - {model_id}] Thumbnail already exists, skipping"
            )
            return

        # Try to generate from 3D model using trimesh
        try:
            import trimesh
            import numpy as np
            from PIL import Image, ImageDraw, ImageFont

            # Load mesh
            mesh = trimesh.load(input_glb_path, file_type="glb")

            # Get combined geometry if it's a Scene
            if isinstance(mesh, trimesh.Scene):
                meshes = [
                    g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)
                ]
                if meshes:
                    combined = trimesh.util.concatenate(meshes)
                else:
                    raise ValueError("No meshes found in scene")
            else:
                combined = mesh

            # Create image
            img = Image.new("RGB", (256, 256), color=(30, 30, 40))
            draw = ImageDraw.Draw(img)

            # Try to use default font
            try:
                font = ImageFont.truetype("arial.ttf", 14)
                font_small = ImageFont.truetype("arial.ttf", 10)
            except:
                font = ImageFont.load_default()
                font_small = font

            # Get model name from database
            with app.app_context():
                model = UserModel.query.get(model_id)
                name = model.original_filename[:25] if model else "Model"

            # Draw model name
            draw.text((128, 100), name, fill=(255, 255, 255), font=font, anchor="mm")

            # Draw model stats
            stats = []
            if hasattr(combined, "vertices"):
                stats.append(f"{len(combined.vertices)} vertices")
            if hasattr(combined, "faces"):
                stats.append(f"{len(combined.faces)} faces")

            for i, stat in enumerate(stats):
                draw.text(
                    (128, 130 + i * 20),
                    stat,
                    fill=(150, 160, 180),
                    font=font_small,
                    anchor="mm",
                )

            # Save thumbnail
            img.save(thumbnail_path, "PNG")
            logger.info(
                f"[Thumbnail Async - {model_id}] Thumbnail generated from 3D model"
            )
            return

        except Exception as e:
            logger.warning(
                f"[Thumbnail Async - {model_id}] Failed to generate 3D thumbnail: {e}"
            )

        # Fallback: Generate gradient-based thumbnail
        with app.app_context():
            model = UserModel.query.get(model_id)
            if not model:
                logger.warning(
                    f"[Thumbnail Async - {model_id}] Model not found in database"
                )
                return

            thumb_color = color or model.color or "#667eea"
            name = model.original_filename[:20]
            file_type = model.file_type or "GLB"

            svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
                <defs>
                    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" style="stop-color:{thumb_color};stop-opacity:1" />
                        <stop offset="100%" style="stop-color:{thumb_color}cc;stop-opacity:1" />
                    </linearGradient>
                    <radialGradient id="glow" cx="50%" cy="60%" r="50%">
                        <stop offset="0%" style="stop-color:rgba(255,255,255,0.2);stop-opacity:1" />
                        <stop offset="100%" style="stop-color:rgba(255,255,255,0);stop-opacity:1" />
                    </radialGradient>
                </defs>
                <rect width="256" height="256" fill="url(#bg)"/>
                <rect width="256" height="256" fill="url(#glow)"/>
                <text x="128" y="120" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-size="16" font-weight="bold">
                    {name}
                </text>
                <text x="128" y="145" text-anchor="middle" fill="rgba(255,255,255,0.7)" font-family="Arial, sans-serif" font-size="12">
                    {file_type} Model
                </text>
            </svg>"""

            # Try to convert SVG to PNG
            try:
                import cairosvg

                png_data = cairosvg.svg2png(
                    bytestring=svg_content.encode(), output_width=256, output_height=256
                )

                with open(thumbnail_path, "wb") as f:
                    f.write(png_data)

                logger.info(
                    f"[Thumbnail Async - {model_id}] Thumbnail generated from SVG (PNG)"
                )
            except ImportError:
                # If cairosvg is not available, save SVG
                svg_path = os.path.join(
                    app.config["CONVERTED_FOLDER"], model_id, "thumbnail.svg"
                )
                with open(svg_path, "w") as f:
                    f.write(svg_content)
                logger.info(f"[Thumbnail Async - {model_id}] Thumbnail saved as SVG")
            except Exception as e:
                logger.warning(
                    f"[Thumbnail Async - {model_id}] Failed to convert SVG: {e}"
                )

    except Exception as e:
        logger.error(
            f"[Thumbnail Async - {model_id}] Error in thumbnail generation: {e}"
        )


def cleanup_old_backups(model_dir, max_backups=3):
    """Clean up old backup files, keeping only the most recent ones."""
    try:
        if not os.path.isdir(model_dir):
            return

        backup_files = [
            f
            for f in os.listdir(model_dir)
            if f.startswith("model_backup_") and f.endswith(".glb")
        ]

        if len(backup_files) <= max_backups:
            return

        # Sort by modification time (oldest first)
        backup_files.sort(key=lambda f: os.path.getmtime(os.path.join(model_dir, f)))

        # Remove oldest backups, keep most recent
        for old_backup in backup_files[:-max_backups]:
            old_path = os.path.join(model_dir, old_backup)
            os.remove(old_path)
            logger.info(f"Cleaned up old backup: {old_path}")

    except Exception as e:
        logger.error(f"Error cleaning up backups: {e}")


@app.route("/api/models/<model_id>/usdz_status")
def get_usdz_status(model_id):
    """Check if USDZ file is ready for iOS AR viewing."""
    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        usdz_ready = False
        usdz_filename = None

        if model.usdz_filename and os.path.exists(model.usdz_filename):
            usdz_ready = True
            usdz_filename = os.path.basename(model.usdz_filename)
        else:
            # Also check the converted directory for usdz files
            converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
            if os.path.isdir(converted_dir):
                usdz_files = [
                    f for f in os.listdir(converted_dir) if f.endswith(".usdz")
                ]
                if usdz_files:
                    usdz_ready = True
                    usdz_filename = usdz_files[0]

        return jsonify(
            {"success": True, "usdz_ready": usdz_ready, "usdz_filename": usdz_filename}
        )
    except Exception as e:
        logger.error(f"Error checking USDZ status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/upload", methods=["POST"])
@limiter.limit("30 per hour")
def upload_file():
    """DEPRECATED: Legacy upload route. Use /upload_model instead.
    Kept for backward compatibility with existing tests."""
    try:
        logger.info("Starting upload process")

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        logger.info(f"File object: {file}")

        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not allowed_file(file.filename):
            return jsonify({"error": "File type not allowed"}), 400

        # Generate unique ID
        unique_id = str(uuid.uuid4())
        logger.info(f"Generated unique ID: {unique_id}")

        # Create upload subdirectory
        upload_subdir = os.path.join(app.config["UPLOAD_FOLDER"], unique_id)
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
        use_color_raw = request.form.get("useColor", "false")
        if isinstance(use_color_raw, str):
            use_color = use_color_raw.lower() in ("true", "1", "yes")
        else:
            use_color = bool(use_color_raw)

        color = request.form.get("color", "#4CAF50")
        logger.info(f"Color settings - useColor: {use_color}, color: {color}")

        # Get texture removal setting (for FBX)
        remove_textures_raw = request.form.get("removeTextures")
        remove_textures = (
            remove_textures_raw == "true" if remove_textures_raw else False
        )
        logger.info(f"Remove textures setting: {remove_textures}")

        # Get maximum dimension setting (only if checkbox is checked)
        use_max_dimension_raw = request.form.get("useMaxDimension")
        logger.info(
            f"DEBUG: useMaxDimension raw value: {use_max_dimension_raw}, type: {type(use_max_dimension_raw)}"
        )
        use_max_dimension = (
            use_max_dimension_raw == "true" if use_max_dimension_raw else False
        )
        logger.info(f"DEBUG: useMaxDimension parsed: {use_max_dimension}")

        if use_max_dimension:
            max_dimension = float(request.form.get("maxDimension", "50"))  # Keep in cm
            logger.info(f"Maximum dimension limit enabled: {max_dimension} cm")
        else:
            max_dimension = None  # No scaling
            logger.info(
                f"Maximum dimension limit disabled - model will keep original size"
            )

        # Create converted directory
        converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], unique_id)
        os.makedirs(converted_dir, exist_ok=True)
        output_path = os.path.join(converted_dir, "model.glb")

        # Get file info
        file_info = get_file_info(file_path)

        # Convert based on file type
        if file_extension == ".obj":
            converter = OBJConverter()
            # OBJ is unitless; default 'm' (no scaling) keeps the original behaviour.
            converter.set_source_unit(request.form.get("sourceUnit", "m"))

            # Handle MTL file for OBJ
            if "mtl" in request.files:
                mtl_file = request.files["mtl"]
                if mtl_file and mtl_file.filename:
                    mtl_filename = secure_filename(mtl_file.filename)
                    mtl_path = os.path.join(upload_subdir, mtl_filename)
                    mtl_file.save(mtl_path)
                    converter.set_material_file(mtl_path)
                    logger.info(f"MTL file saved: {mtl_path}")

            # Handle texture files for OBJ
            if "textures" in request.files:
                texture_files = request.files.getlist("textures")
                for texture_file in texture_files:
                    if texture_file and texture_file.filename:
                        texture_filename = secure_filename(texture_file.filename)
                        texture_path = os.path.join(upload_subdir, texture_filename)
                        texture_file.save(texture_path)
                        converter.add_texture_file(texture_path)
                        logger.info(f"Texture file saved: {texture_path}")

        elif file_extension == ".stl":
            converter = STLConverter()
            converter.set_source_unit(request.form.get("sourceUnit", "cm"))
        elif file_extension == ".fbx":
            converter = FBXConverter()
            # Set texture removal for FBX if requested
            if remove_textures:
                converter.remove_textures = True
                logger.info("FBX texture removal enabled")
        else:
            return jsonify({"error": "Unsupported file format"}), 400

        # Set maximum dimension — form değeri cm, converter metre bekliyor
        if max_dimension is not None:
            converter.set_max_dimension(max_dimension / 100.0)

        # Apply color if specified
        if use_color and color:
            success = converter.convert(file_path, output_path, color=color)
        else:
            success = converter.convert(file_path, output_path)

        if not success:
            return jsonify({"error": "Conversion failed"}), 500

        # Save model info to database
        model = UserModel(
            id=unique_id,  # Use the same unique_id generated for the folder
            user_id=current_user.id if current_user.is_authenticated else None,
            filename=output_path,  # Store the full path to the GLB file
            file_size=os.path.getsize(output_path),
            file_type=os.path.splitext(filename)[1][1:],  # Remove the dot
            upload_date=datetime.utcnow(),
            color=color if use_color else None,
        )
        db.session.add(model)
        db.session.commit()
        logger.info(f"Model info saved to database with ID: {unique_id}")

        # Generate QR code
        qr_code_filename = generate_qr_code(unique_id)
        logger.info(f"QR code generated: {qr_code_filename}")

        # Return success response
        viewer_url = url_for("view_model", model_id=unique_id)
        return jsonify(
            {
                "success": True,
                "viewer_url": viewer_url,
                "message": "Model uploaded and converted successfully",
            }
        )

    except Exception as e:
        logger.error(f"Error during upload: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/upload_progress")
def upload_progress():
    """Get the current upload progress."""
    progress = session.get("upload_progress", 0)
    return jsonify({"progress": progress})


@app.route("/upload_model", methods=["POST"])
@limiter.limit("30 per hour")
def upload_model():
    """Upload and convert 3D model. Works with or without login."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    original_filename = secure_filename(file.filename)
    if not allowed_file(original_filename):
        return jsonify({"error": "File type not allowed"}), 400

    temp_dir = None  # Initialize temp_dir
    try:
        # Get form data
        # Handle both string and boolean values for useColor
        use_color_raw = request.form.get("useColor", "false")
        if isinstance(use_color_raw, str):
            use_color = use_color_raw.lower() in ("true", "1", "yes")
        else:
            use_color = bool(use_color_raw)

        color = request.form.get("color", "#4CAF50")
        logger.info(f"Color settings - useColor: {use_color}, color: {color}")

        # Get maximum dimension setting (only if checkbox is checked)
        use_max_dimension_raw = request.form.get("useMaxDimension")
        use_max_dimension = (
            use_max_dimension_raw == "true" if use_max_dimension_raw else False
        )
        logger.info(f"useMaxDimension checkbox: {use_max_dimension}")

        max_dimension = None
        if use_max_dimension:
            max_dimension_str = request.form.get("maxDimension")
            if max_dimension_str:
                try:
                    max_dimension = (
                        float(max_dimension_str) / 100.0
                    )  # Convert cm to meters
                    logger.info(
                        f"Maximum dimension limit enabled: {max_dimension_str} cm ({max_dimension} m)"
                    )
                except ValueError:
                    logger.warning(f"Invalid maxDimension value: {max_dimension_str}")
        else:
            logger.info(
                "Maximum dimension limit disabled - model will keep original size"
            )

        # --- Start: Consistent File Handling Logic ---
        unique_id = str(uuid.uuid4())
        logger.info(f"[upload_model - {unique_id}] Generated unique ID")

        # Define temporary save path for uploaded file
        temp_dir = os.path.join(app.config["TEMP_FOLDER"], unique_id)
        os.makedirs(temp_dir, exist_ok=True)
        temp_file_path = os.path.join(temp_dir, original_filename)

        # Save uploaded file temporarily
        file.save(temp_file_path)
        logger.info(
            f"[upload_model - {unique_id}] Temporary file saved: {temp_file_path}"
        )

        # Get file extension
        file_extension = os.path.splitext(original_filename)[1].lower()

        # Stage OBJ companion files (MTL + textures) next to the OBJ
        mtl_path = None
        texture_paths = []
        if file_extension == ".obj":
            if "mtl" in request.files:
                mtl_file = request.files["mtl"]
                if mtl_file and mtl_file.filename:
                    mtl_filename = secure_filename(mtl_file.filename)
                    mtl_path = os.path.join(temp_dir, mtl_filename)
                    mtl_file.save(mtl_path)
                    logger.info(
                        f"[upload_model - {unique_id}] MTL file saved: {mtl_path}"
                    )
            if "textures" in request.files:
                for texture_file in request.files.getlist("textures"):
                    if texture_file and texture_file.filename:
                        texture_filename = secure_filename(texture_file.filename)
                        texture_path = os.path.join(temp_dir, texture_filename)
                        texture_file.save(texture_path)
                        texture_paths.append(texture_path)
                        logger.info(
                            f"[upload_model - {unique_id}] Texture file saved: {texture_path}"
                        )

        # Build job payload and persist the job. The pipeline itself runs either
        # inline (default) or in worker.py when JOB_QUEUE is enabled.
        payload = {
            "unique_id": unique_id,
            "original_filename": original_filename,
            "client_filename": file.filename,
            "temp_dir": temp_dir,
            "temp_file_path": temp_file_path,
            "file_extension": file_extension,
            "mtl_path": mtl_path,
            "texture_paths": texture_paths,
            "use_color": use_color,
            "color": color,
            "max_dimension": max_dimension,
            "source_unit": request.form.get("sourceUnit"),
            "user_id": current_user.id if current_user.is_authenticated else None,
        }
        job = ConversionJob(
            id=unique_id,
            job_type="upload",
            status="pending",
            payload=payload,
            user_id=payload["user_id"],
        )
        db.session.add(job)
        db.session.commit()

        if JOB_QUEUE_ENABLED:
            # Worker picks it up; frontend polls the status endpoint.
            return jsonify(
                {
                    "success": True,
                    "job_id": unique_id,
                    "status": "pending",
                    "status_url": url_for("upload_job_status", job_id=unique_id),
                }
            ), 202

        def run_local_job(job_id):
            with app.app_context():
                queued_job = ConversionJob.query.get(job_id)
                if queued_job:
                    run_conversion_job(queued_job, allow_retry=False)

        threading.Thread(target=run_local_job, args=(unique_id,), daemon=True).start()
        return jsonify(
            {
                "success": True,
                "job_id": unique_id,
                "status": "pending",
                "status_url": url_for("upload_job_status", job_id=unique_id),
            }
        ), 202

    except Exception as e:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                logger.error(
                    f"[upload_model] Error cleaning up temp directory {temp_dir} during exception: {cleanup_error}"
                )
        logger.error(f"[upload_model] Error in upload_model: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


JOB_QUEUE_ENABLED = os.environ.get("JOB_QUEUE", "false").lower() in (
    "true",
    "1",
    "yes",
)


def update_conversion_progress(job, *, progress=None, stage=None, detail=None):
    payload = dict(job.payload or {})
    if progress is not None:
        payload["progress"] = int(max(0, min(100, progress)))
    if stage is not None:
        payload["stage"] = stage
    if detail is not None:
        payload["detail"] = detail
    job.payload = payload
    flag_modified(job, "payload")
    db.session.commit()


def run_conversion_job(job, allow_retry=True):
    """Run a ConversionJob through the pipeline with status transitions.

    Failure puts the job back to 'pending' while attempts remain (so the
    worker retries), or 'failed' otherwise. Inline callers pass
    allow_retry=False because nothing would re-poll a pending job.
    """
    job.status = "processing"
    job.started_at = datetime.utcnow()
    job.attempts = (job.attempts or 0) + 1
    db.session.commit()
    update_conversion_progress(
        job,
        progress=45,
        stage="Starting conversion",
        detail="The model has been received and the converter is starting.",
    )
    try:
        model_id = _run_upload_pipeline(
            job.payload,
            progress_callback=lambda progress, stage, detail: update_conversion_progress(
                job, progress=progress, stage=stage, detail=detail
            ),
        )
        job.model_id = model_id
        job.status = "completed"
        job.error = None
        job.finished_at = datetime.utcnow()
        db.session.commit()
        update_conversion_progress(
            job,
            progress=100,
            stage="Ready",
            detail="The model is ready for the viewer.",
        )
    except Exception as e:
        db.session.rollback()
        retry = allow_retry and job.attempts < (job.max_attempts or 1)
        job.status = "pending" if retry else "failed"
        job.error = str(e)[:2000]
        job.finished_at = None if retry else datetime.utcnow()
        db.session.commit()
        update_conversion_progress(
            job,
            progress=35 if retry else 100,
            stage="Retrying" if retry else "Failed",
            detail=str(e)[:240],
        )
        logger.error(
            f"[conversion_job - {job.id}] attempt {job.attempts} failed "
            f"({'will retry' if retry else 'giving up'}): {e}"
        )
        if not retry:
            staged_dir = (job.payload or {}).get("temp_dir")
            if staged_dir and os.path.exists(staged_dir):
                try:
                    shutil.rmtree(staged_dir)
                except Exception as cleanup_error:
                    logger.error(
                        f"[conversion_job - {job.id}] staged cleanup failed: {cleanup_error}"
                    )


def _run_upload_pipeline(payload, progress_callback=None):
    """The conversion pipeline: converter -> GLB -> optimize -> normalize ->
    quality pass -> USDZ/thumbnail threads -> UserModel row + initial version.

    Pure function of the payload (no request context) so it can run inline or
    in worker.py. Returns the model id; raises RuntimeError on failure.
    """
    unique_id = payload["unique_id"]
    original_filename = payload["original_filename"]
    temp_dir = payload.get("temp_dir")
    temp_file_path = payload["temp_file_path"]
    file_extension = payload["file_extension"]
    use_color = bool(payload.get("use_color"))
    color = payload.get("color")
    max_dimension = payload.get("max_dimension")
    source_unit = payload.get("source_unit")
    user_id = payload.get("user_id")

    converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], unique_id)
    os.makedirs(converted_dir, exist_ok=True)
    output_path = os.path.join(converted_dir, "model.glb")
    logger.info(
        f"[upload_model - {unique_id}] Defined final output path: {output_path}"
    )

    def report(progress, stage, detail):
        if progress_callback:
            progress_callback(progress, stage, detail)

    try:
        report(48, "Reading source", f"Inspecting {original_filename} and selected conversion options.")
        # Instantiate appropriate converter
        converter = None
        if file_extension == ".obj":
            converter = OBJConverter()
            # OBJ is unitless; default 'm' (no scaling) keeps the original behaviour.
            converter.set_source_unit(source_unit or "m")
            if payload.get("mtl_path"):
                converter.set_material_file(payload["mtl_path"])
            for texture_path in payload.get("texture_paths") or []:
                converter.add_texture_file(texture_path)
        elif file_extension == ".stl":
            converter = STLConverter()
            # STL is unitless — let the user declare the source unit (mm|cm|m),
            # defaulting to cm for backward compatibility.
            converter.set_source_unit(source_unit or "cm")
        elif file_extension == ".fbx":
            converter = FBXConverter()
        elif file_extension in (".glb", ".gltf"):
            # GLB is already the target format; GLTF can be loaded+exported as GLB
            converter = None  # No converter needed, handle directly below

        # Handle GLB/GLTF directly (no converter needed)
        if file_extension in (".glb", ".gltf"):
            try:
                report(56, "Preparing GLB", "Copying or repacking the uploaded glTF asset.")
                if file_extension == ".glb":
                    # GLB is already binary glTF - just copy it
                    shutil.copy2(temp_file_path, output_path)
                    logger.info(
                        f"[upload_model - {unique_id}] GLB file copied directly to {output_path}"
                    )
                else:
                    # GLTF (text-based) needs to be loaded and re-exported as GLB
                    import trimesh as tm_gltf

                    gltf_mesh = tm_gltf.load(temp_file_path)
                    gltf_mesh.export(output_path, file_type="glb")
                    logger.info(
                        f"[upload_model - {unique_id}] GLTF converted to GLB: {output_path}"
                    )
                conversion_success = os.path.exists(output_path)
            except Exception as e:
                logger.error(
                    f"[upload_model - {unique_id}] Error handling GLB/GLTF: {e}",
                    exc_info=True,
                )
                conversion_success = False
        elif not converter:
            raise RuntimeError(f"Unsupported file format: {file_extension}")
        else:
            # Set max dimension if specified (max_dimension is in meters)
            if max_dimension is not None:
                converter.set_max_dimension(max_dimension)

            # Perform conversion
            report(58, "Converting geometry", f"Running {type(converter).__name__} and building the GLB file.")
            logger.info(
                f"[upload_model - {unique_id}] Starting conversion using {type(converter).__name__} for {temp_file_path} to {output_path}"
            )
            conversion_success = converter.convert(
                temp_file_path, output_path, color=color if use_color else None
            )
            logger.info(
                f"[upload_model - {unique_id}] Conversion result: {conversion_success}"
            )

        if not conversion_success or not os.path.exists(output_path):
            logger.error(
                f"[upload_model - {unique_id}] Conversion failed or output file missing for {temp_file_path}"
            )
            errors = getattr(converter, "errors", None) if converter else None
            raise RuntimeError(
                "Conversion failed" + (f": {errors[-1]}" if errors else "")
            )
        else:
            logger.info(
                f"[upload_model - {unique_id}] Conversion successful, output exists: {output_path}"
            )

        # Apply size limit for GLB/GLTF files that bypassed the converter
        if (
            file_extension in (".glb", ".gltf")
            and max_dimension is not None
            and os.path.exists(output_path)
        ):
            report(68, "Scaling model", "Applying the requested maximum dimension limit.")
            logger.info(
                f"[upload_model - {unique_id}] Applying size limit to GLB: {max_dimension}m to {output_path}"
            )
            try:
                import trimesh as tm

                mesh = tm.load(output_path)
                apply_size_limit(
                    mesh, max_dimension
                )  # max_dimension is already in meters
                logger.info(
                    f"[upload_model - {unique_id}] Scaling applied, attempting export..."
                )
                mesh.export(output_path)
                logger.info(
                    f"[upload_model - {unique_id}] Export after scaling successful."
                )
            except Exception as e:
                logger.error(
                    f"[upload_model - {unique_id}] Error scaling GLB model: {str(e)}",
                    exc_info=True,
                )
        else:
            logger.info(
                f"[upload_model - {unique_id}] Scaling handled by converter or not requested."
            )

        # Optional, fail-safe GLB compression (no-op unless GLB_OPTIMIZE=true)
        try:
            report(72, "Optimizing GLB", "Checking compression and viewer compatibility.")
            optimize_glb(output_path)
        except Exception as e:
            logger.warning(
                f"[upload_model - {unique_id}] GLB optimization skipped: {e}"
            )

        # Check file size before saving to DB
        final_file_size = 0
        if os.path.exists(output_path):
            final_file_size = os.path.getsize(output_path)
            logger.info(
                f"[upload_model - {unique_id}] Final file size of {output_path}: {final_file_size} bytes"
            )
        else:
            logger.error(
                f"[upload_model - {unique_id}] CRITICAL: Output file {output_path} does not exist before saving to DB!"
            )
            raise RuntimeError("Processed file missing")

        if final_file_size == 0:
            logger.warning(
                f"[upload_model - {unique_id}] WARNING: Final file size of {output_path} is 0 bytes!"
            )
            # Decide if 0-byte file is an error
            # return jsonify({'error': 'Internal server error: Processed file is empty'}), 500

        # Normalize model to center origin for consistent pivot behavior
        try:
            report(78, "Normalizing pivot", "Centering the model for predictable rotation and viewing.")
            logger.info(
                f"[upload_model - {unique_id}] Normalizing model to center origin"
            )
            gltf = GLTF2().load(output_path)
            gltf = normalize_model_to_center(gltf)
            gltf.save(output_path)
            logger.info(f"[upload_model - {unique_id}] Model normalized and saved")
        except Exception as e:
            logger.error(
                f"[upload_model - {unique_id}] Error normalizing model: {e}",
                exc_info=True,
            )
            # Continue even if normalization fails

        # GLB quality pass: embed stray external textures, guarantee PBR
        # materials, validate (warn-only — never blocks a viewable upload)
        try:
            report(84, "Checking materials", "Embedding textures and validating material settings.")
            quality_search_dirs = [converted_dir]
            if temp_dir:
                quality_search_dirs.append(temp_dir)
            quality_warnings = finalize_glb(output_path, search_dirs=quality_search_dirs)
            for w in quality_warnings:
                logger.warning(f"[upload_model - {unique_id}] GLB quality: {w}")
        except Exception as e:
            logger.warning(f"[upload_model - {unique_id}] GLB quality pass skipped: {e}")

        # --- USDZ Conversion for iOS AR (using Blender) - ASYNC ---
        # Start USDZ conversion in background thread to not block upload response
        usdz_output_path = os.path.join(converted_dir, "model.usdz")
        try:
            report(88, "Preparing AR assets", "Starting background USDZ generation for iOS AR.")
            logger.info(
                f"[upload_model - {unique_id}] Starting ASYNC USDZ conversion in background"
            )
            usdz_thread = threading.Thread(
                target=convert_usdz_async,
                args=(unique_id, output_path, usdz_output_path),
                daemon=True,
            )
            usdz_thread.start()
            logger.info(f"[upload_model - {unique_id}] USDZ conversion thread started")
        except Exception as e:
            logger.error(
                f"[upload_model - {unique_id}] Error starting USDZ conversion thread: {e}"
            )
            # Don't fail the whole upload if USDZ thread fails to start

        # Clean up temporary file and directory
        try:
            if temp_dir:
                shutil.rmtree(temp_dir)
                logger.info(
                    f"[upload_model - {unique_id}] Cleaned up temporary directory: {temp_dir}"
                )
        except Exception as cleanup_error:
            logger.error(
                f"[upload_model - {unique_id}] Error cleaning up temp directory {temp_dir}: {cleanup_error}"
            )

        # --- End: Consistent File Handling Logic ---

        # Calculate model dimensions for database
        model_bounds = None
        report(91, "Measuring model", "Calculating dimensions for the model details panel.")

        # For FBX, try to use original dimensions from converter
        # BUT if scaling was applied, we need to scale the dimensions too!
        if (
            file_extension == ".fbx"
            and hasattr(converter, "original_dimensions")
            and converter.original_dimensions
        ):
            try:
                import json

                orig_dims = converter.original_dimensions

                # Check if scaling was applied
                scale_factor = 1.0
                if hasattr(converter, "max_dimension") and converter.max_dimension > 0:
                    # Scaling was applied - calculate the scale factor
                    orig_max_m = orig_dims["max"]
                    target_max_m = converter.max_dimension
                    scale_factor = target_max_m / orig_max_m
                    logger.info(
                        f"[upload_model - {unique_id}] FBX was scaled: {scale_factor:.4f}x (orig: {orig_max_m:.4f}m -> target: {target_max_m:.4f}m)"
                    )

                # Apply scale factor to dimensions
                x_cm = round(orig_dims["x"] * scale_factor * 100, 2)
                y_cm = round(orig_dims["y"] * scale_factor * 100, 2)
                z_cm = round(orig_dims["z"] * scale_factor * 100, 2)
                max_cm = round(orig_dims["max"] * scale_factor * 100, 2)

                model_bounds = json.dumps(
                    {"extents": [x_cm, y_cm, z_cm], "max": max_cm}
                )
                logger.info(
                    f"[upload_model - {unique_id}] Using FBX dimensions (after scaling): {x_cm} x {y_cm} x {z_cm} cm (max: {max_cm} cm)"
                )
            except Exception as e:
                logger.warning(
                    f"[upload_model - {unique_id}] Could not use original FBX dimensions: {str(e)}"
                )

        # If not FBX or FBX dimensions failed, try from GLB
        if not model_bounds:
            try:
                import trimesh
                import numpy as np
                import json

                mesh = trimesh.load(output_path)
                logger.info(
                    f"[upload_model - {unique_id}] Loaded mesh type: {type(mesh)}"
                )

                # Get extents
                if isinstance(mesh, trimesh.Scene):
                    logger.info(
                        f"[upload_model - {unique_id}] Scene has {len(mesh.geometry)} geometries"
                    )
                    all_vertices = []
                    for geom in mesh.geometry.values():
                        if isinstance(geom, trimesh.Trimesh):
                            all_vertices.append(geom.vertices)

                    if all_vertices:
                        combined_vertices = np.vstack(all_vertices)
                        logger.info(
                            f"[upload_model - {unique_id}] Combined {len(all_vertices)} vertex arrays, total vertices: {len(combined_vertices)}"
                        )
                        min_bounds = combined_vertices.min(axis=0)
                        max_bounds = combined_vertices.max(axis=0)
                        extents = max_bounds - min_bounds
                        logger.info(
                            f"[upload_model - {unique_id}] Extents from vertices: {extents}"
                        )
                    else:
                        bounds = mesh.bounds
                        extents = bounds[1] - bounds[0]
                        logger.info(
                            f"[upload_model - {unique_id}] Extents from scene bounds: {extents}"
                        )
                else:
                    extents = mesh.extents
                    logger.info(
                        f"[upload_model - {unique_id}] Extents from mesh: {extents}"
                    )

                # Convert to cm and store
                if max(extents) > 0.001:
                    x_cm = round(float(extents[0]) * 100, 2)
                    y_cm = round(float(extents[1]) * 100, 2)
                    z_cm = round(float(extents[2]) * 100, 2)
                    max_cm = round(float(max(extents)) * 100, 2)

                    model_bounds = json.dumps(
                        {"extents": [x_cm, y_cm, z_cm], "max": max_cm}
                    )
                    logger.info(
                        f"[upload_model - {unique_id}] Model dimensions: {x_cm} x {y_cm} x {z_cm} cm (max: {max_cm} cm)"
                    )
                else:
                    logger.warning(
                        f"[upload_model - {unique_id}] Extents too small or zero: {extents}"
                    )
            except Exception as e:
                logger.warning(
                    f"[upload_model - {unique_id}] Could not calculate dimensions: {str(e)}"
                )

        # Store original (pre-scaling) dimensions separately from current bounds
        # original_dimensions = dimensions BEFORE any user scaling was applied
        # bounds = current dimensions (after scaling if any)
        original_dims = None
        if (
            hasattr(converter, "original_dimensions")
            and converter.original_dimensions
        ):
            try:
                orig = converter.original_dimensions
                original_dims = {
                    "x": round(orig["x"] * 100, 2),
                    "y": round(orig["y"] * 100, 2),
                    "z": round(orig["z"] * 100, 2),
                    "max": round(orig["max"] * 100, 2),
                }
            except Exception:
                pass
        # Fallback: if no pre-scaling dims available, use current bounds
        if not original_dims and model_bounds:
            try:
                bounds_data = json.loads(model_bounds)
                original_dims = {
                    "x": bounds_data["extents"][0],
                    "y": bounds_data["extents"][1],
                    "z": bounds_data["extents"][2],
                    "max": bounds_data["max"],
                }
            except Exception:
                pass

        # Create model record in database using the unique_id
        # user_id is optional - can be None if user is not logged in
        report(94, "Saving model", "Writing model metadata and version history.")
        model = UserModel(
            id=unique_id,  # Use the same ID as the directory
            user_id=user_id,
            filename=output_path,  # Store the full path to the GLB file
            usdz_filename=None,  # USDZ conversion runs async, will be updated when complete
            file_size=final_file_size,  # Use the checked size
            file_type=os.path.splitext(original_filename)[1][1:],  # Original extension
            upload_date=datetime.utcnow(),
            color=color if use_color else None,
            bounds=model_bounds,  # Store dimensions
            original_dimensions=original_dims,  # Store original dimensions
            cumulative_scale=1.0,  # Initial scale is 1.0
        )
        db.session.add(model)
        db.session.commit()
        logger.info(
            f"[upload_model - {unique_id}] Model info saved to database. User: {user_id if user_id is not None else 'anonymous'}"
        )

        # Create initial version entry
        try:
            create_version(
                model_id=unique_id,
                operation_type="upload",
                operation_details={
                    "original_filename": payload.get("client_filename", original_filename),
                    "file_type": file_extension,
                    "max_dimension": max_dimension,
                },
                comment="Initial upload",
            )
            logger.info(f"[upload_model - {unique_id}] Created initial version entry")
        except Exception as version_error:
            logger.error(
                f"[upload_model - {unique_id}] Failed to create initial version: {version_error}"
            )

        # Generate thumbnail in background thread
        try:
            report(97, "Creating preview", "Starting background thumbnail generation.")
            thumb_thread = threading.Thread(
                target=generate_thumbnail_async,
                args=(unique_id, output_path, color if use_color else None),
                daemon=True,
            )
            thumb_thread.start()
            logger.info(
                f"[upload_model - {unique_id}] Thumbnail generation thread started"
            )
        except Exception as e:
            logger.error(
                f"[upload_model - {unique_id}] Error starting thumbnail generation thread: {e}"
            )

        return unique_id

    except Exception as e:
        # Staged files are NOT deleted here — a retrying worker needs them.
        # run_conversion_job cleans up when it gives up for good.
        logger.error(f"[upload_model - {unique_id}] Pipeline error: {str(e)}")
        logger.error(traceback.format_exc())
        raise


@app.route("/api/upload-jobs/<job_id>", methods=["GET"])
def upload_job_status(job_id):
    """Poll a conversion job. Job ids are unguessable UUIDs; status is safe to
    expose without auth (mirrors the AI generation status endpoint)."""
    job = ConversionJob.query.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job not found"}), 404
    data = job.to_dict()
    data["success"] = True
    payload = job.payload or {}
    data["progress"] = payload.get("progress")
    data["stage"] = payload.get("stage")
    data["detail"] = payload.get("detail")
    data["filename"] = payload.get("client_filename") or payload.get("original_filename")
    if job.status == "completed" and job.model_id:
        data["viewer_url"] = url_for("view_model", model_id=job.model_id)
    return jsonify(data)


@app.route("/convert", methods=["POST"])
def convert():
    try:
        logger.info("Starting model conversion process")
        data = request.get_json()

        if not data or "modelId" not in data:
            logger.warning("No model ID provided")
            return jsonify({"error": "No model ID provided"}), 400

        model_id = data["modelId"]
        selected_color = data.get("selectedColor", "#FFFFFF")

        # Find original file in upload subfirectory
        upload_subdir = os.path.join(app.config["UPLOAD_FOLDER"], model_id)
        if not os.path.isdir(upload_subdir):
            logger.error(f"Upload directory not found: {upload_subdir}")
            return jsonify(
                {"success": False, "error": "Upload directory not found"}
            ), 404

        original_files = os.listdir(upload_subdir)
        if not original_files:
            logger.error("No valid source file found in upload directory")
            return jsonify(
                {"success": False, "error": "No valid source file found"}
            ), 404

        source_file = os.path.join(upload_subdir, original_files[0])

        # Create model-specific directory
        model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
        os.makedirs(model_dir, exist_ok=True)
        output_file = os.path.join(model_dir, "model.glb")

        # Convert the model
        file_ext = os.path.splitext(source_file)[1].lower()
        if not convert_model_new(source_file, output_file, color=selected_color):
            logger.error(f"Model conversion failed for {model_id}")
            return jsonify({"success": False, "error": "Model conversion failed"}), 500

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

        return jsonify(
            {"message": "Model converted successfully", "model_id": model_id}
        ), 200

    except Exception as e:
        logger.error(f"Error in convert: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/view/<model_id>")
def view_model(model_id):
    """View a specific model."""
    app.logger.info(f"Accessing view_model with ID: {model_id}")

    # Check if model exists in database
    model = UserModel.query.get(model_id)
    if not model:
        flash("Model not found", "error")
        return redirect(url_for("index"))

    # Trashed models are not viewable until restored
    if model.deleted_at is not None:
        flash("This model is in the trash. Restore it from My Models to view it.", "error")
        return redirect(url_for("index"))

    # Increment view count
    model.view_count = (model.view_count or 0) + 1
    db.session.commit()

    # Check if converted file exists
    if not model.filename or not os.path.exists(model.filename):
        app.logger.error(f"Converted GLB file not found at path: {model.filename}")
        flash("Converted model file not found", "error")
        return redirect(url_for("index"))

    # Get model dimensions - try database first, then GLB file
    model_dimensions = None

    # First, try to get from database (faster)
    if model.bounds:
        try:
            import json

            bounds_data = json.loads(model.bounds)
            if "extents" in bounds_data:
                db_extents = bounds_data["extents"]
                model_dimensions = {
                    "x": round(float(db_extents[0]), 2),
                    "y": round(float(db_extents[1]), 2),
                    "z": round(float(db_extents[2]), 2),
                    "max": round(float(bounds_data.get("max", max(db_extents))), 2),
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
                        app.logger.info(
                            f"Scene extents from dump(concatenate=True): {extents}"
                        )
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
                            app.logger.info(
                                f"Scene extents from stacked vertices: {extents}"
                            )
            else:
                extents = mesh.extents
                app.logger.info(f"Mesh extents: {extents}")

            # Convert to cm and round to 2 decimal places (show even if zero for FBX debugging)
            model_dimensions = {
                "x": round(float(extents[0]) * 100, 2),
                "y": round(float(extents[1]) * 100, 2),
                "z": round(float(extents[2]) * 100, 2),
                "max": round(float(max(extents)) * 100, 2),
            }
            app.logger.info(f"Model dimensions (cm): {model_dimensions}")

            if max(extents) <= 0.001:
                app.logger.warning(
                    f"Warning: Extents are zero or very small: {extents} - GLB may be corrupted"
                )
        except Exception as e:
            app.logger.error(f"Error getting model dimensions: {str(e)}")
            import traceback

            app.logger.error(traceback.format_exc())

    # Parse the path to get unique_id and actual filename for URL generation
    try:
        full_path = model.filename
        app.logger.info(f"Model full path from DB: {full_path}")
        converted_folder_abs = os.path.abspath(app.config["CONVERTED_FOLDER"])

        if full_path.startswith(converted_folder_abs):
            relative_path = os.path.relpath(full_path, converted_folder_abs)
            # Use os.path.normpath to handle mixed slashes if any, then split
            parts = os.path.normpath(relative_path).split(os.sep)
            if len(parts) == 2:
                model_unique_id = parts[0]
                actual_filename = parts[1]
                app.logger.info(
                    f"Extracted ID: {model_unique_id}, Filename: {actual_filename}"
                )
            else:
                app.logger.error(
                    f"Could not parse unique_id and filename from relative path: {relative_path}"
                )
                raise ValueError(f"Invalid model path structure: {relative_path}")
        else:
            app.logger.error(
                f"Model path {full_path} does not start with converted folder {converted_folder_abs}"
            )
            raise ValueError("Model path is not within the expected converted folder")

        # Check for USDZ file
        usdz_actual_filename = None
        if (
            hasattr(model, "usdz_filename")
            and model.usdz_filename
            and os.path.exists(model.usdz_filename)
        ):
            usdz_actual_filename = os.path.basename(model.usdz_filename)
            app.logger.info(f"Found USDZ file: {usdz_actual_filename}")

    except Exception as e:
        import traceback as tb

        app.logger.error(f"Error parsing model path '{model.filename}': {e}")
        app.logger.error(tb.format_exc())
        flash("Error processing model path.", "error")
        return redirect(url_for("index"))

    # Get last applied rotation from latest version
    applied_rotation = {"x": 0, "y": 0, "z": 0}
    if model.versions:
        latest_version = model.versions[0]  # Already ordered by created_at desc
        if (
            latest_version.operation_details
            and "transform" in latest_version.operation_details
        ):
            transform_details = latest_version.operation_details["transform"]
            if "rotation" in transform_details:
                applied_rotation = transform_details["rotation"]
                app.logger.info(
                    f"Found applied rotation in version {latest_version.version_number}: {applied_rotation}"
                )

    # Social data
    owner_username = model.user.username if model.user else "anonymous"
    like_count = ModelLike.query.filter_by(model_id=model_id).count()
    is_liked = False
    is_saved = False
    if current_user.is_authenticated:
        is_liked = (
            ModelLike.query.filter_by(
                model_id=model_id, user_id=current_user.id
            ).first()
            is not None
        )
        is_saved = (
            ModelSave.query.filter_by(
                model_id=model_id, user_id=current_user.id
            ).first()
            is not None
        )
    else:
        sid = session.get("_id") or session.sid if hasattr(session, "sid") else None
        if sid:
            is_liked = (
                ModelLike.query.filter_by(model_id=model_id, session_id=sid).first()
                is not None
            )

    # Owner's other models for gallery (up to 9, excluding current)
    owner_models = []
    if model.user_id:
        owner_models = (
            UserModel.query.filter(
                UserModel.user_id == model.user_id,
                UserModel.id != model_id,
                UserModel.deleted_at.is_(None),
            )
            .order_by(UserModel.upload_date.desc())
            .limit(9)
            .all()
        )

    # Derive display name
    filename_base = (model.filename.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
                     if model.filename else "Model")
    display_name = model.display_name or filename_base
    is_owner = current_user.is_authenticated and model.user_id == current_user.id

    response = make_response(render_template(
        "view.html",
        model_id=model_id,
        model=model,
        model_unique_id=model_unique_id,
        actual_filename=actual_filename,
        usdz_filename=usdz_actual_filename,
        model_dimensions=model_dimensions,
        cumulative_scale=model.cumulative_scale or 1.0,
        applied_rotation=applied_rotation,
        owner_username=owner_username,
        like_count=like_count,
        is_liked=is_liked,
        is_saved=is_saved,
        owner_models=owner_models,
        display_name=display_name,
        is_owner=is_owner,
    ))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/embed/<model_id>")
def embed_view(model_id):
    """Minimal embed viewer for iframe integration (e-commerce, portfolios)."""
    model = UserModel.query.get(model_id)
    if not model:
        return "Model not found", 404

    if not model.filename or not os.path.exists(model.filename):
        return "Model file not found", 404

    # Parse path
    try:
        full_path = model.filename
        converted_folder_abs = os.path.abspath(app.config["CONVERTED_FOLDER"])
        relative_path = os.path.relpath(full_path, converted_folder_abs)
        parts = os.path.normpath(relative_path).split(os.sep)
        model_unique_id = parts[0]
        actual_filename = parts[1]
    except Exception:
        return "Invalid model path", 500

    # Check USDZ
    usdz_actual_filename = None
    if model.usdz_filename and os.path.exists(model.usdz_filename):
        usdz_actual_filename = os.path.basename(model.usdz_filename)

    # Dimensions
    model_dimensions = None
    if model.bounds:
        try:
            import json
            bounds = json.loads(model.bounds) if isinstance(model.bounds, str) else model.bounds
            extents = bounds.get("extents", [0, 0, 0])
            model_dimensions = {
                "width": round(extents[0], 2),
                "height": round(extents[1], 2),
                "depth": round(extents[2], 2),
            }
        except Exception:
            pass

    return render_template(
        "embed.html",
        model=model,
        model_unique_id=model_unique_id,
        actual_filename=actual_filename,
        usdz_filename=usdz_actual_filename,
        model_dimensions=model_dimensions,
        autoplay=request.args.get("autoplay", "0") == "1",
        ar=request.args.get("ar", "1") != "0",
    )


@app.route("/vr/<model_id>")
def vr_view(model_id):
    """VR viewer page for a specific model using A-Frame."""
    model = UserModel.query.get(model_id)
    if not model:
        flash("Model not found", "error")
        return redirect(url_for("index"))

    if not model.filename or not os.path.exists(model.filename):
        flash("Converted model file not found", "error")
        return redirect(url_for("index"))

    # Parse unique_id and actual_filename from model.filename (same logic as view_model)
    try:
        full_path = model.filename
        converted_folder_abs = os.path.abspath(app.config["CONVERTED_FOLDER"])
        if full_path.startswith(converted_folder_abs):
            relative_path = os.path.relpath(full_path, converted_folder_abs)
            parts = os.path.normpath(relative_path).split(os.sep)
            if len(parts) == 2:
                model_unique_id = parts[0]
                actual_filename = parts[1]
            else:
                raise ValueError(f"Invalid model path structure: {relative_path}")
        else:
            raise ValueError("Model path is not within the expected converted folder")
    except Exception as e:
        app.logger.error(f"VR view: error parsing model path: {e}")
        flash("Error processing model path.", "error")
        return redirect(url_for("index"))

    filename_base = (model.filename.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
                     if model.filename else "Model")
    display_name = model.display_name or filename_base

    response = make_response(render_template(
        "vr.html",
        model_id=model_id,
        model_unique_id=model_unique_id,
        actual_filename=actual_filename,
        display_name=display_name,
    ))
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/models/<model_id>/like", methods=["POST"])
def toggle_like(model_id):
    model = UserModel.query.get_or_404(model_id)
    if current_user.is_authenticated:
        existing = ModelLike.query.filter_by(
            model_id=model_id, user_id=current_user.id
        ).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify(
                {
                    "liked": False,
                    "count": ModelLike.query.filter_by(model_id=model_id).count(),
                }
            )
        like = ModelLike(model_id=model_id, user_id=current_user.id)
    else:
        sid = session.get("_id", str(uuid.uuid4()))
        session["_id"] = sid
        existing = ModelLike.query.filter_by(model_id=model_id, session_id=sid).first()
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return jsonify(
                {
                    "liked": False,
                    "count": ModelLike.query.filter_by(model_id=model_id).count(),
                }
            )
        like = ModelLike(model_id=model_id, session_id=sid)
    db.session.add(like)
    db.session.commit()
    return jsonify(
        {"liked": True, "count": ModelLike.query.filter_by(model_id=model_id).count()}
    )


@app.route("/api/models/<model_id>/save", methods=["POST"])
@login_required
def toggle_save(model_id):
    model = UserModel.query.get_or_404(model_id)
    existing = ModelSave.query.filter_by(
        model_id=model_id, user_id=current_user.id
    ).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({"saved": False})
    save = ModelSave(model_id=model_id, user_id=current_user.id)
    db.session.add(save)
    db.session.commit()
    return jsonify({"saved": True})


@app.route("/api/models/<model_id>/share", methods=["POST"])
def track_share(model_id):
    model = UserModel.query.get_or_404(model_id)
    model.share_count = (model.share_count or 0) + 1
    db.session.commit()
    return jsonify({"shares": model.share_count})


@app.route("/api/models/<model_id>/track-download", methods=["POST"])
def track_download(model_id):
    model = UserModel.query.get_or_404(model_id)
    model.download_count = (model.download_count or 0) + 1
    db.session.commit()
    return jsonify({"downloads": model.download_count})


@app.route("/api/models/<model_id>/metadata", methods=["PATCH"])
@login_required
def update_model_metadata(model_id):
    model = UserModel.query.get_or_404(model_id)
    if model.user_id != current_user.id:
        return jsonify({"error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    if "display_name" in data:
        model.display_name = str(data["display_name"])[:255] or None
    if "description" in data:
        model.description = str(data["description"])[:2000] or None
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/models/<model_id>/bounds")
def get_model_bounds(model_id):
    """Get model bounding box for slicer"""
    try:
        # Get model from database
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        # Check if model file exists
        if not model.filename or not os.path.exists(model.filename):
            return jsonify({"success": False, "error": "Model file not found"}), 404

        # Try to get bounds from database first
        if model.bounds:
            try:
                import json

                bounds_data = json.loads(model.bounds)
                if "min" in bounds_data and "max" in bounds_data:
                    return jsonify(
                        {
                            "success": True,
                            "bounds": {
                                "min": bounds_data["min"],
                                "max": bounds_data["max"],
                                "extents": bounds_data["extents"],
                            },
                        }
                    )
            except Exception as e:
                logger.warning(f"Could not parse bounds from database: {e}")

        # Calculate bounds from GLB file
        try:
            import trimesh

            mesh = trimesh.load(model.filename, force="scene")

            # Get bounds
            if isinstance(mesh, trimesh.Scene):
                bounds = mesh.bounds
            else:
                bounds = mesh.bounds

            # Convert to list and meters
            min_bounds = bounds[0].tolist()
            max_bounds = bounds[1].tolist()
            extents = (bounds[1] - bounds[0]).tolist()

            return jsonify(
                {
                    "success": True,
                    "bounds": {
                        "min": min_bounds,
                        "max": max_bounds,
                        "extents": extents,
                    },
                }
            )

        except Exception as e:
            logger.error(f"Error calculating bounds: {e}")
            return jsonify(
                {"success": False, "error": "Failed to calculate bounds"}
            ), 500

    except Exception as e:
        logger.error(f"Error in get_model_bounds: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# Route to serve converted model files
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


@app.route("/converted_files/<path:unique_id>/<path:filename>")
def serve_converted_file(unique_id, filename):
    # Validate unique_id is a proper UUID to prevent path traversal
    if not _UUID_RE.match(unique_id):
        app.logger.warning(f"Invalid unique_id format rejected: {unique_id}")
        return "Not Found", 404
    directory = os.path.join(app.config["CONVERTED_FOLDER"], unique_id)
    app.logger.info(f"Attempting to serve file: {filename} from directory: {directory}")
    # Basic security check: ensure filename is just a filename, not trying to escape
    if os.path.basename(filename) != filename:
        app.logger.warning(f"Potential unsafe filename detected: {filename}")
        return "Not Found", 404
    try:
        return send_from_directory(directory, filename, as_attachment=False)
    except FileNotFoundError:
        app.logger.error(
            f"File not found in serve_converted_file: {directory}/{filename}"
        )
        return "File not found", 404
    except Exception as e:
        app.logger.error(f"Error serving file: {e}")
        return "Server error", 500


@app.route("/api/thumbnail/<unique_id>", methods=["POST"])
@login_required
def save_viewer_thumbnail(unique_id):
    """Save a screenshot from the viewer as the model thumbnail."""
    model = UserModel.query.get(unique_id)
    if not model or model.user_id != current_user.id:
        return jsonify({"error": "Not authorized"}), 403

    data = request.get_json()
    if not data or not data.get("image"):
        return jsonify({"error": "No image data"}), 400

    try:
        import base64
        import re

        img_data = data["image"]
        # Strip data URL prefix if present
        img_data = re.sub(r"^data:image/\w+;base64,", "", img_data)
        img_bytes = base64.b64decode(img_data)

        thumb_dir = os.path.join(app.config["CONVERTED_FOLDER"], unique_id)
        os.makedirs(thumb_dir, exist_ok=True)
        thumb_path = os.path.join(thumb_dir, "thumbnail.png")

        with open(thumb_path, "wb") as f:
            f.write(img_bytes)

        return jsonify({"success": True})
    except Exception as e:
        logger.error(f"Failed to save viewer thumbnail for {unique_id}: {e}")
        return jsonify({"error": "Failed to save thumbnail"}), 500


@app.route("/thumbnail/<unique_id>")
def serve_thumbnail(unique_id):
    """Serve model thumbnail image, generating one on-the-fly if needed."""
    import io
    import base64

    thumbnail_path = os.path.join(
        app.config["CONVERTED_FOLDER"], unique_id, "thumbnail.png"
    )

    # If thumbnail exists, serve it
    if os.path.exists(thumbnail_path):
        return send_from_directory(
            os.path.join(app.config["CONVERTED_FOLDER"], unique_id), "thumbnail.png"
        )

    # Generate thumbnail on-the-fly
    try:
        model = UserModel.query.get(unique_id)
        if not model:
            return "Model not found", 404

        # Try to generate from 3D model using trimesh
        model_path = os.path.join(
            app.config["CONVERTED_FOLDER"], unique_id, "model.glb"
        )

        if os.path.exists(model_path):
            try:
                import trimesh
                import numpy as np

                # Load mesh
                mesh = trimesh.load(model_path, file_type="glb")

                # Get scene if it's a Scene object
                if isinstance(mesh, trimesh.Scene):
                    # Combine all geometries
                    meshes = [
                        g
                        for g in mesh.geometry.values()
                        if isinstance(g, trimesh.Trimesh)
                    ]
                    if meshes:
                        combined = trimesh.util.concatenate(meshes)
                    else:
                        raise ValueError("No meshes found in scene")
                else:
                    combined = mesh

                # Render using trimesh's built-in rendering
                # Create a simple PNG with model info
                from PIL import Image, ImageDraw, ImageFont

                img = Image.new("RGB", (256, 256), color=(30, 30, 40))
                draw = ImageDraw.Draw(img)

                # Try to use default font
                try:
                    font = ImageFont.truetype("arial.ttf", 14)
                    font_small = ImageFont.truetype("arial.ttf", 10)
                except:
                    font = ImageFont.load_default()
                    font_small = font

                # Draw model name
                name = model.original_filename[:25]
                draw.text(
                    (128, 100), name, fill=(255, 255, 255), font=font, anchor="mm"
                )

                # Draw model stats
                stats = []
                if hasattr(combined, "vertices"):
                    stats.append(f"{len(combined.vertices)} vertices")
                if hasattr(combined, "faces"):
                    stats.append(f"{len(combined.faces)} faces")

                for i, stat in enumerate(stats):
                    draw.text(
                        (128, 130 + i * 20),
                        stat,
                        fill=(150, 160, 180),
                        font=font_small,
                        anchor="mm",
                    )

                # Save thumbnail
                img.save(thumbnail_path, "PNG")
                return send_from_directory(
                    os.path.join(app.config["CONVERTED_FOLDER"], unique_id),
                    "thumbnail.png",
                )

            except Exception as e:
                app.logger.warning(
                    f"Failed to generate 3D thumbnail for {unique_id}: {e}"
                )

        # Fallback: Generate SVG-based gradient thumbnail
        import html as html_module

        color = model.color if model.color else "#667eea"
        name = html_module.escape(model.original_filename[:20])
        file_type = html_module.escape(model.file_type or "GLB")

        svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
            <defs>
                <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
                    <stop offset="0%" style="stop-color:{color};stop-opacity:1" />
                    <stop offset="100%" style="stop-color:{color}cc;stop-opacity:1" />
                </linearGradient>
                <radialGradient id="glow" cx="50%" cy="60%" r="50%">
                    <stop offset="0%" style="stop-color:rgba(255,255,255,0.2);stop-opacity:1" />
                    <stop offset="100%" style="stop-color:rgba(255,255,255,0);stop-opacity:1" />
                </radialGradient>
            </defs>
            <rect width="256" height="256" fill="url(#bg)"/>
            <rect width="256" height="256" fill="url(#glow)"/>
            <text x="128" y="120" text-anchor="middle" fill="white" font-family="Arial, sans-serif" font-size="16" font-weight="bold">
                {name}
            </text>
            <text x="128" y="145" text-anchor="middle" fill="rgba(255,255,255,0.7)" font-family="Arial, sans-serif" font-size="12">
                {file_type} Model
            </text>
        </svg>"""

        # Save SVG and return directly
        try:
            svg_path = os.path.join(
                app.config["CONVERTED_FOLDER"], unique_id, "thumbnail.svg"
            )
            with open(svg_path, "w", encoding="utf-8") as f:
                f.write(svg_content)

            response = app.response_class(
                response=svg_content, status=200, mimetype="image/svg+xml"
            )
            return response
        except Exception as e:
            app.logger.warning(f"Failed to save SVG thumbnail for {unique_id}: {e}")
            response = app.response_class(
                response=svg_content, status=200, mimetype="image/svg+xml"
            )
            return response

    except Exception as e:
        app.logger.error(f"Error generating thumbnail for {unique_id}: {e}")
        return "Error generating thumbnail", 500


TRASH_RETENTION_DAYS = int(os.getenv("TRASH_RETENTION_DAYS", 30))
# Per-user storage quota. 1 GB for everyone for now; when paid plans land
# this becomes a per-plan value (the env var stays as the global default).
STORAGE_QUOTA_BYTES = int(os.getenv("STORAGE_QUOTA_MB", 1024)) * 1024 * 1024


def _purge_expired_trash(user_id):
    """Permanently delete this user's trashed models older than retention."""
    from datetime import timedelta

    cutoff = datetime.utcnow() - timedelta(days=TRASH_RETENTION_DAYS)
    expired = UserModel.query.filter(
        UserModel.user_id == user_id, UserModel.deleted_at < cutoff
    ).all()
    for model in expired:
        for base in (app.config["CONVERTED_FOLDER"], app.config["UPLOAD_FOLDER"]):
            d = os.path.join(base, str(model.id))
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
        db.session.delete(model)
    if expired:
        db.session.commit()
        app.logger.info(f"Purged {len(expired)} expired trash models for user {user_id}")


@app.route("/my_models")
@app.route("/my_models/<folder_id>")
@login_required
def my_models(folder_id=None):
    try:
        _purge_expired_trash(current_user.id)

        live = UserModel.deleted_at.is_(None)
        if folder_id:
            current_folder = Folder.query.get_or_404(folder_id)
            if current_folder.user_id != current_user.id:
                abort(403)
            folders = Folder.query.filter_by(parent_id=folder_id, user_id=current_user.id).all()
            models = UserModel.query.filter(
                UserModel.folder_id == folder_id, UserModel.user_id == current_user.id, live
            ).all()
        else:
            current_folder = None
            folders = Folder.query.filter_by(parent_id=None, user_id=current_user.id).all()
            models = UserModel.query.filter(
                UserModel.folder_id.is_(None), UserModel.user_id == current_user.id, live
            ).all()

        # Per-folder live model counts + up to 4 thumbnail ids for the cover collage
        folder_model_counts = {}
        folder_previews = {}
        for folder in folders:
            folder_q = UserModel.query.filter(UserModel.folder_id == folder.id, live)
            folder_model_counts[folder.id] = folder_q.count()
            folder_previews[folder.id] = [
                m.id for m in folder_q.order_by(UserModel.upload_date.desc()).limit(4).all()
            ]

        # Trash (all folders) — shown only on the root view
        trash_models = []
        if not folder_id:
            trash_models = (
                UserModel.query.filter(
                    UserModel.user_id == current_user.id, UserModel.deleted_at.isnot(None)
                )
                .order_by(UserModel.deleted_at.desc())
                .all()
            )

        # Storage usage across all of the user's models (incl. trash — still on disk)
        storage_used = (
            db.session.query(db.func.coalesce(db.func.sum(UserModel.file_size), 0))
            .filter(UserModel.user_id == current_user.id)
            .scalar()
        )

        return render_template(
            "my_models.html",
            folders=folders,
            models=models,
            current_folder=current_folder,
            folder_model_counts=folder_model_counts,
            folder_previews=folder_previews,
            trash_models=trash_models,
            trash_retention_days=TRASH_RETENTION_DAYS,
            storage_used=storage_used,
            storage_quota=STORAGE_QUOTA_BYTES,
        )
    except Exception as e:
        app.logger.error(f"Error in my_models: {str(e)}")
        return redirect("/")


@app.route("/converted/<path:filename>")
def get_converted_file(filename):
    """Serve converted model files."""
    try:
        # Get model from database
        model = UserModel.query.filter_by(
            filename=os.path.join(app.config["CONVERTED_FOLDER"], filename)
        ).first()
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


@app.route("/download/<model_id>")
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

        file_path = os.path.join(app.config["CONVERTED_FOLDER"], model_id, "model.glb")
        if not os.path.exists(file_path):
            return "Dosya bulunamadı", 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=model.original_filename,
            mimetype="application/octet-stream",
        )
    except Exception as e:
        logger.error(f"Error in download_model: {str(e)}")
        return "Dosya indirilirken bir hata oluştu", 500


@app.route("/api/model-info/<int:model_id>")
@login_required
def get_model_info_api(model_id):
    session = Session(db.engine)
    model = session.get(UserModel, model_id)
    if model.user_id != current_user.id:
        flash("Bu modele erişim izniniz yok.", "error")
        return redirect(url_for("auth.profile"))

    model_info = get_file_info(model.file_path)
    if model_info is None:
        return jsonify({"error": "Model not found"}), 404

    return jsonify(model_info)


@app.route("/api/update-model-color", methods=["POST"])
@login_required
def update_model_color():
    try:
        data = request.get_json()
        model_id = data.get("model_id")
        color = data.get("color")

        if not model_id or not color:
            return jsonify(
                {"success": False, "error": "Missing model_id or color"}
            ), 400

        # Get the model
        model = UserModel.query.get(model_id)
        if not model or model.user_id != current_user.id:
            return jsonify(
                {"success": False, "error": "Model not found or unauthorized"}
            ), 404

        # Update the model's color in database
        model.color = color
        db.session.commit()

        # Find source file in upload directory
        upload_subdir = os.path.join(app.config["UPLOAD_FOLDER"], model_id)
        if not os.path.isdir(upload_subdir):
            return jsonify(
                {"success": False, "error": "Upload directory not found"}
            ), 404

        source_files = os.listdir(upload_subdir)
        if not source_files:
            return jsonify({"success": False, "error": "Source file not found"}), 404

        input_path = os.path.join(upload_subdir, source_files[0])
        output_path = os.path.join(
            app.config["CONVERTED_FOLDER"], model_id, "model.glb"
        )

        # Re-convert the model with the new color
        try:
            convert_model_new(input_path, output_path, color=color)
            return jsonify({"success": True}), 200
        except Exception as e:
            logger.error(f"Error converting model with new color: {str(e)}")
            return jsonify(
                {"success": False, "error": "Failed to update model color"}
            ), 500

    except Exception as e:
        logger.error(f"Error in update_model_color: {str(e)}")
        return jsonify({"success": False, "error": "Server error"}), 500


@app.route("/temp/<filename>")
def get_temp_file(filename):
    """Serve temporary files (like QR codes)."""
    try:
        temp_path = os.path.join(app.config["CONVERTED_FOLDER"], filename)
        if os.path.exists(temp_path):
            return send_file(temp_path)
        else:
            logger.error(f"Temp file not found: {temp_path}")
            return "Dosya bulunamadı", 404
    except Exception as e:
        logger.error(f"Error serving temp file: {str(e)}")
        return str(e), 500


@app.route("/qr/<filename>")
def get_qr_code(filename):
    """Serve QR code files."""
    try:
        return send_from_directory(app.config["CONVERTED_FOLDER"], filename)
    except Exception as e:
        logger.error(f"Error serving QR code: {str(e)}")
        return "QR code not found", 404


@app.route("/delete_model/<string:model_id>", methods=["POST"])
@login_required
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

        # Ownership check: only the model owner can delete it
        if model.user_id != current_user.id:
            logger.warning(
                f"Unauthorized delete attempt: user {current_user.id} tried to delete model {model_id} owned by {model.user_id}"
            )
            return jsonify({"error": "Unauthorized"}), 403

        logger.info(f"Found model: ID={model.id}")

        # Soft delete by default; permanent only when explicitly requested
        # (from the trash UI) or when the model is already in the trash.
        data = request.get_json(silent=True) or {}
        permanent = bool(data.get("permanent")) or model.deleted_at is not None

        if not permanent:
            try:
                model.deleted_at = datetime.utcnow()
                session.commit()
                logger.info(f"Moved model {model_id} to trash")
                return jsonify({"success": True, "trashed": True}), 200
            except Exception as e:
                session.rollback()
                logger.error(f"Database error trashing model {model_id}: {str(e)}")
                return jsonify({"error": "Database error"}), 500

        # Permanent delete: remove files then the row
        try:
            # Delete files in converted folder
            converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], str(model_id))
            if os.path.exists(converted_dir):
                shutil.rmtree(converted_dir)
                logger.info(f"Deleted converted directory: {converted_dir}")

            # Delete files in uploads folder
            upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], str(model_id))
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


@app.route("/delete_all_models", methods=["POST"])
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
                converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], model.id)
                if os.path.exists(converted_dir):
                    shutil.rmtree(converted_dir)
                    logger.info(f"Deleted converted directory: {converted_dir}")

                # Delete files in uploads folder
                upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], model.id)
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
        logger.info(
            f"Deleted {deleted_count} models, failed to delete {failed_count} models"
        )

        if failed_count > 0:
            return jsonify(
                {
                    "message": f"Partially successful: deleted {deleted_count} models, failed to delete {failed_count} models"
                }
            ), 207
        return jsonify({"message": f"Successfully deleted {deleted_count} models"}), 200

    except Exception as e:
        logger.error(f"Error deleting all models: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Error deleting models"}), 500


@app.route("/delete_selected_models", methods=["POST"])
@login_required
def delete_selected_models():
    try:
        data = request.get_json()
        model_ids = data.get("model_ids", [])

        if not model_ids:
            return jsonify({"success": False, "message": "No models selected"})

        # Get all models that belong to the current user
        models = UserModel.query.filter(
            UserModel.id.in_(model_ids), UserModel.user_id == current_user.id
        ).all()

        if not models:
            return jsonify({"success": False, "message": "No valid models found"})

        for model in models:
            # Delete the model files
            model_dir = os.path.join(app.config["UPLOAD_FOLDER"], model.id)
            converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], model.id)

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
        return jsonify(
            {"success": True, "message": f"Successfully deleted {len(models)} models"}
        )
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting models: {str(e)}")
        return jsonify({"success": False, "message": str(e)})


@app.route("/create_folder", methods=["POST"])
@login_required
def create_folder():
    try:
        folder_name = request.form.get("folder_name")
        parent_id = request.form.get("parent_id")

        if not folder_name:
            flash("Folder name is required", "error")
            return redirect(url_for("my_models"))

        # Convert parent_id to int if it exists, otherwise None
        parent_id = int(parent_id) if parent_id else None

        # Create a URL-friendly slug from the folder name
        slug = slugify(folder_name)

        # Check if folder with same name exists in the same parent
        existing_folder = Folder.query.filter_by(
            name=folder_name, parent_id=parent_id, user_id=current_user.id
        ).first()

        if existing_folder:
            flash("A folder with this name already exists", "error")
            return redirect(
                url_for("my_models", folder_id=parent_id)
                if parent_id
                else url_for("my_models")
            )

        new_folder = Folder(
            name=folder_name, slug=slug, parent_id=parent_id, user_id=current_user.id
        )

        db.session.add(new_folder)
        db.session.commit()

        flash("Folder created successfully", "success")
        return redirect(
            url_for("my_models", folder_id=parent_id)
            if parent_id
            else url_for("my_models")
        )

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error creating folder: {str(e)}")
        flash("An error occurred while creating the folder", "error")
        return redirect(url_for("my_models"))


def delete_folder_recursive(folder):
    # First, recursively delete all subfolders
    for subfolder in Folder.query.filter_by(parent_id=folder.id).all():
        delete_folder_recursive(subfolder)

    # Delete all models in this folder
    UserModel.query.filter_by(folder_id=folder.id).update({"folder_id": None})

    # Delete the folder itself
    db.session.delete(folder)


@app.route("/delete_folder/<int:folder_id>", methods=["POST"])
@login_required
def delete_folder(folder_id):
    try:
        folder = Folder.query.get_or_404(folder_id)

        # Check if folder belongs to current user
        if folder.user_id != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403

        # Recursively delete folder and its contents
        delete_folder_recursive(folder)

        db.session.commit()
        app.logger.info(f"Folder {folder_id} deleted successfully")
        return jsonify({"success": True, "message": "Folder deleted successfully"}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error deleting folder {folder_id}: {str(e)}")
        app.logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@app.route("/move_model", methods=["POST"])
@login_required
def move_model():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No JSON data received"}), 400

        model_id = data.get("model_id")
        folder_id = data.get("folder_id")

        if not model_id:
            return jsonify({"success": False, "error": "Model ID is required"}), 400

        # Convert folder_id to int if it exists, otherwise None
        folder_id = int(folder_id) if folder_id else None

        # Get the model
        model = UserModel.query.get_or_404(model_id)

        # Check if the model belongs to the current user
        if model.user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        # If folder_id is provided, check if the folder exists and belongs to the user
        if folder_id:
            folder = Folder.query.get_or_404(folder_id)
            if folder.user_id != current_user.id:
                return jsonify({"success": False, "error": "Unauthorized"}), 403

        # Update model's folder
        model.folder_id = folder_id
        db.session.commit()

        return jsonify({"success": True, "message": "Model moved successfully"}), 200

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error moving model: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/restore_model/<string:model_id>", methods=["POST"])
@login_required
def restore_model(model_id):
    """Bring a model back from the trash."""
    try:
        model = UserModel.query.get_or_404(model_id)
        if model.user_id != current_user.id:
            return jsonify({"error": "Unauthorized"}), 403
        if model.deleted_at is None:
            return jsonify({"success": True, "message": "Model is not in trash"}), 200
        model.deleted_at = None
        # Its folder may have been deleted while the model sat in trash
        if model.folder_id and not Folder.query.get(model.folder_id):
            model.folder_id = None
        db.session.commit()
        return jsonify({"success": True}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error restoring model {model_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route("/rename_folder/<int:folder_id>", methods=["POST"])
@login_required
def rename_folder(folder_id):
    try:
        folder = Folder.query.get_or_404(folder_id)
        if folder.user_id != current_user.id:
            return jsonify({"success": False, "error": "Unauthorized"}), 403

        data = request.get_json(silent=True) or {}
        new_name = (data.get("name") or "").strip()[:100]
        if not new_name:
            return jsonify({"success": False, "error": "Folder name is required"}), 400

        duplicate = Folder.query.filter(
            Folder.name == new_name,
            Folder.parent_id == folder.parent_id,
            Folder.user_id == current_user.id,
            Folder.id != folder.id,
        ).first()
        if duplicate:
            return jsonify({"success": False, "error": "A folder with this name already exists"}), 409

        folder.name = new_name
        db.session.commit()
        return jsonify({"success": True, "name": folder.name}), 200
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error renaming folder {folder_id}: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/move_selected_models", methods=["POST"])
@login_required
def move_selected_models():
    try:
        data = request.get_json()
        model_ids = data.get("model_ids", [])
        folder_id = data.get("folder_id")

        if not model_ids:
            return jsonify({"success": False, "error": "No models selected"}), 400

        # JS sends folder_id as a string; Integer column needs int (or None)
        folder_id = int(folder_id) if folder_id else None

        # Verify folder exists and belongs to user if folder_id is provided
        if folder_id:
            folder = Folder.query.get_or_404(folder_id)
            if folder.user_id != current_user.id:
                return jsonify({"success": False, "error": "Unauthorized"}), 403

        # Move all selected models
        models = UserModel.query.filter(
            UserModel.id.in_(model_ids), UserModel.user_id == current_user.id
        ).all()

        if len(models) != len(model_ids):
            return jsonify(
                {
                    "success": False,
                    "error": "Some models were not found or do not belong to you",
                }
            ), 403

        for model in models:
            model.folder_id = folder_id

        db.session.commit()
        return jsonify(
            {"success": True, "message": f"Successfully moved {len(models)} models"}
        )

    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Error moving models: {str(e)}")
        return jsonify({"success": False, "error": "Failed to move models"}), 500


@app.errorhandler(413)
def too_large(e):
    return jsonify(
        {"error": "Dosya boyutu çok büyük. Maksimum dosya boyutu 100MB."}
    ), 413


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Sunucu hatası. Lütfen daha sonra tekrar deneyin."}), 500


def check_model_files():
    """Check if model files exist and update database accordingly."""
    try:
        session = Session(db.engine)
        models = session.query(UserModel).all()

        for model in models:
            # Check if model files exist
            converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], model.id)
            upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], model.id)

            # If neither directory exists, delete the model from database
            if not os.path.exists(converted_dir) and not os.path.exists(upload_dir):
                logger.info(
                    f"Files for model {model.id} not found, removing from database"
                )
                session.delete(model)

        session.commit()
    except Exception as e:
        logger.error(f"Error checking model files: {str(e)}")
        session.rollback()


@app.before_request
def before_request():
    """Run before each request to ensure database is in sync with files."""
    if request.endpoint == "my_models":
        check_model_files()


@app.route("/apply_modifications", methods=["POST"])
def apply_modifications():
    """Apply material and transform modifications to GLB model"""
    try:
        data = request.json
        model_id = data.get("model_id")
        modifications = data.get("modifications")

        if not model_id or not modifications:
            return jsonify(
                {"success": False, "error": "Missing model_id or modifications"}
            ), 400

        logger.info(f"[apply_modifications] Model ID: {model_id}")
        logger.info(f"[apply_modifications] Modifications: {modifications}")

        # Get original GLB path
        original_path = os.path.join(
            app.config["CONVERTED_FOLDER"], model_id, "model.glb"
        )

        if not os.path.exists(original_path):
            logger.error(f"Original GLB not found: {original_path}")
            return jsonify({"success": False, "error": "Original model not found"}), 404

        # Create output filename with timestamp
        timestamp = int(time.time())
        output_filename = f"modified_{timestamp}.glb"
        output_path = os.path.join(
            app.config["CONVERTED_FOLDER"], model_id, output_filename
        )

        logger.info(f"[apply_modifications] Input: {original_path}")
        logger.info(f"[apply_modifications] Output: {output_path}")

        # Apply modifications
        success = modify_glb(original_path, output_path, modifications)

        if success:
            download_url = f"/download_modified/{model_id}/{output_filename}"
            logger.info(f"[apply_modifications] Success! Download URL: {download_url}")
            return jsonify(
                {
                    "success": True,
                    "download_url": download_url,
                    "filename": output_filename,
                }
            )
        else:
            logger.error("[apply_modifications] Modification failed")
            return jsonify({"success": False, "error": "Failed to modify GLB"}), 500

    except Exception as e:
        logger.error(f"[apply_modifications] Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/download_modified/<model_id>/<filename>")
def download_modified(model_id, filename):
    """Download modified GLB file"""
    try:
        directory = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
        logger.info(f"[download_modified] Serving {filename} from {directory}")

        if not os.path.exists(os.path.join(directory, filename)):
            logger.error(f"File not found: {os.path.join(directory, filename)}")
            return "File not found", 404

        return send_from_directory(
            directory,
            filename,
            as_attachment=True,
            download_name=f"modified_model_{int(time.time())}.glb",
        )
    except Exception as e:
        logger.error(f"[download_modified] Error: {e}", exc_info=True)
        return str(e), 500


@app.route("/get_model_dimensions/<model_id>")
def get_model_dimensions(model_id):
    """Get model dimensions in meters"""
    try:
        glb_path = os.path.join(app.config["CONVERTED_FOLDER"], model_id, "model.glb")

        if not os.path.exists(glb_path):
            return jsonify({"success": False, "error": "Model not found"}), 404

        # Load model with trimesh
        mesh = trimesh.load(glb_path, force="scene")

        # Get bounding box
        if isinstance(mesh, trimesh.Scene):
            bounds = mesh.bounds
        else:
            bounds = mesh.bounds

        # Calculate dimensions (in meters, assuming GLB units are meters)
        dimensions = bounds[1] - bounds[0]

        # Convert to cm for display
        dimensions_cm = {
            "width": float(dimensions[0] * 100),  # X
            "height": float(dimensions[1] * 100),  # Y
            "depth": float(dimensions[2] * 100),  # Z
            "unit": "cm",
        }

        logger.info(
            f"[get_model_dimensions] Model {model_id} dimensions: {dimensions_cm}"
        )

        return jsonify({"success": True, "dimensions": dimensions_cm})

    except Exception as e:
        logger.error(f"[get_model_dimensions] Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/save_modifications", methods=["POST"])
@limiter.limit("60 per minute")
def save_modifications():
    """Save modifications to original GLB model (replaces model.glb)"""
    try:
        data = request.json
        model_id = data.get("model_id")
        modifications = data.get("modifications")

        if not model_id or not modifications:
            return jsonify(
                {"success": False, "error": "Missing model_id or modifications"}
            ), 400

        logger.info(f"[save_modifications] Model ID: {model_id}")
        logger.info(f"[save_modifications] Modifications: {modifications}")

        # This is the viewer's material editor: the user picked the color while
        # SEEING the texture, so honor it as a tint. (Upload-time color keeps
        # the protective skip-on-textured behavior in glb_modifier.)
        if isinstance(modifications.get("material"), dict):
            modifications["material"]["tint_textures"] = True

        # Use current model.glb as base (which may be sliced or modified)
        # This ensures modifications are applied to the current state, not original upload
        model = UserModel.query.get(model_id)
        if not model:
            logger.error(f"Model not found for ID: {model_id}")
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        # Use current model.glb file as the base for modifications
        current_model_path = os.path.join(
            app.config["CONVERTED_FOLDER"], model_id, "model.glb"
        )

        if not os.path.exists(current_model_path):
            logger.error(f"Current model.glb not found: {current_model_path}")
            return jsonify({"success": False, "error": "Model file not found"}), 404

        # Refuse to edit meshopt-compressed GLBs (trimesh cannot decode them).
        from converters.glb_optimizer import glb_requires_meshopt

        if glb_requires_meshopt(current_model_path):
            return jsonify(
                {
                    "success": False,
                    "error": "This model is compressed (meshopt) and cannot be modified. Re-upload it without optimization to edit.",
                }
            ), 400

        logger.info(
            f"[save_modifications] Using current model.glb as base: {current_model_path}"
        )

        # Create backup of current model
        backup_path = os.path.join(
            app.config["CONVERTED_FOLDER"],
            model_id,
            f"model_backup_{int(time.time())}.glb",
        )
        shutil.copy2(current_model_path, backup_path)
        logger.info(f"[save_modifications] Created backup: {backup_path}")
        cleanup_old_backups(os.path.dirname(backup_path))

        # Create temporary output path
        temp_output = os.path.join(
            app.config["CONVERTED_FOLDER"], model_id, f"temp_{int(time.time())}.glb"
        )

        logger.info(f"[save_modifications] Input: {current_model_path}")
        logger.info(f"[save_modifications] Temp output: {temp_output}")

        # Apply modifications to current model
        success = modify_glb(current_model_path, temp_output, modifications)

        if success and os.path.exists(temp_output):
            # Replace current model.glb with modified version (atomic on same volume)
            os.replace(temp_output, current_model_path)
            logger.info(
                f"[save_modifications] Successfully replaced model.glb with modified version"
            )

            # Keep iOS AR in sync: Quick Look uses the USDZ, so it must be
            # rebuilt from the freshly modified GLB.
            refresh_usdz_after_edit(model_id, current_model_path)

            # Update database dimensions after modifications
            try:
                mesh = trimesh.load(current_model_path, force="scene")
                if isinstance(mesh, trimesh.Scene):
                    bounds = mesh.bounds
                else:
                    bounds = mesh.bounds

                dimensions = bounds[1] - bounds[0]
                new_dims = {
                    "x": round(float(dimensions[0] * 100), 2),
                    "y": round(float(dimensions[1] * 100), 2),
                    "z": round(float(dimensions[2] * 100), 2),
                    "max": round(float(max(dimensions) * 100), 2),
                }

                # Update database
                model = UserModel.query.get(model_id)
                if model:
                    model.dimensions = new_dims

                    # Update cumulative scale if scale was applied
                    if (
                        "transform" in modifications
                        and "scale" in modifications["transform"]
                    ):
                        applied_scale = float(modifications["transform"]["scale"])
                        if applied_scale != 1.0:
                            current_cumulative = model.cumulative_scale or 1.0
                            model.cumulative_scale = current_cumulative * applied_scale
                            logger.info(
                                f"[save_modifications] Updated cumulative scale: {current_cumulative} * {applied_scale} = {model.cumulative_scale}"
                            )

                    db.session.commit()
                    logger.info(
                        f"[save_modifications] Updated database dimensions: {new_dims}"
                    )

            except Exception as dim_error:
                logger.error(
                    f"[save_modifications] Failed to update dimensions: {dim_error}"
                )

            # Create version entry
            try:
                operation_type = (
                    "transform" if "transform" in modifications else "material"
                )
                if "material" in modifications and "transform" in modifications:
                    operation_type = "transform+material"

                create_version(
                    model_id=model_id,
                    operation_type=operation_type,
                    operation_details=modifications,
                    comment="Model modifications saved",
                )
                logger.info(
                    f"[save_modifications] Created version entry for {model_id}"
                )
            except Exception as version_error:
                logger.error(
                    f"[save_modifications] Failed to create version: {version_error}"
                )

            return jsonify(
                {
                    "success": True,
                    "message": "Model saved successfully",
                    "backup": os.path.basename(backup_path),
                }
            )
        else:
            logger.error("[save_modifications] Modification failed")
            return jsonify({"success": False, "error": "Failed to modify GLB"}), 500

    except Exception as e:
        logger.error(f"[save_modifications] Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/get_mesh_bounds/<model_id>")
def api_get_mesh_bounds_route(model_id):
    """Get mesh bounding box for slicer"""
    try:
        from mesh_slicer import get_mesh_bounds as get_bounds

        model_path = os.path.join(app.config["CONVERTED_FOLDER"], model_id, "model.glb")

        if not os.path.exists(model_path):
            return jsonify({"success": False, "error": "Model not found"}), 404

        bounds = get_bounds(model_path)

        if bounds:
            return jsonify({"success": True, "bounds": bounds})
        else:
            return jsonify({"success": False, "error": "Failed to get bounds"}), 500

    except Exception as e:
        logger.error(f"Error getting mesh bounds: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/slice_model", methods=["POST"])
@limiter.limit("60 per minute")
def slice_model():
    """Slice a 3D model with a plane"""
    try:
        from mesh_slicer import slice_mesh_multi

        data = request.json
        model_id = data.get("model_id")

        # Accept either the new atomic multi-plane payload (`planes`) or the legacy
        # single-plane fields. Everything is funnelled through one multi-plane slice
        # so X+Y+Z is applied in a single pass producing ONE backup + ONE version.
        planes = data.get("planes")
        if not planes:
            single_origin = data.get("plane_origin")
            single_normal = data.get("plane_normal")
            if single_origin and single_normal:
                planes = [
                    {
                        "plane_origin": single_origin,
                        "plane_normal": single_normal,
                        "keep_side": data.get("keep_side", "positive"),
                    }
                ]

        logger.info(
            f"[slice_model] Received request for model_id: {model_id}, "
            f"{len(planes) if planes else 0} plane(s)"
        )

        if not model_id or not planes:
            return jsonify(
                {"success": False, "error": "Missing required parameters"}
            ), 400

        # Owner guard (models without a DB record are treated as anonymous)
        guard = check_model_mutation_allowed(model_id, require_exists=False)
        if guard:
            return guard

        # Try to find the model file
        # First check if model_id is a UUID (converted model)
        input_path = os.path.join(app.config["CONVERTED_FOLDER"], model_id, "model.glb")

        if not os.path.exists(input_path):
            # Maybe model_id is the full filename from database
            model = UserModel.query.get(model_id)
            if model and model.filename:
                # Extract folder from filename (e.g., "converted/uuid/model.glb" -> "uuid")
                parts = model.filename.split("/")
                if len(parts) >= 2:
                    folder_id = parts[1]
                    input_path = os.path.join(
                        app.config["CONVERTED_FOLDER"], folder_id, "model.glb"
                    )
                    logger.info(f"[slice_model] Trying alternate path: {input_path}")

        if not os.path.exists(input_path):
            logger.error(f"[slice_model] Model not found at: {input_path}")
            logger.error(
                f"[slice_model] CONVERTED_FOLDER: {app.config['CONVERTED_FOLDER']}"
            )
            logger.error(f"[slice_model] model_id: {model_id}")
            return jsonify(
                {"success": False, "error": f"Model not found at {input_path}"}
            ), 404

        # Refuse to edit meshopt-compressed GLBs (trimesh cannot decode them).
        from converters.glb_optimizer import glb_requires_meshopt

        if glb_requires_meshopt(input_path):
            return jsonify(
                {
                    "success": False,
                    "error": "This model is compressed (meshopt) and cannot be sliced. Re-upload it without optimization to edit.",
                }
            ), 400

        # Create backup
        import time

        backup_path = os.path.join(
            app.config["CONVERTED_FOLDER"],
            model_id,
            f"model_backup_{int(time.time())}.glb",
        )
        import shutil

        shutil.copy2(input_path, backup_path)
        logger.info(f"[slice_model] Created backup: {backup_path}")
        cleanup_old_backups(os.path.dirname(backup_path))

        # Slice the mesh
        temp_output = os.path.join(
            app.config["CONVERTED_FOLDER"],
            model_id,
            f"temp_sliced_{int(time.time())}.glb",
        )

        slice_result = slice_mesh_multi(
            input_path=input_path,
            output_path=temp_output,
            planes=planes,
        )
        success = bool(slice_result.get("success"))

        if success and os.path.exists(temp_output):
            # Replace original with sliced version (atomic on same volume)
            os.replace(temp_output, input_path)
            logger.info(
                f"[slice_model] Successfully replaced original with sliced mesh"
            )

            # Rebuild the iOS USDZ from the sliced GLB (Quick Look uses it).
            refresh_usdz_after_edit(model_id, input_path)

            # Update dimensions in database
            try:
                import trimesh

                mesh = trimesh.load(input_path, force="mesh")

                if isinstance(mesh, trimesh.Scene):
                    meshes = list(mesh.geometry.values())
                    if meshes:
                        mesh = trimesh.util.concatenate(meshes)

                bounds = mesh.bounds
                dimensions = bounds[1] - bounds[0]
                new_dims = {
                    "x": round(float(dimensions[0] * 100), 2),
                    "y": round(float(dimensions[1] * 100), 2),
                    "z": round(float(dimensions[2] * 100), 2),
                    "max": round(float(max(dimensions) * 100), 2),
                }

                model = UserModel.query.get(model_id)
                if model:
                    model.dimensions = new_dims
                    db.session.commit()
                    logger.info(f"[slice_model] Updated dimensions: {new_dims}")

            except Exception as dim_error:
                logger.error(f"[slice_model] Failed to update dimensions: {dim_error}")

            # Create a SINGLE version entry for the whole multi-plane slice
            try:
                axis_count = len(planes)
                create_version(
                    model_id=model_id,
                    operation_type="slice",
                    operation_details={"planes": planes},
                    comment=f"Sliced model ({axis_count} plane(s))",
                )
                logger.info(f"[slice_model] Created version entry for {model_id}")
            except Exception as version_error:
                logger.error(f"[slice_model] Failed to create version: {version_error}")

            response = {
                "success": True,
                "message": "Model sliced successfully",
                "backup": os.path.basename(backup_path),
            }
            # Surface near-flat results so the UI can warn the user instead of
            # silently producing a degenerate model.
            if slice_result.get("degenerate"):
                response["warning"] = (
                    "The slice result is nearly flat — one dimension is almost zero. "
                    "Check the kept side / slider position."
                )
            return jsonify(response)
        else:
            logger.error("[slice_model] Slicing failed")
            return jsonify({"success": False, "error": "Failed to slice model"}), 500

    except Exception as e:
        logger.error(f"[slice_model] Error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


# ========== MODEL VERSION MANAGEMENT ==========


@app.route("/api/versions/<model_id>", methods=["GET"])
def get_versions(model_id):
    """Get version history for a model"""
    try:
        versions = get_version_history(model_id)
        return jsonify(
            {
                "success": True,
                "versions": [
                    {
                        "id": v.id,
                        "version_number": v.version_number,
                        "operation_type": v.operation_type,
                        "operation_details": v.operation_details,
                        "dimensions": v.dimensions,
                        "vertices": v.vertices,
                        "faces": v.faces,
                        "file_size": v.file_size,
                        "file_size_formatted": v.file_size_formatted,
                        "created_at": v.created_at_formatted,
                        "comment": v.comment,
                    }
                    for v in versions
                ],
            }
        )
    except Exception as e:
        logger.error(f"Failed to get versions for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/versions/<model_id>/restore/<int:version_number>", methods=["POST"])
def restore_model_version(model_id, version_number):
    """Restore model to a specific version"""
    try:
        guard = check_model_mutation_allowed(model_id, require_exists=False)
        if guard:
            return guard

        success = restore_version(model_id, version_number)
        if success:
            # The restored GLB replaced model.glb — rebuild the iOS USDZ too.
            glb_path = os.path.join(
                app.config["CONVERTED_FOLDER"], model_id, "model.glb"
            )
            refresh_usdz_after_edit(model_id, glb_path)
            return jsonify(
                {"success": True, "message": f"Restored to version {version_number}"}
            )
        else:
            return jsonify(
                {"success": False, "error": "Failed to restore version"}
            ), 500
    except Exception as e:
        logger.error(f"Failed to restore version {version_number} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/versions/<model_id>/delete/<int:version_number>", methods=["DELETE"])
def delete_model_version(model_id, version_number):
    """Delete a specific version"""
    try:
        guard = check_model_mutation_allowed(model_id, require_exists=False)
        if guard:
            return guard

        success = delete_version(model_id, version_number)
        if success:
            return jsonify(
                {"success": True, "message": f"Deleted version {version_number}"}
            )
        else:
            return jsonify({"success": False, "error": "Failed to delete version"}), 500
    except Exception as e:
        logger.error(f"Failed to delete version {version_number} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/versions/<model_id>/download/<int:version_number>", methods=["GET"])
def download_version(model_id, version_number):
    """Download a specific version"""
    try:
        version = ModelVersion.query.filter_by(
            model_id=model_id, version_number=version_number
        ).first()
        if not version:
            return jsonify({"success": False, "error": "Version not found"}), 404

        if not os.path.exists(version.filename):
            return jsonify({"success": False, "error": "Version file not found"}), 404

        directory = os.path.dirname(version.filename)
        filename = os.path.basename(version.filename)

        return send_from_directory(
            directory,
            filename,
            as_attachment=True,
            download_name=f"model_v{version_number}.glb",
        )
    except Exception as e:
        logger.error(f"Failed to download version {version_number} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ===================================================================
# HOTSPOT CRUD API
# ===================================================================

@app.route("/api/models/<model_id>/hotspots", methods=["GET"])
def get_hotspots(model_id):
    """Get all hotspots for a model"""
    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        hotspots = ModelHotspot.query.filter_by(model_id=model_id).order_by(ModelHotspot.created_at).all()
        return jsonify({
            "success": True,
            "hotspots": [h.to_dict() for h in hotspots],
            "hotspots_visible": model.hotspots_visible
        })
    except Exception as e:
        logger.error(f"Error getting hotspots for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/models/<model_id>/hotspots", methods=["POST"])
def create_hotspot(model_id):
    """Create a new hotspot on a model"""
    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        hotspot = ModelHotspot(
            model_id=model_id,
            hotspot_id=data.get("id", f"hotspot-{int(time.time()*1000)}"),
            title=data.get("title", "Untitled"),
            description=data.get("description"),
            position_x=data["position"]["x"],
            position_y=data["position"]["y"],
            position_z=data["position"]["z"],
            normal_x=data.get("normal", {}).get("x"),
            normal_y=data.get("normal", {}).get("y"),
            normal_z=data.get("normal", {}).get("z"),
        )

        # Optional camera view
        camera = data.get("cameraView")
        if camera:
            hotspot.camera_view_id = data.get("cameraViewId")
            orbit = camera.get("orbit", {})
            hotspot.camera_orbit_theta = orbit.get("theta")
            hotspot.camera_orbit_phi = orbit.get("phi")
            hotspot.camera_orbit_radius = orbit.get("radius")
            target = camera.get("target", {})
            hotspot.camera_target_x = target.get("x")
            hotspot.camera_target_y = target.get("y")
            hotspot.camera_target_z = target.get("z")
            hotspot.camera_fov = camera.get("fov")

        db.session.add(hotspot)
        db.session.commit()

        return jsonify({"success": True, "hotspot": hotspot.to_dict()}), 201
    except KeyError as e:
        return jsonify({"success": False, "error": f"Missing required field: {e}"}), 400
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating hotspot for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/models/<model_id>/hotspots/<hotspot_id>", methods=["DELETE"])
def delete_hotspot(model_id, hotspot_id):
    """Delete a specific hotspot"""
    try:
        guard = check_model_mutation_allowed(model_id, require_exists=False)
        if guard:
            return guard

        hotspot = ModelHotspot.query.filter_by(
            model_id=model_id, hotspot_id=hotspot_id
        ).first()
        if not hotspot:
            return jsonify({"success": False, "error": "Hotspot not found"}), 404

        db.session.delete(hotspot)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting hotspot {hotspot_id} for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/models/<model_id>/hotspots", methods=["DELETE"])
def delete_all_hotspots(model_id):
    """Delete all hotspots for a model"""
    try:
        guard = check_model_mutation_allowed(model_id, require_exists=False)
        if guard:
            return guard

        ModelHotspot.query.filter_by(model_id=model_id).delete()
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting all hotspots for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/models/<model_id>/hotspots/visibility", methods=["PATCH"])
def toggle_hotspots_visibility(model_id):
    """Toggle hotspot visibility for a model"""
    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        data = request.get_json()
        model.hotspots_visible = data.get("visible", not model.hotspots_visible)
        db.session.commit()
        return jsonify({"success": True, "hotspots_visible": model.hotspots_visible})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error toggling hotspot visibility for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ===================================================================
# CAMERA VIEW CRUD API
# ===================================================================

@app.route("/api/models/<model_id>/camera-views", methods=["GET"])
def get_camera_views(model_id):
    """Get all saved camera views for a model"""
    try:
        views = CameraView.query.filter_by(model_id=model_id).order_by(CameraView.created_at).all()
        return jsonify({"success": True, "views": [v.to_dict() for v in views]})
    except Exception as e:
        logger.error(f"Error getting camera views for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/models/<model_id>/camera-views", methods=["POST"])
def create_camera_view(model_id):
    """Save a camera view"""
    try:
        model = UserModel.query.get(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        guard = check_model_mutation_allowed(model_id)
        if guard:
            return guard

        data = request.get_json()
        orbit = data.get("orbit", {})
        target = data.get("target", {})

        view = CameraView(
            model_id=model_id,
            name=data.get("name", "View"),
            orbit_theta=orbit.get("theta", 0),
            orbit_phi=orbit.get("phi", 0),
            orbit_radius=orbit.get("radius", 0),
            target_x=target.get("x", 0),
            target_y=target.get("y", 0),
            target_z=target.get("z", 0),
            fov=data.get("fov"),
        )
        db.session.add(view)
        db.session.commit()
        return jsonify({"success": True, "view": view.to_dict()}), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating camera view for {model_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/models/<model_id>/camera-views/<int:view_id>", methods=["DELETE"])
def delete_camera_view(model_id, view_id):
    """Delete a camera view"""
    try:
        guard = check_model_mutation_allowed(model_id, require_exists=False)
        if guard:
            return guard

        view = CameraView.query.filter_by(id=view_id, model_id=model_id).first()
        if not view:
            return jsonify({"success": False, "error": "View not found"}), 404
        db.session.delete(view)
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting camera view {view_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# =====================================================================
#  AI Text/Image -> 3D generation (Meshy)
# =====================================================================
def register_glb_as_model(glb_path, *, user_id=None, source="ai", prompt=None,
                          usdz_src_path=None, color=None):
    """Register an already-prepared GLB into the same pipeline as /upload_model.

    Mirrors the upload flow: UUID dir -> converted/<uuid>/model.glb -> bounds via
    trimesh -> UserModel -> async thumbnail (+ USDZ: use the provided file if any,
    otherwise fall back to the Blender async path). Returns the committed UserModel.
    """
    import json as _json

    unique_id = str(uuid.uuid4())
    converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], unique_id)
    os.makedirs(converted_dir, exist_ok=True)
    output_path = os.path.join(converted_dir, "model.glb")
    shutil.copy2(glb_path, output_path)

    # Best-effort centre-normalize (same as upload) for consistent pivot
    try:
        g = GLTF2().load(output_path)
        g = normalize_model_to_center(g)
        g.save(output_path)
    except Exception as e:
        logger.warning(f"[register_glb] normalize skipped: {e}")

    # GLB quality pass (warn-only): embedded textures + PBR guarantee + validation
    try:
        for w in finalize_glb(output_path, search_dirs=[converted_dir,
                                                        os.path.dirname(glb_path)]):
            logger.warning(f"[register_glb] GLB quality: {w}")
    except Exception as e:
        logger.warning(f"[register_glb] GLB quality pass skipped: {e}")

    # Dimensions / bounds (mirror upload_model GLB branch)
    model_bounds = None
    try:
        import trimesh
        import numpy as np

        mesh = trimesh.load(output_path)
        if isinstance(mesh, trimesh.Scene):
            verts = [gm.vertices for gm in mesh.geometry.values()
                     if isinstance(gm, trimesh.Trimesh)]
            if verts:
                cv = np.vstack(verts)
                extents = cv.max(axis=0) - cv.min(axis=0)
            else:
                b = mesh.bounds
                extents = b[1] - b[0]
        else:
            extents = mesh.extents
        if max(extents) > 0.001:
            model_bounds = _json.dumps({
                "extents": [round(float(extents[0]) * 100, 2),
                            round(float(extents[1]) * 100, 2),
                            round(float(extents[2]) * 100, 2)],
                "max": round(float(max(extents)) * 100, 2),
            })
    except Exception as e:
        logger.warning(f"[register_glb] bounds calc failed: {e}")

    # USDZ: prefer the supplied file (e.g. Meshy) so we skip Blender entirely
    usdz_path = os.path.join(converted_dir, "model.usdz")
    usdz_filename = None
    if usdz_src_path and os.path.exists(usdz_src_path):
        try:
            shutil.copy2(usdz_src_path, usdz_path)
            usdz_filename = usdz_path
        except Exception as e:
            logger.warning(f"[register_glb] usdz copy failed: {e}")

    model = UserModel(
        id=unique_id,
        user_id=user_id,
        filename=output_path,
        usdz_filename=usdz_filename,
        file_size=os.path.getsize(output_path),
        file_type="glb",
        upload_date=datetime.utcnow(),
        color=color,
        bounds=model_bounds,
        original_dimensions=None,
        cumulative_scale=1.0,
        display_name=(prompt[:80] if prompt else None),
        description=(f"AI generated ({source})" + (f": {prompt}" if prompt else "")),
    )
    db.session.add(model)
    db.session.commit()

    try:
        create_version(model_id=unique_id, operation_type="upload",
                       operation_details={"source": source, "prompt": prompt},
                       comment="AI generation")
    except Exception as e:
        logger.error(f"[register_glb] version failed: {e}")

    try:
        threading.Thread(target=generate_thumbnail_async,
                         args=(unique_id, output_path, color), daemon=True).start()
    except Exception as e:
        logger.error(f"[register_glb] thumbnail thread failed: {e}")

    if not usdz_filename:
        try:
            threading.Thread(target=convert_usdz_async,
                             args=(unique_id, output_path, usdz_path), daemon=True).start()
        except Exception as e:
            logger.error(f"[register_glb] usdz thread failed: {e}")

    return model


def _ai_quota_state(user_id):
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=1)
    limit = app.config.get("AI_GEN_DAILY_LIMIT", 10)
    count = AIGenerationJob.query.filter(
        AIGenerationJob.user_id == user_id,
        AIGenerationJob.created_at >= since,
    ).count()
    return (count >= limit), count, limit


def _claim_ai_stage(job_id, expect_stage, new_stage):
    """Atomically move a job between stages with UPDATE ... WHERE stage=...

    The state machine is advanced by client polls; two concurrent polls of
    the same job (multiple tabs/devices) could otherwise both see a finished
    preview and both call start_refine — burning duplicate Meshy credits —
    or both finalize and register duplicate models. Exactly one poll wins
    this claim; the loser just reports current progress.
    """
    claimed = AIGenerationJob.query.filter_by(
        id=job_id, stage=expect_stage
    ).update({"stage": new_stage}, synchronize_session=False)
    db.session.commit()
    return bool(claimed)


def _finalize_ai_job(job, task):
    """Download finished GLB (+USDZ), register as model, mark job ready."""
    import ai_generator

    model_urls = task.get("model_urls") or {}
    glb_url = model_urls.get("glb")
    if not glb_url:
        job.status = "failed"
        job.error = "Generation finished but returned no GLB"
        db.session.commit()
        resp = job.to_dict(); resp["success"] = True
        return jsonify(resp)

    tmp_dir = os.path.join(app.config["TEMP_FOLDER"], "ai_" + job.id)
    os.makedirs(tmp_dir, exist_ok=True)
    glb_tmp = os.path.join(tmp_dir, "model.glb")
    ai_generator.download(glb_url, glb_tmp)

    usdz_tmp = None
    if model_urls.get("usdz"):
        try:
            usdz_tmp = os.path.join(tmp_dir, "model.usdz")
            ai_generator.download(model_urls["usdz"], usdz_tmp)
        except Exception as e:
            logger.warning(f"[generate-3d] USDZ download failed: {e}")
            usdz_tmp = None

    model = register_glb_as_model(
        glb_tmp, user_id=job.user_id, source=f"ai-{job.kind}",
        prompt=job.prompt, usdz_src_path=usdz_tmp,
    )
    try:
        shutil.rmtree(tmp_dir)
    except Exception:
        pass

    job.status = "ready"
    job.progress = 100
    job.model_id = model.id
    db.session.commit()
    resp = job.to_dict(); resp["success"] = True
    resp["viewer_url"] = url_for("view_model", model_id=model.id)
    return jsonify(resp)


@app.route("/api/generate-3d", methods=["POST"])
@login_required
@limiter.limit("6 per minute")
def generate_3d():
    """Start a Meshy text/image -> 3D generation job (login + daily quota)."""
    import ai_generator

    if not ai_generator.is_configured():
        return jsonify({"success": False,
                        "error": "AI generation is not configured on this server."}), 503

    exceeded, count, limit = _ai_quota_state(current_user.id)
    if exceeded:
        return jsonify({"success": False,
                        "error": f"Daily generation limit reached ({limit}). Try again tomorrow."}), 429

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "text").strip()
    job_id = str(uuid.uuid4())
    try:
        if mode == "image":
            image_task = data.get("image_task")
            if isinstance(image_task, dict):
                # an AI-generated image from the pre-processing step,
                # resolved server-side from its Meshy task id
                image = _resolve_image_task(image_task)
            else:
                image = (data.get("image") or "").strip()
            if not image.startswith("data:image/"):
                return jsonify({"success": False,
                                "error": "A valid image (jpg/png) is required."}), 400
            task_id = ai_generator.start_image_to_3d(image)
            job = AIGenerationJob(id=job_id, user_id=current_user.id, kind="image",
                                  stage="image", meshy_image_id=task_id,
                                  status="generating", progress=0)
        else:
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                return jsonify({"success": False,
                                "error": "A text prompt is required."}), 400
            task_id = ai_generator.start_text_to_3d(prompt)
            job = AIGenerationJob(id=job_id, user_id=current_user.id, kind="text",
                                  prompt=prompt, stage="preview", meshy_preview_id=task_id,
                                  status="generating", progress=0)
        db.session.add(job)
        db.session.commit()
        return jsonify({"success": True, "job_id": job_id})
    except ai_generator.MeshyError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        logger.error(f"[generate-3d] start error: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Failed to start generation."}), 500


@app.route("/api/generate-3d/<job_id>/status", methods=["GET"])
@login_required
def generate_3d_status(job_id):
    """Poll a generation job; advances text two-stage and finalizes on success."""
    import ai_generator

    job = AIGenerationJob.query.get(job_id)
    if not job:
        return jsonify({"success": False, "error": "Job not found"}), 404
    if job.user_id != current_user.id:
        return jsonify({"success": False, "error": "Unauthorized"}), 403

    if job.status in ("ready", "failed"):
        resp = job.to_dict(); resp["success"] = True
        if job.status == "ready" and job.model_id:
            resp["viewer_url"] = url_for("view_model", model_id=job.model_id)
        return jsonify(resp)

    try:
        if job.kind == "image":
            if job.stage == "image":
                t = ai_generator.get_task("image", job.meshy_image_id)
                job.progress = min(99, t["progress"])
                if t["status"] == ai_generator.SUCCEEDED:
                    if not _claim_ai_stage(job.id, "image", "finalizing"):
                        db.session.refresh(job)  # another poll is finalizing
                    else:
                        try:
                            return _finalize_ai_job(job, t)
                        except Exception:
                            # let the next poll retry the download/registration
                            _claim_ai_stage(job.id, "finalizing", "image")
                            raise
                elif t["status"] in (ai_generator.FAILED, ai_generator.CANCELED):
                    job.status = "failed"
                    job.error = t.get("task_error") or "Generation failed"
        else:
            if job.stage == "preview":
                t = ai_generator.get_task("text", job.meshy_preview_id)
                job.progress = min(49, t["progress"] // 2)
                if t["status"] == ai_generator.SUCCEEDED:
                    if not _claim_ai_stage(job.id, "preview", "refining"):
                        db.session.refresh(job)  # another poll started refine
                    else:
                        try:
                            refine_id = ai_generator.start_refine(job.meshy_preview_id)
                        except Exception:
                            # release the claim so the next poll retries
                            _claim_ai_stage(job.id, "refining", "preview")
                            raise
                        job.meshy_refine_id = refine_id
                        job.stage = "refine"
                        job.progress = 50
                elif t["status"] in (ai_generator.FAILED, ai_generator.CANCELED):
                    job.status = "failed"
                    job.error = t.get("task_error") or "Preview failed"
            elif job.stage == "refine":
                t = ai_generator.get_task("text", job.meshy_refine_id)
                job.progress = min(99, 50 + t["progress"] // 2)
                if t["status"] == ai_generator.SUCCEEDED:
                    if not _claim_ai_stage(job.id, "refine", "finalizing"):
                        db.session.refresh(job)
                    else:
                        try:
                            return _finalize_ai_job(job, t)
                        except Exception:
                            _claim_ai_stage(job.id, "finalizing", "refine")
                            raise
                elif t["status"] in (ai_generator.FAILED, ai_generator.CANCELED):
                    job.status = "failed"
                    job.error = t.get("task_error") or "Texturing failed"
        db.session.commit()
    except ai_generator.MeshyError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        logger.error(f"[generate-3d] status error: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Status check failed."}), 500

    resp = job.to_dict(); resp["success"] = True
    return jsonify(resp)


# --------------------------------------------------------------------------- #
#  AI image pre-processing (text-to-image / image-to-image before 3D)
#
#  Stateless by design: image generation finishes in seconds, produces only
#  an image, and Meshy task ids are unguessable — so the task id is handed
#  straight to the client which polls the status proxy below. No DB rows,
#  gunicorn multi-worker safe, and it does NOT count against the 3D daily
#  quota (only HTTP rate limiting applies).
# --------------------------------------------------------------------------- #
_IMAGE_GEN_KINDS = ("t2i", "i2i")


@app.route("/api/generate-image", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def generate_image():
    """Start a Meshy image generation task as an optional pre-step to 3D."""
    import ai_generator

    if not ai_generator.is_configured():
        return jsonify({"success": False,
                        "error": "AI generation is not configured on this server."}), 503

    data = request.get_json(silent=True) or {}
    mode = (data.get("mode") or "text").strip()
    prompt = (data.get("prompt") or "").strip()
    try:
        if mode == "image":
            image = (data.get("image") or "").strip()
            if not image.startswith("data:image/"):
                return jsonify({"success": False,
                                "error": "A valid image (jpg/png) is required."}), 400
            if not prompt:
                return jsonify({"success": False,
                                "error": "Describe how to transform the image."}), 400
            task_id = ai_generator.start_image_to_image(image, prompt)
            kind = "i2i"
        else:
            if not prompt:
                return jsonify({"success": False,
                                "error": "A text prompt is required."}), 400
            task_id = ai_generator.start_text_to_image(
                prompt, aspect_ratio=(data.get("aspect_ratio") or "1:1"))
            kind = "t2i"
        return jsonify({"success": True, "task_id": task_id, "kind": kind})
    except ai_generator.MeshyError as e:
        return jsonify({"success": False, "error": str(e)}), 502
    except Exception as e:
        logger.error(f"[generate-image] start error: {e}", exc_info=True)
        return jsonify({"success": False, "error": "Failed to start image generation."}), 500


@app.route("/api/generate-image/<task_id>/status", methods=["GET"])
@login_required
def generate_image_status(task_id):
    """Proxy a Meshy image generation task's status to the client."""
    import ai_generator

    kind = request.args.get("kind", "t2i")
    if kind not in _IMAGE_GEN_KINDS:
        return jsonify({"success": False, "error": "Invalid kind."}), 400
    try:
        t = ai_generator.get_image_gen_task(kind, task_id)
    except ai_generator.MeshyError as e:
        return jsonify({"success": False, "error": str(e)}), 502

    status = t.get("status")
    if status == ai_generator.SUCCEEDED:
        return jsonify({"success": True, "status": "ready",
                        "progress": 100, "image_urls": t.get("image_urls") or []})
    if status in (ai_generator.FAILED, ai_generator.CANCELED):
        return jsonify({"success": True, "status": "failed",
                        "error": t.get("task_error") or "Image generation failed."})
    return jsonify({"success": True, "status": "generating",
                    "progress": t.get("progress") or 0})


def _resolve_image_task(image_task):
    """Turn a {kind, task_id, index} reference into a data URI.

    The 3D step never accepts raw URLs from the client (SSRF); the image is
    re-resolved from Meshy by task id and downloaded server-side because
    Meshy output links expire.
    """
    import ai_generator

    kind = (image_task.get("kind") or "").strip()
    task_id = (image_task.get("task_id") or "").strip()
    try:
        index = int(image_task.get("index", 0))
    except (TypeError, ValueError):
        index = -1
    if kind not in _IMAGE_GEN_KINDS or not task_id or index < 0:
        raise ai_generator.MeshyError("Invalid image task reference.")

    t = ai_generator.get_image_gen_task(kind, task_id)
    urls = t.get("image_urls") or []
    if t.get("status") != ai_generator.SUCCEEDED or index >= len(urls):
        raise ai_generator.MeshyError("The selected image is not ready.")
    return ai_generator.fetch_image_as_data_uri(urls[index])


if __name__ == "__main__":
    if init_app_dependencies():
        app.logger.info("Dependencies initialized successfully")
        # Railway/Heroku için PORT environment variable
        port = int(os.environ.get("PORT", 5000))
        app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", True))
    else:
        app.logger.error("Failed to initialize dependencies")
