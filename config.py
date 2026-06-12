import os
import platform

# Load a local .env if present (no-op in production where real env vars are set).
# Railway/Heroku env vars take precedence — load_dotenv does not override them.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Base directory - projenin kök dizini
BASE_DIR = os.getenv('WEB_AR_BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

# Railway Volume: when a Volume is mounted, Railway injects RAILWAY_VOLUME_MOUNT_PATH
# automatically — no manual env var needed. Falls back to BASE_DIR locally.
_STORAGE_ROOT = (
    os.environ.get('STORAGE_ROOT')
    or os.environ.get('RAILWAY_VOLUME_MOUNT_PATH')
    or BASE_DIR
)

# Alt dizinler — on Railway all data dirs live under the persistent volume root.
UPLOAD_FOLDER = os.getenv('WEB_AR_UPLOAD_DIR', os.path.join(_STORAGE_ROOT, 'uploads'))
CONVERTED_FOLDER = os.getenv('WEB_AR_CONVERTED_DIR', os.path.join(_STORAGE_ROOT, 'converted'))
TEMP_FOLDER = os.getenv('WEB_AR_TEMP_DIR', os.path.join(_STORAGE_ROOT, 'temp'))
QR_FOLDER = os.getenv('WEB_AR_QR_DIR', os.path.join(_STORAGE_ROOT, 'qr_codes'))
TOOLS_DIR = os.getenv('WEB_AR_TOOLS_DIR', os.path.join(BASE_DIR, 'tools'))  # tools are in the image, not the volume

# Dönüşüm araçları - Platform-specific
if platform.system() == 'Windows':
    FBX2GLTF_PATH = os.path.join(TOOLS_DIR, 'FBX2glTF.exe')
else:
    # Linux/Mac için (Railway, Heroku, etc.)
    FBX2GLTF_PATH = os.path.join(TOOLS_DIR, 'FBX2glTF')

# Flask Configuration
SECRET_KEY = os.getenv('SECRET_KEY') or os.getenv('WEB_AR_SECRET_KEY', 'dev-secret-key-change-in-production')
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
FLASK_ENV = os.environ.get('FLASK_ENV', 'development')

# Database - Railway PostgreSQL veya local SQLite
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Railway PostgreSQL
    # Fix: Railway uses postgres:// but SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
else:
    # Local SQLite (Flask-SQLAlchemy resolves the relative path to instance/)
    SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'

SQLALCHEMY_TRACK_MODIFICATIONS = False

# Production optimizations
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}

# Dosya limitleri ve izinler
MAX_CONTENT_LENGTH = int(os.getenv('WEB_AR_MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB default
ALLOWED_EXTENSIONS = {'obj', 'stl', 'fbx', 'glb', 'gltf'}

# AI 3D generation (Meshy) — server-side only, never expose the key to clients.
MESHY_API_KEY = os.getenv('MESHY_API_KEY', '')
MESHY_API_BASE = os.getenv('MESHY_API_BASE', 'https://api.meshy.ai/openapi')
MESHY_AI_MODEL = os.getenv('MESHY_AI_MODEL', 'meshy-5')
# Image generation model for the optional pre-processing step (text-to-image /
# image-to-image before image-to-3D).
MESHY_IMAGE_MODEL = os.getenv('MESHY_IMAGE_MODEL', 'nano-banana-pro')
# Per-user daily generation quota (each generation costs Meshy credits = money).
AI_GEN_DAILY_LIMIT = int(os.getenv('AI_GEN_DAILY_LIMIT', 10))

# Klasörleri oluştur
def create_directories():
    """Create necessary directories if they don't exist."""
    directories = [UPLOAD_FOLDER, CONVERTED_FOLDER, TEMP_FOLDER, QR_FOLDER, TOOLS_DIR]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")
