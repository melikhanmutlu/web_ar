"""
Dosya işlemleri için yardımcı fonksiyonlar.
"""
import os
import shutil
from typing import Optional

def ensure_directory(directory: str) -> None:
    """
    Klasörün var olduğundan emin ol, yoksa oluştur
    Args:
        directory: Oluşturulacak klasör yolu
    """
    os.makedirs(directory, exist_ok=True)

def safe_delete_file(file_path: str) -> bool:
    """
    Dosyayı güvenli bir şekilde sil
    Args:
        file_path: Silinecek dosyanın yolu
    Returns:
        bool: Silme işlemi başarılı mı
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
        return True
    except Exception:
        return False

def get_file_size(file_path: str) -> Optional[int]:
    """
    Dosya boyutunu döndür
    Args:
        file_path: Dosya yolu
    Returns:
        Optional[int]: Dosya boyutu (bytes)
    """
    try:
        return os.path.getsize(file_path)
    except Exception:
        return None

def copy_file(src: str, dst: str) -> bool:
    """
    Dosyayı kopyala
    Args:
        src: Kaynak dosya yolu
        dst: Hedef dosya yolu
    Returns:
        bool: Kopyalama başarılı mı
    """
    try:
        shutil.copy2(src, dst)
        return True
    except Exception:
        return False
