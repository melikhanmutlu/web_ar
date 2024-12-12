import os

# Base directory - projenin kök dizini
BASE_DIR = os.getenv('WEB_AR_BASE_DIR', os.path.dirname(os.path.abspath(__file__)))

# Alt dizinler
UPLOAD_FOLDER = os.getenv('WEB_AR_UPLOAD_DIR', os.path.join(BASE_DIR, 'uploads'))
CONVERTED_FOLDER = os.getenv('WEB_AR_CONVERTED_DIR', os.path.join(BASE_DIR, 'converted'))
TEMP_FOLDER = os.getenv('WEB_AR_TEMP_DIR', os.path.join(BASE_DIR, 'temp'))
QR_FOLDER = os.getenv('WEB_AR_QR_DIR', os.path.join(BASE_DIR, 'qr_codes'))
TOOLS_DIR = os.getenv('WEB_AR_TOOLS_DIR', os.path.join(BASE_DIR, 'tools'))

# Dönüşüm araçları
FBX2GLTF_PATH = os.path.join(TOOLS_DIR, 'FBX2glTF.exe')

# Secret key for session management and CSRF protection
SECRET_KEY = os.getenv('WEB_AR_SECRET_KEY', 'your-secret-key-here')

# Dosya limitleri ve izinler
MAX_CONTENT_LENGTH = int(os.getenv('WEB_AR_MAX_CONTENT_LENGTH', 100 * 1024 * 1024))  # 100MB default
ALLOWED_EXTENSIONS = {'obj', 'stl', 'fbx'}

# Maximum model size in meters (50 cm = 0.5 meters)
MAX_MODEL_SIZE = 0.5

# Klasörleri oluştur
def create_directories():
    """Create necessary directories if they don't exist."""
    directories = [UPLOAD_FOLDER, CONVERTED_FOLDER, TEMP_FOLDER, QR_FOLDER, TOOLS_DIR]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        print(f"Created directory: {directory}")
