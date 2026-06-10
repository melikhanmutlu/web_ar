"""Application configuration.

All values come from environment variables so the same code runs locally
(SQLite, .env file) and on Railway (PostgreSQL, injected env vars). The
variable names are kept compatible with the previous deployment so existing
Railway services keep working without reconfiguration:

    SECRET_KEY, DATABASE_URL, PORT, JOB_QUEUE, SKIP_DB_BOOTSTRAP,
    WEB_AR_BASE_DIR, WEB_AR_UPLOAD_DIR, WEB_AR_CONVERTED_DIR,
    WEB_AR_QR_DIR, WEB_AR_TOOLS_DIR, WEB_AR_MAX_CONTENT_LENGTH
"""

import os
from pathlib import Path

try:  # Local convenience only; real env vars always win.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


BASE_DIR = Path(os.getenv("WEB_AR_BASE_DIR", Path(__file__).resolve().parent.parent))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    DEBUG = _env_bool("DEBUG")

    # Railway provides postgres:// URLs; SQLAlchemy requires postgresql://.
    _db_url = os.getenv("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url or "sqlite:///app.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 3600}

    MAX_CONTENT_LENGTH = int(os.getenv("WEB_AR_MAX_CONTENT_LENGTH", 100 * 1024 * 1024))
    ALLOWED_EXTENSIONS = {"obj", "stl", "fbx", "glb", "gltf"}

    # Storage. Point these at a Railway volume to persist files across deploys.
    UPLOAD_DIR = Path(os.getenv("WEB_AR_UPLOAD_DIR", BASE_DIR / "uploads"))
    CONVERTED_DIR = Path(os.getenv("WEB_AR_CONVERTED_DIR", BASE_DIR / "converted"))
    QR_DIR = Path(os.getenv("WEB_AR_QR_DIR", BASE_DIR / "qr_codes"))
    TOOLS_DIR = Path(os.getenv("WEB_AR_TOOLS_DIR", BASE_DIR / "tools"))

    # When true, uploads only enqueue a ConversionJob row and worker.py picks
    # it up. When false the job row is processed inline in the request; the
    # polling contract toward the frontend is identical either way.
    JOB_QUEUE = _env_bool("JOB_QUEUE")

    # iOS Quick Look needs USDZ; export is best-effort via Blender when present.
    USDZ_EXPORT = _env_bool("USDZ_EXPORT", "true")

    # AI 3D generation (Meshy) — server-side only, the key never reaches
    # clients. Generation costs credits, hence the per-user daily quota.
    MESHY_API_KEY = os.getenv("MESHY_API_KEY", "")
    MESHY_API_BASE = os.getenv("MESHY_API_BASE", "https://api.meshy.ai/openapi")
    MESHY_AI_MODEL = os.getenv("MESHY_AI_MODEL", "meshy-5")
    AI_GEN_DAILY_LIMIT = int(os.getenv("AI_GEN_DAILY_LIMIT", 10))

    # gunicorn/flask db upgrade handles schema in production; local boot can
    # bootstrap the schema itself unless this is set.
    SKIP_DB_BOOTSTRAP = _env_bool("SKIP_DB_BOOTSTRAP")

    WTF_CSRF_TIME_LIMIT = None  # tokens valid for the whole session


def ensure_directories(config: type[Config] = Config) -> None:
    for directory in (config.UPLOAD_DIR, config.CONVERTED_DIR, config.QR_DIR):
        Path(directory).mkdir(parents=True, exist_ok=True)
