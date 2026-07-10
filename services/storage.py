import os
import shutil
from pathlib import Path


class StorageService:
    """Resolve and mutate files without allowing paths to escape storage roots."""

    def __init__(self, converted_root, upload_root=None, temp_root=None):
        self.converted_root = Path(converted_root).resolve()
        self.upload_root = Path(upload_root).resolve() if upload_root else None
        self.temp_root = Path(temp_root).resolve() if temp_root else None

    @staticmethod
    def _inside(root: Path, *parts: str) -> Path:
        candidate = root.joinpath(*map(str, parts)).resolve()
        if candidate != root and root not in candidate.parents:
            raise ValueError("Path escapes configured storage root")
        return candidate

    def converted_path(self, model_id, filename="model.glb"):
        return self._inside(self.converted_root, model_id, filename)

    def remove_model(self, model_id):
        target = self._inside(self.converted_root, model_id)
        if target.is_dir():
            shutil.rmtree(target)

        if self.upload_root:
            upload = self._inside(self.upload_root, model_id)
            if upload.is_dir():
                shutil.rmtree(upload)

    def ensure_model_dir(self, model_id):
        target = self._inside(self.converted_root, model_id)
        target.mkdir(parents=True, exist_ok=True)
        return target
