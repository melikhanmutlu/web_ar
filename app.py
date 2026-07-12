from datetime import timedelta
from services.time_utils import datetime
import os
import json
from flask import (
    Flask,
    request,
    jsonify,
    send_file,
    send_from_directory,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    make_response,
    abort,
    g,
    has_app_context,
)
from flask_wtf.csrf import CSRFError, CSRFProtect
from flask_login import (
    LoginManager,
    login_user,
    login_required,
    logout_user,
    current_user,
)
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
import logging
import shutil
import subprocess
import threading
from models import db, User, UserModel, Folder, Organization, OrganizationMember, OrganizationDomain, ApiToken, PromptPreset, MaterialPreset, ModelVersion, ModelLOD, ModelDerivedAsset, ModelLike, ModelSave, ModelHotspot, ModelShareLink, ModelAnalyticsEvent, CameraView, AIGenerationJob, ConversionJob, WorkerHeartbeat
from auth import auth
from admin import admin_bp
from blueprints.health import health_bp
from blueprints.seo import seo_bp
from blueprints.material_presets import material_presets_bp, _resolve_prompt_preset
from blueprints.api_tokens import api_tokens_bp
from blueprints.organizations import organizations_bp
from blueprints.model_files import model_files_bp
from blueprints.models_crud import models_crud_bp
from blueprints.sharing import sharing_bp
from blueprints.model_metadata import model_metadata_bp
from blueprints.model_geometry import model_geometry_bp
from blueprints.versions import versions_bp
from blueprints.hotspots import hotspots_bp
from blueprints.engagement import engagement_bp
from blueprints.model_editing import model_editing_bp
from blueprints.upload import upload_bp
from blueprints.main import main_bp
from blueprints.viewer import viewer_bp
from blueprints.ai_generation import ai_generation_bp
from blueprints.ai_image import ai_image_bp
from blueprints.webhooks import webhooks_bp
from blueprints.discover import discover_bp
from blueprints.scenes import scenes_bp
from model_cleanup import purge_model_completely
from site_settings import get_setting, setting_bool, setting_int
import re
import traceback
import uuid
import secrets
import hashlib
from urllib.parse import urlparse, urlsplit
from flask_migrate import Migrate
from config import *
from sqlalchemy.orm import Session
import qrcode
from slugify import slugify
import trimesh
from converters import OBJConverter, FBXConverter, STLConverter, STEPConverter
from converters.glb_optimizer import optimize_glb
from converters.glb_quality import finalize_glb
import numpy as np
from glb_modifier import modify_glb, normalize_model_to_center
from pygltflib import GLTF2
import time
from version_manager import (
    create_version,
    get_version_history,
    restore_version,
    delete_version,
    version_path,
)
from services import AssetQualityService, ConversionJobService, ConversionService, ModelAccessService, StorageService, UploadStagingService, configure_json_logging, initialize_external_observability, dispatch_webhook_event, send_email
from services.model_permissions import (
    model_access,
    get_live_model,
    check_model_mutation_allowed,
    check_model_view_allowed,
    _active_share_grant,
)
from services.model_analytics import ANALYTICS_EVENT_TYPES, record_model_event
from services.viewer_settings import DEFAULT_VIEWER_SETTINGS, resolved_viewer_settings
from services.storage_quota import (
    TRASH_RETENTION_DAYS,
    _purge_expired_trash,
    _storage_usage_for,
    _storage_quota_bytes,
)
from services.org_membership import _organization_membership

app = Flask(__name__)
app.config.from_object("config")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# Baseline security headers on every response. X-Frame-Options is intentionally
# omitted because /embed/<id> is designed to be iframed by third parties.
@app.after_request
def after_request(response):
    request_id = getattr(g, "request_id", None)
    if request_id:
        response.headers["X-Request-ID"] = request_id
    started = getattr(g, "request_started_at", None)
    if started is not None:
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(self), microphone=(), geolocation=(self), payment=()",
    )
    frame_ancestors = "'self'"
    if request.endpoint == "viewer.embed_view" and request.view_args:
        model = db.session.get(UserModel, request.view_args.get("model_id"))
        domains = [
            item.strip().lower()
            for item in (model.embed_allowed_domains or "").split(",")
            if item.strip()
        ] if model else []
        if domains:
            frame_ancestors += " " + " ".join(f"https://{domain}" for domain in domains)
        else:
            # Existing embed semantics allow any parent until an explicit
            # allowlist is configured for the model.
            frame_ancestors = "*"
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        # 'wasm-unsafe-eval' is REQUIRED: model-viewer's decoders (meshopt,
        # and DRACO/KTX2 from gstatic) compile WebAssembly. Without it the
        # decoder's WebAssembly.instantiate() is refused, the loader's
        # decoder promise rejects, and EVERY model load fails -- blank
        # viewer, dead AR/fullscreen buttons on all devices.
        "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.tailwindcss.com https://unpkg.com https://ajax.googleapis.com https://cdnjs.cloudflare.com https://aframe.io https://cdn.rawgit.com https://www.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: blob: https:; connect-src 'self' https:; "
        "worker-src 'self' blob:; "
        f"frame-ancestors {frame_ancestors}",
    )
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.before_request
def attach_request_context():
    supplied = request.headers.get("X-Request-ID", "")
    g.request_id = supplied[:128] if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied) else str(uuid.uuid4())
    g.request_started_at = time.perf_counter()


@app.before_request
def protect_browser_writes():
    """Reject cross-site browser writes while preserving token-based API clients.

    Modern browsers send Origin on unsafe requests. Referer is the fallback for
    older form submissions; non-browser clients without either header continue
    to work and must still satisfy each endpoint's auth/capability checks.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    supplied = request.headers.get("Origin") or request.headers.get("Referer")
    if not supplied:
        return None
    source = urlsplit(supplied)
    expected = urlsplit(request.host_url)
    source_port = source.port or (443 if source.scheme == "https" else 80)
    expected_port = expected.port or (443 if expected.scheme == "https" else 80)
    if (source.scheme, source.hostname, source_port) != (
        expected.scheme, expected.hostname, expected_port
    ):
        return jsonify({"success": False, "error": "Cross-site request rejected"}), 403
    return None


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
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.config["ALLOWED_EXTENSIONS"] = ALLOWED_EXTENSIONS

# NOTE: UPLOAD_FOLDER/CONVERTED_FOLDER/TEMP_FOLDER/QR_FOLDER and the limits come
# from config.py via `from config import *`. They are storage-root aware (they
# respect the Railway volume mount). They are deliberately NOT redefined here to
# dirname-relative paths — doing so previously made the module globals diverge
# from app.config and wrote data to the ephemeral container filesystem.


@app.context_processor
def upload_capabilities():
    """Expose the backend's authoritative upload policy to templates."""
    extensions = sorted(app.config["ALLOWED_EXTENSIONS"])
    return {
        "upload_extensions": extensions,
        "upload_accept": ",".join(f".{ext}" for ext in extensions),
        "upload_max_bytes": app.config["MAX_CONTENT_LENGTH"],
        "upload_max_mb": app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024),
    }

# Initialize extensions
db.init_app(app)
# CSRF protection for all state-changing requests. Token is bound to the session
# (no hard time limit) so long-lived viewer/editor pages don't fail mutations.
app.config.setdefault("WTF_CSRF_TIME_LIMIT", None)
csrf = CSRFProtect(app)
migrate = Migrate(app, db)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    if user is not None and not user.is_active:
        # Deactivated accounts lose their live sessions on the next request.
        return None
    return user


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

storage = StorageService(CONVERTED_FOLDER, UPLOAD_FOLDER, TEMP_FOLDER)
conversion_jobs = ConversionJobService(
    db,
    retry_base_seconds=int(os.environ.get("JOB_RETRY_BASE_SECONDS", "15")),
    retry_max_seconds=int(os.environ.get("JOB_RETRY_MAX_SECONDS", "900")),
)
upload_staging = UploadStagingService(
    TEMP_FOLDER,
    max_uncompressed_bytes=MAX_CONTENT_LENGTH,
    max_archive_entries=ZIP_MAX_ENTRIES,
)
asset_quality = AssetQualityService(
    warning_triangles=int(os.environ.get("GLB_WARNING_TRIANGLES", "250000")),
    warning_bytes=int(os.environ.get("GLB_WARNING_BYTES", str(25 * 1024 * 1024))),
)
conversion_service = ConversionService(asset_quality)

@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify(
        {"success": False, "error": f"Rate limit exceeded: {e.description}"}
    ), 429


@app.errorhandler(CSRFError)
def csrf_error_handler(e):
    wants_json = request.path.startswith("/api/") or (
        request.accept_mimetypes.best == "application/json"
    )
    if wants_json:
        return jsonify(
            {"success": False, "error": f"CSRF validation failed: {e.description}"}
        ), 400
    flash("Your session expired. Please try again.", "error")
    referrer = request.referrer or ""
    same_origin = urlsplit(referrer).netloc == urlsplit(request.host_url).netloc
    return redirect(referrer if same_origin else url_for("main.index"))




@app.before_request
def resolve_custom_domain():
    hostname = request.host.split(":", 1)[0].strip().lower().rstrip(".")
    g.custom_domain = OrganizationDomain.query.filter_by(hostname=hostname).filter(
        OrganizationDomain.verified_at.isnot(None)
    ).first()
    if g.custom_domain and request.endpoint == "main.index" and request.method == "GET":
        organization = g.custom_domain.organization
        models = UserModel.query.filter(
            UserModel.organization_id == organization.id,
            UserModel.visibility == "public",
            UserModel.deleted_at.is_(None),
        ).order_by(UserModel.upload_date.desc()).all()
        branding = DEFAULT_VIEWER_SETTINGS["branding"]
        if models:
            branding = resolved_viewer_settings(models[0])["branding"]
        return render_template(
            "custom_domain.html", organization=organization,
            models=models, branding=branding,
        )


# Register blueprints
app.register_blueprint(auth)
app.register_blueprint(admin_bp)
app.register_blueprint(health_bp)
app.register_blueprint(seo_bp)
app.register_blueprint(material_presets_bp)
app.register_blueprint(api_tokens_bp)
app.register_blueprint(organizations_bp)
app.register_blueprint(model_files_bp)
app.register_blueprint(models_crud_bp)
app.register_blueprint(sharing_bp)
app.register_blueprint(model_metadata_bp)
app.register_blueprint(model_geometry_bp)
app.register_blueprint(versions_bp)
app.register_blueprint(hotspots_bp)
app.register_blueprint(engagement_bp)
app.register_blueprint(model_editing_bp)
app.register_blueprint(upload_bp)
app.register_blueprint(main_bp)
app.register_blueprint(viewer_bp)
app.register_blueprint(ai_generation_bp)
app.register_blueprint(ai_image_bp)
app.register_blueprint(webhooks_bp)
app.register_blueprint(discover_bp)
app.register_blueprint(scenes_bp)
limiter.limit("120 per minute")(admin_bp)

# auth.py can't import `limiter` itself (it's imported before `limiter` exists
# in this module, so that would be circular) — apply IP-based brute-force
# throttling here instead, on top of the per-account lockout in models.py.
app.view_functions["auth.login"] = limiter.limit(
    "10 per minute", methods=["POST"]
)(app.view_functions["auth.login"])
app.view_functions["auth.register"] = limiter.limit(
    "5 per hour", methods=["POST"]
)(app.view_functions["auth.register"])
app.view_functions["sharing.open_model_share_link"] = limiter.limit(
    "30 per minute"
)(app.view_functions["sharing.open_model_share_link"])
app.view_functions["model_geometry.model_lods"] = limiter.limit(
    "20 per hour"
)(app.view_functions["model_geometry.model_lods"])
app.view_functions["model_geometry.model_derivatives"] = limiter.limit(
    "20 per hour"
)(app.view_functions["model_geometry.model_derivatives"])
app.view_functions["versions.restore_model_version"] = limiter.limit(
    "60 per minute"
)(app.view_functions["versions.restore_model_version"])
app.view_functions["versions.delete_model_version"] = limiter.limit(
    "60 per minute"
)(app.view_functions["versions.delete_model_version"])
for _endpoint in (
    "hotspots.create_hotspot", "hotspots.delete_hotspot", "hotspots.delete_all_hotspots",
    "hotspots.toggle_hotspots_visibility", "hotspots.create_camera_view", "hotspots.delete_camera_view",
):
    app.view_functions[_endpoint] = limiter.limit("60 per minute")(app.view_functions[_endpoint])
app.view_functions["engagement.create_model_analytics_event"] = limiter.limit(
    "120 per minute"
)(app.view_functions["engagement.create_model_analytics_event"])
for _endpoint in ("model_editing.save_modifications", "model_editing.slice_model"):
    app.view_functions[_endpoint] = limiter.limit("60 per minute")(app.view_functions[_endpoint])
app.view_functions["upload.upload_file"] = limiter.limit(
    "30 per hour"
)(app.view_functions["upload.upload_file"])
app.view_functions["upload.upload_model"] = limiter.limit(
    "30 per hour"
)(app.view_functions["upload.upload_model"])
app.view_functions["upload.batch_upload_models"] = limiter.limit(
    "10 per hour"
)(app.view_functions["upload.batch_upload_models"])
app.view_functions["upload.retry_upload_job"] = limiter.limit(
    "10 per hour"
)(app.view_functions["upload.retry_upload_job"])
# Admins are exempt from the AI abuse-guard rate limits (they're also exempt
# from the monthly quota via the unlimited plan) so admin testing/support isn't
# throttled.
_ai_rate_exempt = lambda: current_user.is_authenticated and getattr(current_user, "is_admin", False)
app.view_functions["ai_generation.generate_3d"] = limiter.limit(
    "6 per minute", exempt_when=_ai_rate_exempt
)(app.view_functions["ai_generation.generate_3d"])
app.view_functions["ai_generation.meshy_webhook"] = limiter.limit(
    "120 per minute"
)(app.view_functions["ai_generation.meshy_webhook"])
csrf.exempt(app.view_functions["ai_generation.meshy_webhook"])
app.view_functions["ai_image.generate_image"] = limiter.limit(
    "10 per minute", exempt_when=_ai_rate_exempt
)(app.view_functions["ai_image.generate_image"])

# Endpoints that cannot carry a session-bound CSRF token: 410 stubs that must
# keep answering old clients, capability-token/anonymous flows, and beacons
# fired from session-less cross-site embed iframes.
csrf.exempt(app.view_functions["upload.upload_file"])  # 410 stub
csrf.exempt(app.view_functions["upload.convert"])  # 410 stub
csrf.exempt(app.view_functions["upload.retry_upload_job"])  # capability-token auth
csrf.exempt(app.view_functions["engagement.track_download"])  # anonymous beacon
csrf.exempt(app.view_functions["engagement.create_model_analytics_event"])  # embed beacon

# Configure logging FIRST (before database operations)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)
configure_json_logging()
OBSERVABILITY_STATUS = initialize_external_observability(app)

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


import click


@app.cli.command("make-admin")
@click.argument("email")
def make_admin_command(email):
    """Grant admin panel access to the user with the given email."""
    user = User.query.filter_by(email=email).first()
    if user is None:
        click.echo(f"No user found with email {email}")
        raise SystemExit(1)
    user.is_admin = True
    db.session.commit()
    click.echo(f"{user.username} <{user.email}> is now an admin")


# Promote ADMIN_EMAILS (comma-separated) on boot — idempotent, covers deploys
# where a shell isn't handy. Wrapped defensively: on a legacy DB the is_admin
# column may not exist until `flask db upgrade` has run. The project owner is
# always promoted so the panel has an admin out of the box; add more via the
# ADMIN_EMAILS env var.
_DEFAULT_ADMIN_EMAILS = ["melikhanmutlu@gmail.com"]
_admin_emails = _DEFAULT_ADMIN_EMAILS + [
    e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()
]
if _admin_emails and os.environ.get("SKIP_DB_BOOTSTRAP", "").lower() not in (
    "1",
    "true",
    "yes",
):
    with app.app_context():
        try:
            for _user in User.query.filter(User.email.in_(_admin_emails)).all():
                if not _user.is_admin:
                    _user.is_admin = True
                    logger.info(f"ADMIN_EMAILS: promoted {_user.email} to admin")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"ADMIN_EMAILS promotion skipped: {e}")


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
                # For FBX/STEP files, we can't get mesh information directly
                if file_ext in (".fbx", ".step", ".stp"):
                    logger.info(
                        f"{file_ext} file detected - mesh information will be updated after conversion"
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

    if bounds is None:
        logger.warning("apply_size_limit: model has no geometry. Skipping scaling.")
        return mesh

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
        elif file_ext in (".step", ".stp"):
            converter = STEPConverter()
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
        model_url = f"{base_url}{url_for('viewer.view_model', model_id=model_id)}"

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
            if not model.filename or not os.path.exists(model.filename):
                logger.info(
                    f"Model {model.id} ({model.original_filename}) file not found at: {model.filename}"
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




# Static pages listed in sitemap.xml. Extend this as new marketing/landing
# pages are added. Model pages (/view, /embed, /vr) are deliberately not
# enumerated here — see _seo_robots_for_model_page() for whether they're
# indexable at all, and an unbounded number of user-uploaded models would
# need a paginated sitemap index, which is future work.


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

        # Blender writes to a temp path first, then we atomically rename onto
        # output_usdz_path — this runs in a daemon thread (see
        # refresh_usdz_after_edit) that can be killed mid-write by a deploy;
        # without this, a kill mid-export permanently corrupts an existing
        # model's USDZ with nothing to ever regenerate it.
        temp_usdz_path = f"{output_usdz_path}.tmp{os.getpid()}"

        # Construct command
        cmd = [
            blender_exec,
            "--background",
            "--python",
            blender_script,
            "--",
            input_glb_path,
            temp_usdz_path,
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

        if process.returncode == 0 and os.path.exists(temp_usdz_path):
            os.replace(temp_usdz_path, output_usdz_path)
            logger.info(f"USDZ conversion successful: {output_usdz_path}")
            return True
        else:
            logger.warning(f"USDZ conversion failed. Return code: {process.returncode}")
            logger.warning(f"Stdout: {process.stdout}")
            logger.warning(f"Stderr: {process.stderr}")
            if os.path.exists(temp_usdz_path):
                try:
                    os.remove(temp_usdz_path)
                except OSError:
                    pass
            return False

    except Exception as e:
        logger.error(f"Error during USDZ conversion: {e}")
        if os.path.exists(temp_usdz_path):
            try:
                os.remove(temp_usdz_path)
            except OSError:
                pass
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


def _atomic_replace(dest_path, tmp_path):
    """Atomically move a fully-written temp file onto dest_path.

    Thumbnail/USDZ generation runs in daemon threads that a deploy can kill
    mid-write; writing straight to dest_path would leave a permanently
    corrupt file behind (nothing ever re-checks an existing file for
    validity). Writing to tmp_path first and renaming here means dest_path
    only ever holds a complete file.
    """
    try:
        os.replace(tmp_path, dest_path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


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

        # First choice: render the actual geometry (software rasterizer, no GPU)
        from converters.thumbnail_render import render_thumbnail

        if render_thumbnail(input_glb_path, thumbnail_path):
            logger.info(
                f"[Thumbnail Async - {model_id}] Real 3D thumbnail rendered"
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
            tmp_thumbnail_path = f"{thumbnail_path}.tmp{os.getpid()}"
            img.save(tmp_thumbnail_path, "PNG")
            _atomic_replace(thumbnail_path, tmp_thumbnail_path)
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

            import html as _html
            # Escape values interpolated into the SVG (served as image/svg+xml):
            # defense in depth against a stored value breaking out of markup.
            thumb_color = _html.escape(color or model.color or "#667eea")
            name = _html.escape(model.original_filename[:20])
            file_type = _html.escape(model.file_type or "GLB")

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

                tmp_thumbnail_path = f"{thumbnail_path}.tmp{os.getpid()}"
                with open(tmp_thumbnail_path, "wb") as f:
                    f.write(png_data)
                _atomic_replace(thumbnail_path, tmp_thumbnail_path)

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


JOB_QUEUE_ENABLED = os.environ.get("JOB_QUEUE", "false").lower() in (
    "true",
    "1",
    "yes",
)

# UPLOAD_STALL_SECONDS and INLINE_STALE_JOB_MINUTES come from config.py
# (via `from config import *` above).


def _recover_interrupted_inline_job(job):
    """Restart (or fail) a job whose inline thread died with the process."""
    if JOB_QUEUE_ENABLED or job.status not in {"pending", "processing"}:
        return
    last_signal = job.last_heartbeat_at or job.started_at or job.created_at
    if not last_signal or last_signal > datetime.utcnow() - timedelta(
        minutes=INLINE_STALE_JOB_MINUTES
    ):
        return
    staged_dir = (job.payload or {}).get("temp_dir")
    recoverable = job.job_type != "upload" or (staged_dir and os.path.isdir(staged_dir))
    # Compare-and-set on the observed state so concurrent polls cannot both
    # claim the recovery and start duplicate inline threads.
    claimed = ConversionJob.query.filter(
        ConversionJob.id == job.id,
        ConversionJob.status == job.status,
        ConversionJob.last_heartbeat_at == job.last_heartbeat_at,
    ).update(
        {
            "status": "pending" if recoverable else "failed",
            "last_heartbeat_at": datetime.utcnow(),
            "next_attempt_at": datetime.utcnow() if recoverable else None,
            "finished_at": None if recoverable else datetime.utcnow(),
        }
        | ({} if recoverable else {"error": "Conversion was interrupted by a server restart"})
    )
    db.session.commit()
    if not claimed:
        db.session.refresh(job)
        return
    db.session.refresh(job)
    if recoverable:
        conversion_jobs.record(
            job, "inline_recovered", "Restarted after a server interruption"
        )
        _start_local_conversion(job.id)
    else:
        conversion_jobs.record(
            job, "failed", "Staged upload lost in a server interruption", level="error"
        )


def _start_local_conversion(job_id):
    def run_local_job():
        with app.app_context():
            queued_job = db.session.get(ConversionJob, job_id)
            if queued_job:
                run_conversion_job(queued_job, allow_retry=False)
    threading.Thread(target=run_local_job, daemon=True).start()


def _enqueue_internal_job(job_type, model_id, payload):
    """Persist a follow-up asset job before optionally starting it locally."""
    job_id = str(uuid.uuid4())
    job = ConversionJob(
        id=job_id,
        job_type=job_type,
        status="pending",
        model_id=model_id,
        user_id=payload.get("user_id"),
        payload={**payload, "model_id": model_id, "job_id": job_id},
    )
    db.session.add(job)
    db.session.commit()
    if not JOB_QUEUE_ENABLED:
        _start_local_conversion(job_id)
    return job


def update_conversion_progress(job, *, progress=None, stage=None, detail=None):
    conversion_jobs.update_progress(
        job, progress=progress, stage=stage, detail=detail
    )


def _notify_user_by_email(user_id, subject, body_text):
    """Best-effort notification helper -- see services/email.py. No-op for
    anonymous (user_id is None) jobs/actions."""
    if not user_id:
        return
    user = db.session.get(User, user_id)
    if user and user.email:
        send_email(user.email, subject, body_text)


def run_conversion_job(job, allow_retry=True):
    """Run a ConversionJob through the pipeline with status transitions.

    Failure puts the job back to 'pending' while attempts remain (so the
    worker retries), or 'failed' otherwise. Inline callers pass
    allow_retry=False because nothing would re-poll a pending job.
    """
    conversion_jobs.start(job)
    update_conversion_progress(
        job,
        progress=45,
        stage="Starting conversion",
        detail="The model has been received and the converter is starting.",
    )
    try:
        callback = lambda progress, stage, detail: update_conversion_progress(
            job, progress=progress, stage=stage, detail=detail
        )
        if job.job_type == "lod":
            model_id = _run_lod_pipeline(job.payload, progress_callback=callback)
        elif job.job_type in {"retopology", "texture_upscale"}:
            model_id = _run_derived_pipeline(job.payload, progress_callback=callback)
        elif job.job_type in {"thumbnail", "usdz"}:
            model_id = _run_auxiliary_asset_pipeline(job.payload, progress_callback=callback)
        else:
            model_id = _run_upload_pipeline(job.payload, progress_callback=callback)
        conversion_jobs.succeed(job, model_id)
        update_conversion_progress(
            job,
            progress=100,
            stage="Ready",
            detail="The model is ready for the viewer.",
        )
        if job.job_type == "upload":
            dispatch_webhook_event("conversion.completed", job.user_id, {
                "job_id": job.id, "model_id": model_id,
            })
            _notify_user_by_email(
                job.user_id, "Your model is ready",
                # Built without url_for(): this runs from a background
                # thread (inline/JOB_QUEUE=false mode) with only an app
                # context pushed, not a request context, and url_for()
                # requires one or the other (or SERVER_NAME configured).
                f"Your model has finished converting and is ready to view:\n"
                f"{SITE_URL}/view/{model_id}",
            )
    except Exception as e:
        retry = conversion_jobs.fail(job, e, allow_retry=allow_retry)
        update_conversion_progress(
            job,
            progress=35 if retry else 100,
            stage="Retrying" if retry else ("Dead letter" if allow_retry else "Failed"),
            detail=str(e)[:240],
        )
        logger.error(
            f"[conversion_job - {job.id}] attempt {job.attempts} failed "
            f"({'will retry' if retry else 'giving up'}): {e}"
        )
        if not retry and job.job_type == "upload":
            dispatch_webhook_event("conversion.failed", job.user_id, {
                "job_id": job.id, "error": str(e)[:240],
            })
        # Keep dead-letter staging for explicit replay/inspection. Inline jobs
        # cannot be replayed, so their staged files are cleaned immediately.
        if not retry and not allow_retry:
            staged_dir = (job.payload or {}).get("temp_dir")
            if staged_dir and os.path.exists(staged_dir):
                try:
                    shutil.rmtree(staged_dir)
                except Exception as cleanup_error:
                    logger.error(
                        f"[conversion_job - {job.id}] staged cleanup failed: {cleanup_error}"
                    )


def _run_lod_pipeline(payload, progress_callback=None):
    from converters.lod_generator import generate_lods
    model_id = payload["model_id"]
    model = get_live_model(model_id)
    if not model or not model.filename or not os.path.isfile(model.filename):
        raise RuntimeError("Model source is unavailable")
    report = progress_callback or (lambda *_: None)
    report(50, "Generating LODs", "Simplifying geometry into streaming variants.")
    model_dir = os.path.dirname(model.filename)
    temp_dir = os.path.join(model_dir, ".lod_" + payload.get("job_id", secrets.token_hex(4)))
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        outputs = generate_lods(
            model.filename,
            temp_dir,
            ratios=payload.get("ratios", [0.5, 0.25, 0.1]),
            meshopt=bool(payload.get("meshopt", True)),
        )
        report(85, "Publishing LODs", "Writing LOD manifest and assets.")
        ModelLOD.query.filter_by(model_id=model_id).delete()
        for output in outputs:
            destination = os.path.join(model_dir, output["filename"])
            os.replace(output["path"], destination)
            db.session.add(ModelLOD(
                model_id=model_id,
                level=output["level"], ratio=output["ratio"],
                filename=destination, file_size=output["file_size"],
            ))
        db.session.commit()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return model_id


def _run_derived_pipeline(payload, progress_callback=None):
    model_id = payload["model_id"]
    kind = payload["kind"]
    model = get_live_model(model_id)
    if not model or not os.path.isfile(model.filename):
        raise RuntimeError("Model source is unavailable")
    report = progress_callback or (lambda *_: None)
    model_dir = os.path.dirname(model.filename)
    if kind == "retopology":
        from converters.lod_generator import generate_lods
        report(55, "Retopologizing", "Building a cleaner reduced-topology variant.")
        temp_dir = os.path.join(model_dir, ".retopology_" + payload["job_id"])
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            output = generate_lods(
                model.filename, temp_dir,
                ratios=[payload.get("ratio", 0.65)], meshopt=False,
            )[0]
            filename = "model_retopology.glb"
            destination = os.path.join(model_dir, filename)
            os.replace(output["path"], destination)
            metadata = {"ratio": output["ratio"], "method": "gltfpack-simplify"}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    elif kind == "texture_upscale":
        from converters.texture_upscale import upscale_embedded_textures
        report(55, "Upscaling textures", "Resampling embedded textures into a high-resolution variant.")
        filename = f"model_textures_{int(payload.get('factor', 2))}x.glb"
        destination = os.path.join(model_dir, filename)
        temp = destination + ".tmp"
        metadata = upscale_embedded_textures(
            model.filename, temp, factor=payload.get("factor", 2)
        )
        finalize_glb(temp, search_dirs=[model_dir], strict=True)
        os.replace(temp, destination)
    else:
        raise RuntimeError("Unknown derived asset kind")
    ModelDerivedAsset.query.filter_by(model_id=model_id, kind=kind).delete()
    db.session.add(ModelDerivedAsset(
        model_id=model_id, kind=kind, filename=destination,
        file_size=os.path.getsize(destination), asset_metadata=metadata,
    ))
    db.session.commit()
    return model_id


def _run_auxiliary_asset_pipeline(payload, progress_callback=None):
    model_id = payload["model_id"]
    model = get_live_model(model_id)
    if not model or not model.filename or not os.path.isfile(model.filename):
        raise RuntimeError("Model source is unavailable")
    report = progress_callback or (lambda *_: None)
    if payload.get("kind") == "usdz":
        report(55, "Preparing iOS AR", "Converting the model to USDZ.")
        output_path = os.path.join(os.path.dirname(model.filename), "model.usdz")
        if not convert_to_usdz(model.filename, output_path):
            raise RuntimeError("USDZ conversion failed")
        model.usdz_filename = output_path
        db.session.commit()
    elif payload.get("kind") == "thumbnail":
        report(55, "Creating preview", "Rendering the model thumbnail.")
        generate_thumbnail_async(model_id, model.filename, payload.get("color"))
        output_path = os.path.join(os.path.dirname(model.filename), "thumbnail.png")
        if not os.path.isfile(output_path):
            raise RuntimeError("Thumbnail generation failed")
    else:
        raise RuntimeError("Unknown auxiliary asset kind")
    report(95, "Publishing asset", "The generated asset is ready.")
    return model_id


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

    # Idempotency guard: if a prior attempt already completed the UserModel
    # insert (below) but the job was retried anyway -- e.g. it failed/crashed
    # afterward, or a stale-job sweep requeued it before its "completed"
    # status was recorded (the very case where the staged temp source below
    # has often already been cleaned up) -- re-running the whole pipeline
    # would redo a perfectly good conversion and then crash on the duplicate
    # primary key. Short-circuit instead: the id is a UUID the pipeline chose
    # once, so its presence in the table means this exact attempt already
    # succeeded. Guarded by has_app_context() so this otherwise-pure function
    # can still be called (and reach the file-existence check below) with no
    # Flask app/request context active -- true of every real caller (worker.py
    # and inline request handlers both run inside one) but not of a raw
    # function-level test.
    if has_app_context():
        existing = db.session.get(UserModel, unique_id)
        if existing is not None:
            logger.info(f"[upload_model - {unique_id}] UserModel already exists; retry is a no-op")
            return existing.id

    # Staged source must still exist. Requeued/stale jobs (e.g. picked up
    # after a redeploy) often point at a temp file that was already cleaned
    # up; fail fast and clearly instead of cascading into assimp "Could not
    # import file!" and an FBX2glTF cwd FileNotFoundError.
    if not temp_file_path or not os.path.exists(temp_file_path):
        raise RuntimeError(
            "Source file is no longer available — please re-upload the model."
        )

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
        conversion_result = conversion_service.convert(payload, output_path, progress=report)
        converter = conversion_result["converter"]
        service_converted = True
        # Legacy orchestration below remains temporarily for dimension metadata;
        # format dispatch itself is owned by ConversionService.
        if service_converted:
            pass
        elif file_extension == ".obj":
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
        elif file_extension in (".step", ".stp"):
            # STEP carries real units; cascadio converts to meters directly
            converter = STEPConverter()
        elif file_extension in (".glb", ".gltf"):
            # GLB is already the target format; GLTF can be loaded+exported as GLB
            converter = None  # No converter needed, handle directly below

        # Handle GLB/GLTF directly (no converter needed)
        if service_converted:
            conversion_success = True
        elif file_extension in (".glb", ".gltf"):
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
            compression = payload.get("compression")
            if not service_converted:
                optimize_glb(
                    output_path,
                    enabled=None if compression is None else compression == "meshopt",
                )
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

        # Normalize model to center origin for consistent pivot behavior.
        # ConversionService already normalizes (and compresses last), so
        # re-running a pygltflib save here would corrupt a meshopt/draco
        # buffer ("buffer too short") -- skip for service-converted models.
        if not service_converted:
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

        quality_warnings = []
        asset_report = None
        # GLB quality pass: embed stray external textures, guarantee PBR
        # materials, validate (warn-only — never blocks a viewable upload).
        # ConversionService already ran finalize_glb + inspect on the
        # uncompressed geometry and then compressed as its last step; re-running
        # them here would (a) corrupt a meshopt/draco buffer via pygltflib save
        # and (b) misread geometry counts from the compressed file. Reuse the
        # service's results instead.
        if service_converted:
            quality_warnings = conversion_result.get("quality_warnings") or []
            asset_report = conversion_result.get("asset_report")
        else:
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
            try:
                asset_report = asset_quality.inspect(output_path, quality_warnings)
            except Exception as e:
                logger.warning(f"[upload_model - {unique_id}] Asset report failed: {e}")
                asset_report = {"valid": False, "warnings": [f"Inspection failed: {e}"]}

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

        # Prefer the dimensions ConversionService measured on the UNcompressed
        # geometry (before its final compression step). Re-measuring the stored
        # file here is unreliable once it's meshopt-compressed (quantized
        # coordinates), so use the service's value when available.
        if not model_bounds and service_converted:
            svc_dims = conversion_result.get("dimensions_cm")
            if svc_dims:
                import json
                model_bounds = json.dumps({
                    "extents": [svc_dims["x"], svc_dims["y"], svc_dims["z"]],
                    "max": svc_dims["max"],
                })
                logger.info(f"[upload_model - {unique_id}] Using service dimensions: {svc_dims}")

        # If not FBX or FBX dimensions failed, try from GLB
        if not model_bounds:
            try:
                import trimesh
                import numpy as np
                import json
                from converters.glb_optimizer import readable_glb

                # If the output was meshopt/draco compressed, trimesh reads it
                # as empty geometry -- decompress to a temp copy first, or the
                # stored dimensions would be all zeros (and the viewer would
                # show 0 x 0 x 0, blocking slicing).
                with readable_glb(output_path) as readable_path:
                    mesh = trimesh.load(readable_path)
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
            display_name=os.path.splitext(
                payload.get("client_filename", original_filename)
            )[0][:255],
            bounds=model_bounds,  # Store dimensions
            original_dimensions=original_dims,  # Store original dimensions
            cumulative_scale=1.0,  # Initial scale is 1.0
            edit_token_hash=payload.get("edit_token_hash"),
            validation_report=asset_report,
            vertices=(asset_report or {}).get("vertices"),
            faces=(asset_report or {}).get("triangles"),
            source_filename=str(payload.get("client_filename", original_filename))[:255],
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

        # Follow-up assets are durable jobs. A process restart can no longer
        # silently lose thumbnail or iOS AR generation work.
        report(97, "Creating previews", "Queueing thumbnail and iOS AR assets.")
        _enqueue_internal_job(
            "thumbnail", unique_id,
            {"kind": "thumbnail", "color": color if use_color else None, "user_id": user_id},
        )
        _enqueue_internal_job(
            "usdz", unique_id,
            {"kind": "usdz", "user_id": user_id},
        )

        return unique_id

    except Exception as e:
        # Staged files are NOT deleted here — a retrying worker needs them.
        # run_conversion_job cleans up when it gives up for good.
        logger.error(f"[upload_model - {unique_id}] Pipeline error: {str(e)}")
        logger.error(traceback.format_exc())
        raise


@app.errorhandler(413)
def too_large(e):
    max_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return jsonify(
        {"error": f"File is too large. Maximum file size is {max_mb}MB."}
    ), 413


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Server error. Please try again later."}), 500


def check_model_files():
    """Report missing model storage without deleting durable metadata."""
    session = None
    try:
        session = Session(db.engine)
        models = session.query(UserModel).all()

        for model in models:
            # Check if model files exist
            converted_dir = os.path.join(app.config["CONVERTED_FOLDER"], model.id)
            upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], model.id)

            # Storage can be temporarily unavailable during a volume remount.
            # Never turn a transient filesystem outage into permanent DB loss.
            if not os.path.exists(converted_dir) and not os.path.exists(upload_dir):
                logger.warning(
                    f"Files for model {model.id} are currently unavailable"
                )
    except Exception as e:
        logger.error(f"Error checking model files: {str(e)}")
        if session:
            session.rollback()
    finally:
        if session:
            session.close()


@app.before_request
def before_request():
    """Per-request hook.

    Previously this ran check_model_files() on every /my_models load — an
    O(N) full-table scan + filesystem stat that *deleted* model rows (including
    other users') whenever a directory looked missing. A transient volume mount
    hiccup could mass-delete models. That destructive sweep has been removed
    from the request path; check_model_files() remains available for an
    explicit offline/maintenance job.

    Now enforces the admin-controlled maintenance mode: admins and the
    admin/login/static paths stay reachable, everything else gets a 503.
    """
    if setting_bool("maintenance_mode", False):
        exempt = request.path.startswith(
            ("/admin", "/login", "/logout", "/static", "/favicon.ico",
             "/robots.txt", "/sitemap.xml")
        )
        is_admin = current_user.is_authenticated and getattr(
            current_user, "is_admin", False
        )
        if not exempt and not is_admin:
            return render_template("maintenance.html"), 503
    return None


@app.context_processor
def inject_announcement():
    """Admin-set announcement banner, rendered by base.html on every page."""
    return {"announcement_text": get_setting("announcement_text", "") or ""}


@app.context_processor
def inject_seo_defaults():
    """Site-wide SEO context (SITE_URL for absolute canonical/OG URLs,
    GOOGLE_SITE_VERIFICATION for the GSC verification meta tag) — available
    in every template without each route passing them explicitly."""
    return {"SITE_URL": SITE_URL, "GOOGLE_SITE_VERIFICATION": GOOGLE_SITE_VERIFICATION}


# ========== MODEL VERSION MANAGEMENT ==========




# ===================================================================
# HOTSPOT CRUD API
# ===================================================================



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
    quality_warnings = []
    try:
        quality_warnings = finalize_glb(output_path, search_dirs=[converted_dir,
                                                                  os.path.dirname(glb_path)])
        for w in quality_warnings:
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

    try:
        ai_asset_report = asset_quality.inspect(output_path, quality_warnings)
    except Exception as e:
        ai_asset_report = {"valid": False, "warnings": [f"Inspection failed: {e}"]}
    clean_prompt = (prompt or "").strip()
    seo_title = (clean_prompt[:60] if clean_prompt else "AI generated 3D model")
    seo_description = (
        f"Interactive AR-ready 3D model generated from: {clean_prompt[:150]}"
        if clean_prompt else "Interactive AR-ready AI generated 3D model."
    )
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
        description=(
            (f"AI generated ({source})" if source.startswith("ai") else f"Combined scene ({source})")
            + (f": {prompt}" if prompt else "")
        ),
        validation_report=ai_asset_report,
        vertices=ai_asset_report.get("vertices"),
        faces=ai_asset_report.get("triangles"),
        seo_metadata={
            "title": seo_title,
            "description": seo_description,
            "keywords": ["3D model", "AR", "AI generated", source],
        },
        source=source,
    )
    db.session.add(model)
    db.session.commit()

    try:
        create_version(model_id=unique_id, operation_type="upload",
                       operation_details={"source": source, "prompt": prompt},
                       comment="AI generation")
    except Exception as e:
        logger.error(f"[register_glb] version failed: {e}")

    _enqueue_internal_job(
        "thumbnail", unique_id,
        {"kind": "thumbnail", "color": color, "user_id": user_id},
    )
    if not usdz_filename:
        _enqueue_internal_job(
            "usdz", unique_id,
            {"kind": "usdz", "user_id": user_id},
        )

    return model


def _stash_texture_reference(job_id, data_uri):
    """Persist a refine-stage texture reference image to a temp file so it
    survives between the initial request and the later async refine call
    (texture_prompt/texture_image_url only apply once refine starts).
    Never stored inline as base64 in the DB. Cleaned up by the reconciliation
    sweep alongside abandoned jobs."""
    if not isinstance(data_uri, str) or not data_uri.startswith("data:image/"):
        return None
    tmp_dir = os.path.join(app.config["TEMP_FOLDER"], "ai_texture")
    os.makedirs(tmp_dir, exist_ok=True)
    path = os.path.join(tmp_dir, f"{job_id}.txt")
    with open(path, "w") as f:
        f.write(data_uri)
    return path


def _load_texture_reference(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return f.read()


def _ai_quota_state(user_id):
    """Per-user monthly (rolling 30-day) AI generation quota. Counts
    AIGenerationJob rows -- text/image generation spends real Meshy credits,
    so an admin setting ai_monthly_limit to 0 to disable Meshy usage entirely
    must cover it."""
    from datetime import timedelta
    from services.plans import effective_ai_monthly_limit
    since = datetime.utcnow() - timedelta(days=30)
    # Admin-editable override; falls back to the env default when unset.
    # The user's plan (services/plans.py) sets the per-tier monthly ceiling.
    global_default_limit = setting_int("ai_monthly_limit", app.config.get("AI_GEN_MONTHLY_LIMIT", 0))
    user = db.session.get(User, user_id) if user_id else None
    limit = effective_ai_monthly_limit(user, global_default_limit)
    count = AIGenerationJob.query.filter(
        AIGenerationJob.user_id == user_id,
        AIGenerationJob.created_at >= since,
    ).count()
    return (count >= limit), count, limit


def _consume_ai_allowance(user):
    """Decide whether an AI generation may proceed for `user`, consuming one
    prepaid overage credit when the monthly plan quota is exhausted.

    Call this while holding a row lock on `user` (SELECT ... FOR UPDATE) so
    concurrent requests can't each spend the same last credit. When the plan
    quota is used up but a credit is spent, the balance is decremented on the
    session but NOT committed -- it rides with the caller's job-creation
    commit, so a failed generation doesn't burn a credit.

    Returns (allowed, count, limit): `count`/`limit` are the monthly plan
    quota state (for the error message); allowance may still be granted via a
    credit even when count >= limit.
    """
    exceeded, count, limit = _ai_quota_state(user.id)
    if not exceeded:
        return True, count, limit
    if (user.ai_credit_balance or 0) > 0:
        user.ai_credit_balance -= 1
        return True, count, limit
    return False, count, limit




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


# Hosts Meshy serves generated GLBs/textures from. Used to allowlist the
# remote-texture embed (SSRF guard) so we only fetch texture images referenced
# by a Meshy-authored GLB, never an arbitrary URL.
MESHY_TEXTURE_HOSTS = ["meshy.ai", "amazonaws.com", "cloudfront.net"]


def _finalize_ai_job(job, task):
    """Download finished GLB (+USDZ), register as model, mark job ready.

    Pure job-mutation + commit (no HTTP response built here) -- shared by the
    client-poll route, the webhook receiver and the reconciliation sweep.
    Returns the created UserModel, or None if Meshy returned no GLB (job is
    marked failed in that case instead)."""
    import ai_generator

    model_urls = task.get("model_urls") or {}
    glb_url = model_urls.get("glb")
    if not glb_url:
        job.status = "failed"
        job.error = "Generation finished but returned no GLB"
        db.session.commit()
        dispatch_webhook_event("ai_generation.failed", job.user_id, {
            "job_id": job.id, "error": job.error,
        })
        return None

    tmp_dir = os.path.join(app.config["TEMP_FOLDER"], "ai_" + job.id)
    os.makedirs(tmp_dir, exist_ok=True)
    glb_tmp = os.path.join(tmp_dir, "model.glb")
    ai_generator.download(glb_url, glb_tmp)

    # Diagnose + self-heal textures BEFORE registration (which runs a pygltflib
    # round-trip). Logs exactly what Meshy returned (so an untextured result is
    # one-glance diagnosable), then embeds any externally-referenced (CDN/signed
    # URL) textures so the model is self-contained -- otherwise it renders
    # untextured under CSP/CORS or once Meshy's signed URLs expire. Never fails
    # the job.
    try:
        from converters.glb_quality import (
            attach_base_color_texture_files, embed_remote_textures,
            has_embedded_base_color_textures, inspect_texture_state,
        )
        logger.info(
            "[generate-3d] job=%s texture state: %s | model_urls=%s | texture_urls=%d",
            job.id, inspect_texture_state(glb_tmp), sorted(model_urls.keys()),
            len(task.get("texture_urls") or []),
        )
        if embed_remote_textures(glb_tmp, allowed_hosts=MESHY_TEXTURE_HOSTS):
            logger.info("[generate-3d] job=%s embedded remote Meshy textures", job.id)
        # Some successful image-to-3D tasks return a texture-less GLB and expose
        # the artwork only through texture_urls. There is no image URI for
        # embed_external_textures to resolve in that case, so download Meshy's
        # base-color maps and explicitly bind/embed them into the GLB.
        if not has_embedded_base_color_textures(glb_tmp) and task.get("texture_urls"):
            from urllib.parse import urlparse as _urlparse
            texture_entries = task["texture_urls"]
            if isinstance(texture_entries, dict):
                texture_entries = [texture_entries]
            base_color_files = []
            base_color_keys = {"base_color", "basecolor", "albedo", "diffuse", "diffuse_color"}
            for index, tex in enumerate(texture_entries):
                if not isinstance(tex, dict):
                    continue
                map_url = next((
                    value for key, value in tex.items()
                    if str(key).lower().replace("-", "_") in base_color_keys
                    and isinstance(value, str)
                    and value.lower().startswith(("http://", "https://"))
                ), None)
                if not map_url:
                    continue
                parsed = _urlparse(map_url)
                host = (parsed.hostname or "").lower()
                if not any(host == allowed or host.endswith("." + allowed)
                           for allowed in MESHY_TEXTURE_HOSTS):
                    logger.warning("[generate-3d] skipped untrusted texture host: %s", host)
                    continue
                suffix = os.path.splitext(parsed.path)[1].lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                    suffix = ".png"
                destination = os.path.join(tmp_dir, f"meshy_base_color_{index}{suffix}")
                try:
                    if ai_generator.download(map_url, destination):
                        base_color_files.append(destination)
                except Exception as texture_exc:
                    logger.warning("[generate-3d] base-color download failed: %s", texture_exc)
            if attach_base_color_texture_files(glb_tmp, base_color_files):
                logger.info(
                    "[generate-3d] job=%s attached %d Meshy base-color texture(s)",
                    job.id, len(base_color_files),
                )
    except Exception as exc:
        logger.warning("[generate-3d] job=%s texture diagnose/heal skipped: %s", job.id, exc)

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
    dispatch_webhook_event("ai_generation.completed", job.user_id, {
        "job_id": job.id, "model_id": model.id,
    })
    return model


def _advance_ai_job(job):
    """Advance a 'generating' AIGenerationJob by one step using whatever
    Meshy task state is available right now: poll the active Meshy task, and
    if it just finished, either kick off the next stage (preview -> refine)
    or finalize (download + register the model).

    Shared by the client-poll route (generate_3d_status), the Meshy webhook
    receiver, and worker.py's reconciliation sweep -- all three call this
    identically, so the existing _claim_ai_stage atomic claim prevents any
    two of them from double-starting a refine or double-registering a model
    for the same job (e.g. a webhook firing while a browser tab is also
    polling). Mutates and commits `job`; raises on transient failures
    (ai_generator.MeshyError etc.) so callers can decide how to react
    (poll route -> 502 to the client, sweep/webhook -> log and move on).
    """
    import ai_generator

    if job.status in ("ready", "failed"):
        return

    if job.kind == "image":
        if job.stage == "image":
            t = ai_generator.get_task("image", job.meshy_image_id)
            job.progress = min(99, t["progress"])
            if t["status"] == ai_generator.SUCCEEDED:
                if not _claim_ai_stage(job.id, "image", "finalizing"):
                    db.session.refresh(job)  # another poll is finalizing
                else:
                    try:
                        _finalize_ai_job(job, t)
                        return
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
                    job_options = job.options or {}
                    texture_image_url = _load_texture_reference(job.texture_ref)
                    try:
                        refine_id = ai_generator.start_refine(
                            job.meshy_preview_id,
                            texture_prompt=job_options.get("texture_prompt"),
                            texture_image_url=texture_image_url,
                            moderation=job_options.get("moderation"),
                            remove_lighting=job_options.get("remove_lighting"))
                    except Exception:
                        # release the claim so the next poll retries
                        _claim_ai_stage(job.id, "refining", "preview")
                        raise
                    job.meshy_refine_id = refine_id
                    job.stage = "refine"
                    job.progress = 50
                    if job.texture_ref:
                        try:
                            os.remove(job.texture_ref)
                        except OSError:
                            pass
                        job.texture_ref = None
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
                        _finalize_ai_job(job, t)
                        return
                    except Exception:
                        _claim_ai_stage(job.id, "finalizing", "refine")
                        raise
            elif t["status"] in (ai_generator.FAILED, ai_generator.CANCELED):
                job.status = "failed"
                job.error = t.get("task_error") or "Texturing failed"

    db.session.commit()
    if job.status == "failed":
        dispatch_webhook_event("ai_generation.failed", job.user_id, {
            "job_id": job.id, "error": job.error,
        })


if __name__ == "__main__":
    if init_app_dependencies():
        app.logger.info("Dependencies initialized successfully")
        # Railway/Heroku için PORT environment variable
        port = int(os.environ.get("PORT", 5000))
        # threaded=True: a long-lived SSE connection (/api/upload-jobs/<id>/stream)
        # would otherwise tie up this dev server's single worker for its whole
        # duration, blocking every other request until it closes.
        app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False), threaded=True)
    else:
        app.logger.error("Failed to initialize dependencies")
