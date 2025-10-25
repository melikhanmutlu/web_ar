import os
import platform

# Base directory - projenin kök dizini
BASE_DIR = os.getenv('WEB_AR_BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

# Alt dizinler
UPLOAD_FOLDER = os.getenv('WEB_AR_UPLOAD_DIR', os.path.join(BASE_DIR, 'uploads'))
CONVERTED_FOLDER = os.getenv('WEB_AR_CONVERTED_DIR', os.path.join(BASE_DIR, 'converted'))
TEMP_FOLDER = os.getenv('WEB_AR_TEMP_DIR', os.path.join(BASE_DIR, 'temp'))
QR_FOLDER = os.getenv('WEB_AR_QR_DIR', os.path.join(BASE_DIR, 'qr_codes'))
TOOLS_DIR = os.getenv('WEB_AR_TOOLS_DIR', os.path.join(BASE_DIR, 'tools'))

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
    # Local SQLite
    SQLALCHEMY_DATABASE_URI = 'sqlite:///instance/app.db'

SQLALCHEMY_TRACK_MODIFICATIONS = False

# Production optimizations
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}

# Dosya limitleri ve izinler
MAX_CONTENT_LENGTH = int(os.getenv('WEB_AR_MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB default
ALLOWED_EXTENSIONS = {'obj', 'stl', 'fbx'}

# Klasörleri oluştur
def create_directories():
    """Create necessary directories if they don't exist."""
    directories = [UPLOAD_FOLDER, CONVERTED_FOLDER, TEMP_FOLDER, QR_FOLDER, TOOLS_DIR]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")
