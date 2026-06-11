"""
Temel model dönüştürücü sınıfı.
Tüm format-spesifik dönüştürücüler bu sınıftan türetilecektir.
"""
from datetime import datetime
import os
import logging
from typing import Optional, Dict


def srgb_to_linear_channel(c: float) -> float:
    """Convert one sRGB channel (0-1) to linear (0-1).

    Color pickers produce sRGB values, but glTF baseColorFactor and COLOR_0
    vertex attributes are linear. Writing sRGB values straight into those slots
    makes colors render washed-out/wrong, most visibly in iOS Quick Look (USDZ).
    """
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def hex_to_linear_rgb(hex_color: str) -> tuple:
    """Parse '#RRGGBB' (sRGB) into a (r, g, b) tuple of linear floats 0-1."""
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        raise ValueError(f"Invalid hex color: {hex_color}")
    return tuple(
        srgb_to_linear_channel(int(h[i : i + 2], 16) / 255.0) for i in (0, 2, 4)
    )


class BaseConverter:
    def __init__(self):
        self.model_id: str = None
        self.original_filename: str = None
        self.status: str = "INITIALIZED"
        self.errors: list = []
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.logger = logging.getLogger(__name__)
        self.max_dimension: float = 0  # No scaling by default - only scale if user explicitly sets it

    def validate(self, file_path: str) -> bool:
        """
        Dosya formatı ve güvenlik kontrolleri
        Args:
            file_path: Kontrol edilecek dosyanın yolu
        Returns:
            bool: Dosya geçerli mi
        """
        if not os.path.exists(file_path):
            self.handle_error(f"Dosya bulunamadı: {file_path}")
            return False
            
        if not os.path.isfile(file_path):
            self.handle_error(f"Geçersiz dosya: {file_path}")
            return False
            
        return True

    def prepare(self, file_path: str) -> bool:
        """
        Dönüştürme öncesi hazırlıklar
        Args:
            file_path: Hazırlanacak dosyanın yolu
        Returns:
            bool: Hazırlık başarılı mı
        """
        self.start_time = datetime.now()
        self.original_filename = os.path.basename(file_path)
        self.status = "PREPARING"
        return True

    def convert(self, input_path: str, output_path: str) -> bool:
        """
        Asıl dönüştürme işlemi - alt sınıflar tarafından implement edilecek
        Args:
            input_path: Dönüştürülecek dosyanın yolu
            output_path: Çıktı dosyasının yolu
        Returns:
            bool: Dönüştürme başarılı mı
        """
        raise NotImplementedError("Bu metod alt sınıflar tarafından implement edilmelidir")

    def cleanup(self) -> None:
        """Geçici dosyaları temizleme"""
        self.end_time = datetime.now()
        self.status = "COMPLETED"

    def log_operation(self, message: str, level: str = "INFO") -> None:
        """
        İşlem logları
        Args:
            message: Log mesajı
            level: Log seviyesi
        """
        log_levels = {
            "DEBUG": logging.DEBUG,
            "INFO": logging.INFO,
            "WARNING": logging.WARNING,
            "ERROR": logging.ERROR,
            "CRITICAL": logging.CRITICAL
        }
        self.logger.log(log_levels.get(level, logging.INFO), message)

    def update_status(self, status: str) -> None:
        """
        Durum güncelleme
        Args:
            status: Yeni durum
        """
        self.status = status
        self.log_operation(f"Status updated: {status}")

    def handle_error(self, error: str) -> None:
        """
        Hata yönetimi
        Args:
            error: Hata mesajı
        """
        self.errors.append(error)
        self.status = "ERROR"
        self.log_operation(error, "ERROR")

    def optimize_output(self, output_path: str) -> bool:
        """
        Çıktı optimizasyonu
        Args:
            output_path: Optimize edilecek dosyanın yolu
        Returns:
            bool: Optimizasyon başarılı mı
        """
        return True

    def get_conversion_time(self) -> float:
        """
        Dönüştürme süresini hesapla
        Returns:
            float: Dönüştürme süresi (saniye)
        """
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return 0.0

    def get_status(self) -> Dict:
        """
        Mevcut durumu döndür
        Returns:
            dict: Durum bilgileri
        """
        return {
            "model_id": self.model_id,
            "original_filename": self.original_filename,
            "status": self.status,
            "errors": self.errors,
            "conversion_time": self.get_conversion_time(),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None
        }

    def set_max_dimension(self, max_dimension_meters: float) -> None:
        """
        Set maximum dimension in meters
        Args:
            max_dimension_meters: Maximum dimension in meters (already converted from cm)
        """
        self.max_dimension = max_dimension_meters
        self.log_operation(f"Maximum dimension set to {max_dimension_meters:.4f} m ({max_dimension_meters * 100:.2f} cm)")

    @staticmethod
    def auto_detect_unit(max_extent: float):
        """
        Guess the source unit of a unitless mesh (OBJ/STL) from its raw extent.

        Picks the unit that lands the object in a plausible real-world size
        (5 cm - 5 m). Preference order m > cm > mm, so a model that is
        plausible as metres stays untouched. Falls back to the nearest
        sensible interpretation when nothing fits.

        Returns:
            (unit, scale_to_meters): e.g. ("cm", 0.01)
        """
        candidates = (("m", 1.0), ("cm", 0.01), ("mm", 0.001))
        if max_extent and max_extent > 0:
            for unit, k in candidates:
                if 0.05 <= max_extent * k <= 5.0:
                    return unit, k
            # Nothing plausible: huge numbers are almost certainly mm,
            # tiny ones are best left as metres.
            if max_extent * 0.001 > 5.0:
                return "mm", 0.001
        return "m", 1.0

    def calculate_scale_factor(self, dimensions: Dict[str, float]) -> float:
        """
        Calculate scale factor based on maximum dimension.
        ALWAYS scales to target dimension (both up and down) for AR standardization.
        Args:
            dimensions: Dictionary containing x, y, z dimensions in meters
        Returns:
            float: Scale factor to apply to the model (always applied if max_dimension is set)
        """
        # Find the largest dimension
        max_current_dimension = max(dimensions.values())
        
        if max_current_dimension <= 0:
            self.log_operation("Warning: Model has zero or negative dimensions", "WARNING")
            return 1.0
        
        # If no max_dimension is set, don't scale
        if self.max_dimension <= 0:
            return 1.0
            
        # ALWAYS calculate scale factor (both scale up and scale down)
        scale_factor = self.max_dimension / max_current_dimension
        
        if scale_factor > 1.0:
            self.log_operation(f"Scaling UP: {scale_factor:.4f}x (Current max: {max_current_dimension:.4f}m -> Target: {self.max_dimension:.4f}m)")
        elif scale_factor < 1.0:
            self.log_operation(f"Scaling DOWN: {scale_factor:.4f}x (Current max: {max_current_dimension:.4f}m -> Target: {self.max_dimension:.4f}m)")
        else:
            self.log_operation(f"No scaling needed (already at target: {self.max_dimension:.4f}m)")
        
        return scale_factor
