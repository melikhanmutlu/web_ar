from datetime import timedelta
from services.time_utils import datetime
import os
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
from models import db, User, UserModel, Folder, Organization, OrganizationMember, OrganizationDomain, ApiToken, PromptPreset, MaterialPreset, ModelVersion, ModelLOD, ModelDerivedAsset, ModelLike, ModelSave, ModelHotspot, ModelShareLink, ModelAnalyticsEvent, CameraView, AIGenerationJob, ConversionJob, WorkerHeartbeat
from auth import auth
from admin import admin_bp
from blueprints.health import health_bp
from blueprints.seo import seo_bp
from blueprints.material_presets import material_presets_bp, _resolve_prompt_preset
from blueprints.api_tokens import api_tokens_bp, api_token_rate_limit_key
from blueprints.organizations import organizations_bp
from blueprints.workspace import workspace_bp
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
from blueprints.billing import billing_bp
from model_cleanup import purge_model_completely
from site_settings import get_setting, setting_bool
import re
import traceback
import uuid
import hashlib
from urllib.parse import urlparse, urlsplit
from flask_compress import Compress
from flask_migrate import Migrate
from config import *
from sqlalchemy.orm import Session
from slugify import slugify
import trimesh
from glb_modifier import modify_glb
import time
from version_manager import (
    get_version_history,
    restore_version,
    delete_version,
    version_path,
)
from services import AssetQualityService, ConversionJobService, ConversionService, ModelAccessService, StorageService, UploadStagingService, configure_json_logging, initialize_external_observability
from services.model_permissions import (
    model_access,
    check_model_mutation_allowed,
    check_model_view_allowed,
    _active_share_grant,
)
from services.model_analytics import ANALYTICS_EVENT_TYPES, record_model_event
from services.viewer_settings import DEFAULT_VIEWER_SETTINGS, resolved_viewer_settings
from services.org_branding import resolved_org_branding
from services.storage_quota import (
    TRASH_RETENTION_DAYS,
    _purge_expired_trash,
    _storage_usage_for,
    _storage_quota_bytes,
)
from services.org_membership import _organization_membership, org_allows
from services import upload_pipeline

app = Flask(__name__)
app.config.from_object("config")
# Number of trusted reverse-proxy hops in front of the app (Railway: 1). The
# client IP used by every per-IP rate limit is taken that many hops from the
# right of X-Forwarded-For, so set this to match the deployment (0 = no proxy,
# ignore X-Forwarded-For entirely).
try:
    _PROXY_HOPS = max(0, int(os.environ.get("PROXY_FIX_X_FOR", "1")))
except ValueError:
    _PROXY_HOPS = 1
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=_PROXY_HOPS, x_proto=1, x_host=1)


# Baseline security headers on every response. X-Frame-Options is only sent for
# non-embed pages because /embed/<id> is designed to be iframed by third parties.
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
            # (EMBED_DEFAULT_FRAME_ANCESTORS can narrow this default.)
            frame_ancestors = os.environ.get("EMBED_DEFAULT_FRAME_ANCESTORS", "*").strip() or "*"
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        # 'wasm-unsafe-eval' is REQUIRED: model-viewer's decoders (meshopt,
        # and the self-hosted DRACO/KTX2 decoders) compile WebAssembly. Without it the
        # decoder's WebAssembly.instantiate() is refused, the loader's
        # decoder promise rejects, and EVERY model load fails -- blank
        # viewer, dead AR/fullscreen buttons on all devices.
        "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://ajax.googleapis.com https://cdnjs.cloudflare.com https://aframe.io https://cdn.rawgit.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        # GLTFLoader turns images embedded in a GLB binary chunk into blob:
        # URLs and fetches them before uploading to WebGL. blob: therefore
        # belongs in connect-src as well as img-src; without it every embedded
        # material texture is blocked and model-viewer renders a white mesh.
        "img-src 'self' data: blob: https:; connect-src 'self' https: blob:; "
        "worker-src 'self' blob:; "
        f"frame-ancestors {frame_ancestors}",
    )
    if request.endpoint != "viewer.embed_view":
        # Clickjacking fallback for browsers without CSP frame-ancestors, and
        # popup isolation that still lets payment/OAuth popups work.
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    if request.is_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Keep per-user HTML pages (my_models, studio, billing, admin, ...) out of
    # shared/proxy caches and the browser back-forward cache. Scoped to HTML so
    # cacheable static assets are unaffected; endpoints that set their own
    # Cache-Control (e.g. the viewer's no-store data routes) win via the guard.
    if (current_user.is_authenticated
            and response.mimetype == "text/html"
            and "Cache-Control" not in response.headers):
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers.setdefault("Vary", "Cookie")
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


# All DB timestamps are naive UTC (see services/time_utils). Render them in the
# app's display timezone -- default GMT+3 (Turkey / Europe/Istanbul), a fixed
# offset with no DST. Override with DISPLAY_TZ_OFFSET_HOURS if ever needed.
DISPLAY_TZ_OFFSET = timedelta(hours=int(os.getenv("DISPLAY_TZ_OFFSET_HOURS", "3")))


def to_display_tz(value):
    """Shift a naive-UTC datetime to the display timezone. None-safe."""
    return value + DISPLAY_TZ_OFFSET if value else None


@app.template_filter("localdt")
def _localdt(value, fmt="%Y-%m-%d %H:%M"):
    """Jinja filter: format a naive-UTC datetime in the display timezone."""
    local = to_display_tz(value)
    return local.strftime(fmt) if local else ""

from services.plans import format_mb as _format_mb, format_money as _format_money
app.add_template_filter(_format_mb, "format_mb")
app.add_template_filter(_format_money, "money")

# Initialize extensions
db.init_app(app)
# CSRF protection for all state-changing requests. Token is bound to the session
# (no hard time limit) so long-lived viewer/editor pages don't fail mutations.
app.config.setdefault("WTF_CSRF_TIME_LIMIT", None)
csrf = CSRFProtect(app)
migrate = Migrate(app, db)

# Response compression (br/gzip) for text payloads only. GLB/USDZ/images are
# already compressed and text/event-stream (job progress SSE) must stay
# unbuffered, so neither mimetype is listed.
app.config["COMPRESS_MIMETYPES"] = [
    "text/html",
    "text/css",
    "text/xml",
    "text/javascript",
    "application/javascript",
    "application/json",
    "image/svg+xml",
    "application/wasm",
]
Compress(app)

# Initialize login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "auth.login"


@login_manager.user_loader
def load_user(user_id):
    # "<id>:<session_version>" (User.get_id); a bare id is a pre-versioning
    # cookie and counts as version 0, so it dies at the first password change.
    raw_id, _, version = str(user_id).partition(":")
    try:
        user = db.session.get(User, int(raw_id))
        version = int(version or 0)
    except ValueError:
        return None
    if user is None or (user.session_version or 0) != version:
        return None
    if not user.is_active:
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
    # Emit X-RateLimit-Limit/Remaining/Reset on limited endpoints so API
    # integrators can self-throttle instead of hitting 429s blind.
    headers_enabled=True,
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
upload_pipeline.configure(
    conversion_jobs=conversion_jobs,
    conversion_service=conversion_service,
    asset_quality=asset_quality,
)


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
    # Custom domains are a paid org feature, checked at serve time too so a
    # downgraded owner's domain stops serving without deleting the record.
    if g.custom_domain and not org_allows(g.custom_domain.organization, "custom_domains"):
        g.custom_domain = None
    if g.custom_domain and request.endpoint == "main.index" and request.method == "GET":
        organization = g.custom_domain.organization
        models = UserModel.query.filter(
            UserModel.organization_id == organization.id,
            UserModel.visibility == "public",
            UserModel.deleted_at.is_(None),
        ).order_by(UserModel.upload_date.desc()).all()
        return render_template(
            "custom_domain.html", organization=organization,
            models=models, branding=resolved_org_branding(organization),
        )


# Register blueprints
app.register_blueprint(auth)
app.register_blueprint(admin_bp)
app.register_blueprint(health_bp)
app.register_blueprint(seo_bp)
app.register_blueprint(material_presets_bp)
app.register_blueprint(api_tokens_bp)
app.register_blueprint(organizations_bp)
app.register_blueprint(workspace_bp)
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
app.register_blueprint(billing_bp)
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
app.view_functions["auth.forgot_password"] = limiter.limit(
    "5 per hour", methods=["POST"]
)(app.view_functions["auth.forgot_password"])
app.view_functions["auth.reset_password"] = limiter.limit(
    "10 per hour", methods=["POST"]
)(app.view_functions["auth.reset_password"])
app.view_functions["auth.resend_verification"] = limiter.limit(
    "5 per hour", methods=["POST"]
)(app.view_functions["auth.resend_verification"])
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
# Anonymous, view-tier counter writes: throttle per IP so a public/unlisted
# model's share/download counts (and their ModelAnalyticsEvent rows) can't be
# inflated without bound.
for _endpoint in ("engagement.track_share", "engagement.track_download"):
    app.view_functions[_endpoint] = limiter.limit("60 per minute")(app.view_functions[_endpoint])
# Likes and the /view counter write are anonymous too (SEC-12); the per-visitor
# dedupe lives in services/abuse_guard.py, this adds a coarse per-IP/user cap.
app.view_functions["viewer.view_model"] = limiter.limit(
    "120 per minute"
)(app.view_functions["viewer.view_model"])
for _endpoint in ("engagement.toggle_like",):
    app.view_functions[_endpoint] = limiter.limit("60 per minute")(app.view_functions[_endpoint])
# Hotspot comments are open to any logged-in viewer of a public model: slow spam.
app.view_functions["hotspots.create_hotspot_comment"] = limiter.limit(
    "10 per minute"
)(app.view_functions["hotspots.create_hotspot_comment"])
for _endpoint in ("model_editing.save_modifications", "model_editing.slice_model"):
    app.view_functions[_endpoint] = limiter.limit("60 per minute")(app.view_functions[_endpoint])
app.view_functions["upload.upload_file"] = limiter.limit(
    "30 per hour"
)(app.view_functions["upload.upload_file"])
app.view_functions["upload.upload_model"] = limiter.limit(
    "30 per hour"
)(app.view_functions["upload.upload_model"])
app.view_functions["upload.init_chunked_upload"] = limiter.limit(
    "30 per hour"
)(app.view_functions["upload.init_chunked_upload"])
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
    "10 per minute;60 per day", exempt_when=_ai_rate_exempt
)(app.view_functions["ai_image.generate_image"])

# Endpoints that cannot carry a session-bound CSRF token: 410 stubs that must
# keep answering old clients, capability-token/anonymous flows, and beacons
# fired from session-less cross-site embed iframes.
csrf.exempt(app.view_functions["upload.upload_file"])  # 410 stub
csrf.exempt(app.view_functions["upload.convert"])  # 410 stub
csrf.exempt(app.view_functions["upload.retry_upload_job"])  # capability-token auth
csrf.exempt(app.view_functions["engagement.track_download"])  # anonymous beacon
csrf.exempt(app.view_functions["engagement.create_model_analytics_event"])  # embed beacon
csrf.exempt(app.view_functions["auth.unsubscribe"])  # signed-token link / mail-client one-click POST

# Programmatic write API (/api/v1): authenticated by Bearer API token, not a
# session, so it can't carry a CSRF token. Rate-limit each endpoint per token
# (api_token_rate_limit_key) so one integration can't exhaust another's budget;
# the upload endpoint gets a tighter limit than the metadata reads/writes.
app.view_functions["api_tokens.api_v1_create_model"] = limiter.limit(
    "30 per minute", key_func=api_token_rate_limit_key
)(app.view_functions["api_tokens.api_v1_create_model"])
for _endpoint in (
    "api_tokens.api_v1_models",
    "api_tokens.api_v1_model",
    "api_tokens.api_v1_model_analytics",
    "api_tokens.api_v1_job_status",
    "api_tokens.api_v1_update_model",
    "api_tokens.api_v1_delete_model",
):
    app.view_functions[_endpoint] = limiter.limit(
        "120 per minute", key_func=api_token_rate_limit_key
    )(app.view_functions[_endpoint])
for _endpoint in (
    "api_tokens.api_v1_create_model",
    "api_tokens.api_v1_update_model",
    "api_tokens.api_v1_delete_model",
):
    csrf.exempt(app.view_functions[_endpoint])

# PayTR server-to-server callback: authenticated by the gateway's hash (not a
# session), so CSRF-exempt, and rate-limited like the Meshy webhook.
app.view_functions["billing.paytr_callback"] = limiter.limit(
    "120 per minute"
)(app.view_functions["billing.paytr_callback"])
csrf.exempt(app.view_functions["billing.paytr_callback"])
app.view_functions["billing.lemonsqueezy_webhook"] = limiter.limit(
    "120 per minute"
)(app.view_functions["billing.lemonsqueezy_webhook"])
csrf.exempt(app.view_functions["billing.lemonsqueezy_webhook"])
# Public sales-enquiry form: throttle POST submissions to blunt spam/abuse.
app.view_functions["main.contact_sales"] = limiter.limit(
    "10 per hour", methods=["POST"]
)(app.view_functions["main.contact_sales"])

# Configure logging FIRST (before database operations)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],  # stdout/stderr only; the platform collects it
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
        _inspection_failed = False
        try:
            from sqlalchemy import inspect as _sa_inspect

            _inspector = _sa_inspect(db.engine)
            _has_alembic = _inspector.has_table("alembic_version")
        except Exception as e:
            # Unknown state (e.g. a transient DB error): do NOT assume "no
            # alembic_version" — create_all + stamp head on a schema that never
            # ran its migrations would mask them forever.
            logger.error(f"DB inspection failed; skipping schema bootstrap/stamp: {e}")
            _inspection_failed = True
            _has_alembic = False

        if _inspection_failed:
            pass
        elif _has_alembic:
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
# column may not exist until `flask db upgrade` has run. There is no built-in
# default: an address in code would let anyone who registers (or renames their
# account to) it become admin. auth.py refuses switching to a listed address.
def _promote_admin_emails():
    """Promote verified users whose address is listed in ADMIN_EMAILS. Only a
    verified mailbox qualifies: a listed address registered by someone else
    must not become admin."""
    emails = admin_emails()
    if not emails:
        return
    with app.app_context():
        try:
            for _user in User.query.filter(User.email.in_(emails)).all():
                if not _user.is_admin and _user.email_verified_at is not None:
                    _user.is_admin = True
                    logger.info(f"ADMIN_EMAILS: promoted {_user.email} to admin")
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"ADMIN_EMAILS promotion skipped: {e}")


if os.environ.get("SKIP_DB_BOOTSTRAP", "").lower() not in (
    "1",
    "true",
    "yes",
):
    _promote_admin_emails()

# Seed the Plan table from PLAN_CONFIG on first boot so admins have editable
# Free/Pro/Business/Unlimited rows. Idempotent (no-op once any plan exists) and
# defensive: on a fresh DB before `flask db upgrade` the table may not exist yet
# -- the plan helpers fall back to PLAN_CONFIG until it does. Wrapped in
# SKIP_DB_BOOTSTRAP like the blocks above.
if os.environ.get("SKIP_DB_BOOTSTRAP", "").lower() not in ("1", "true", "yes"):
    with app.app_context():
        try:
            from services.plans import seed_plans_if_empty
            seed_plans_if_empty()
        except Exception as e:
            db.session.rollback()
            logger.warning(f"Plan seeding skipped: {e}")


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

                if file_ext == ".glb":
                    # meshopt/draco GLBs read as empty geometry in trimesh
                    from converters.glb_optimizer import readable_glb

                    with readable_glb(file_path) as readable_path:
                        mesh = trimesh.load(readable_path)
                else:
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


@app.errorhandler(413)
def too_large(e):
    max_mb = app.config['MAX_CONTENT_LENGTH'] // (1024 * 1024)
    return jsonify(
        {"error": f"File is too large. Maximum file size is {max_mb}MB."}
    ), 413


def _error_wants_json(non_browser_is_json=False):
    """JSON for API/XHR callers, HTML pages for browser navigation (same idea
    as the CSRF handler). With non_browser_is_json, anything that doesn't ask
    for text/html (curl, bare fetch) also gets JSON."""
    if request.path.startswith("/api/") or request.is_json:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    if request.accept_mimetypes.best_match(["text/html", "application/json"]) == "application/json":
        return True
    return non_browser_is_json and "text/html" not in request.headers.get("Accept", "")


_ERROR_PAGES = {
    403: ("Access denied",
          "You don't have access to this page. If it is a private model, sign in "
          "or ask the owner for a share link."),
    404: ("Page not found",
          "We couldn't find what you were looking for. The link may be broken, "
          "or the page or model may have been removed."),
    500: ("Something went wrong",
          "We hit an unexpected error. Please try again in a moment."),
}


def _render_error(code, json_message, non_browser_is_json=False):
    if _error_wants_json(non_browser_is_json):
        return jsonify({"success": False, "error": json_message}), code
    title, message = _ERROR_PAGES[code]
    try:
        return render_template(
            "error.html", error_code=code, error_title=title, error_message=message
        ), code
    except Exception:
        # Never let the error page itself fail (e.g. DB down while the base
        # template's context processors run); fall back to static markup.
        logger.exception("Error page render failed")
        return (
            f"<!doctype html><title>{title}</title><h1>{title}</h1><p>{message}</p>"
            '<p><a href="/">Home</a></p>',
            code,
        )


@app.errorhandler(404)
def not_found_error(e):
    return _render_error(404, "Not found")


@app.errorhandler(403)
def forbidden_error(e):
    return _render_error(403, "Forbidden")


@app.errorhandler(500)
def server_error(e):
    # Generic body only: never echo exception details to the client.
    try:
        db.session.rollback()
    except Exception:
        pass
    return _render_error(500, "Server error. Please try again later.", non_browser_is_json=True)


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
             "/robots.txt", "/sitemap.xml", "/healthz")
        )
        is_admin = current_user.is_authenticated and getattr(
            current_user, "is_admin", False
        )
        if not exempt and not is_admin:
            response = make_response(render_template("maintenance.html"), 503)
            response.headers["Retry-After"] = "600"
            return response
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
    from urllib.parse import urlparse
    return {"SITE_URL": SITE_URL, "SITE_HOST": urlparse(SITE_URL).netloc,
            "GOOGLE_SITE_VERIFICATION": GOOGLE_SITE_VERIFICATION}


# ========== MODEL VERSION MANAGEMENT ==========




# ===================================================================
# HOTSPOT CRUD API
# ===================================================================



if __name__ == "__main__":
    if init_app_dependencies():
        app.logger.info("Dependencies initialized successfully")
        # Railway/Heroku için PORT environment variable
        port = int(os.environ.get("PORT", 5000))
        # threaded=True: a long-lived SSE connection (/api/upload-jobs/<id>/stream)
        # would otherwise tie up this dev server's single worker for its whole
        # duration, blocking every other request until it closes.
        app.run(host="0.0.0.0", port=port, debug=app.config.get("DEBUG", False), threaded=True)  # nosec B104 - dev entrypoint only; must listen on all interfaces inside the container (prod runs gunicorn)
    else:
        app.logger.error("Failed to initialize dependencies")
