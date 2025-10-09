"""
Format doğrulama için yardımcı fonksiyonlar.
"""
import os
from typing import Set

def is_valid_extension(filename: str, allowed_extensions: Set[str]) -> bool:
    """
    Dosya uzantısının geçerli olup olmadığını kontrol et
    Args:
        filename: Dosya adı
        allowed_extensions: İzin verilen uzantılar kümesi
    Returns:
        bool: Uzantı geçerli mi
    """
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def is_safe_filename(filename: str) -> bool:
    """
    Dosya adının güvenli olup olmadığını kontrol et
    Args:
        filename: Kontrol edilecek dosya adı
    Returns:
        bool: Dosya adı güvenli mi
    """
    return os.path.basename(filename) == filename

def get_safe_filename(filename: str) -> str:
    """
    Güvenli dosya adı oluştur
    Args:
        filename: Orijinal dosya adı
    Returns:
        str: Güvenli dosya adı
    """
    filename = os.path.basename(filename)
    return ''.join(c for c in filename if c.isalnum() or c in '._- ')
