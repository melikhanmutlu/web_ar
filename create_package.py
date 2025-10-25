"""
ARVision - Package Creator
Bu script projeyi paylaşmak için ZIP dosyası oluşturur.
"""

import os
import shutil
import zipfile
from pathlib import Path

# Gönderilecek dosya ve klasörler
INCLUDE = [
    'app.py',
    'models.py',
    'auth.py',
    'config.py',
    'requirements.txt',
    'migrate_db.py',
    'start.bat',
    'DEPLOYMENT.md',
    'README.md',
    'templates',
    'static',
    'converters',
]

# Gönderilmeyecekler
EXCLUDE = [
    'venv',
    '__pycache__',
    '.git',
    '.gitignore',
    'uploads',
    'converted',
    'temp',
    'instance',
    'build',
    'dist',
    '*.pyc',
    '*.spec',
    '*.log',
]

def create_package():
    """Projeyi ZIP dosyasına paketler"""
    
    print("=" * 60)
    print("ARVision - Package Creator")
    print("=" * 60)
    
    # Çıktı dosyası
    output_file = '../ARVision_Package.zip'
    
    print(f"\n📦 Paket oluşturuluyor: {output_file}")
    print("\n✅ Dahil edilen dosyalar:")
    
    with zipfile.ZipFile(output_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for item in INCLUDE:
            if os.path.exists(item):
                if os.path.isfile(item):
                    zipf.write(item, f'ARVision/{item}')
                    print(f"   - {item}")
                elif os.path.isdir(item):
                    for root, dirs, files in os.walk(item):
                        # __pycache__ klasörlerini atla
                        dirs[:] = [d for d in dirs if d != '__pycache__']
                        
                        for file in files:
                            # .pyc dosyalarını atla
                            if not file.endswith('.pyc'):
                                file_path = os.path.join(root, file)
                                arc_path = os.path.join('ARVision', file_path)
                                zipf.write(file_path, arc_path)
                    print(f"   - {item}/ (klasör)")
            else:
                print(f"   ⚠️  {item} bulunamadı (atlandı)")
    
    # Dosya boyutu
    size_mb = os.path.getsize(output_file) / (1024 * 1024)
    
    print("\n" + "=" * 60)
    print(f"✅ Paket başarıyla oluşturuldu!")
    print(f"📁 Dosya: {os.path.abspath(output_file)}")
    print(f"📊 Boyut: {size_mb:.2f} MB")
    print("=" * 60)
    print("\n📧 Bu ZIP dosyasını gönderebilirsiniz!")
    print("\n📋 Alıcı yapması gerekenler:")
    print("   1. ZIP'i aç")
    print("   2. Python 3.8+ kur (python.org)")
    print("   3. Terminal'de: pip install -r requirements.txt")
    print("   4. start.bat'a çift tıkla (veya: python app.py)")
    print("   5. Tarayıcıda: http://localhost:5000")
    print("\n" + "=" * 60)

if __name__ == '__main__':
    try:
        create_package()
    except Exception as e:
        print(f"\n❌ Hata: {e}")
        input("\nDevam etmek için Enter'a basın...")
