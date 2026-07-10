import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from werkzeug.utils import secure_filename


class UploadStagingError(ValueError):
    pass


class UploadStagingService:
    """Safely stage model uploads and resolve ZIP companions."""

    MODEL_EXTENSIONS = {".obj", ".stl", ".fbx", ".glb", ".gltf"}
    TEXTURE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tga", ".bmp", ".webp"}

    def __init__(self, temp_root, *, max_uncompressed_bytes, max_archive_entries=500):
        self.temp_root = Path(temp_root).resolve()
        self.max_uncompressed_bytes = max_uncompressed_bytes
        self.max_archive_entries = max_archive_entries

    def _job_dir(self, job_id):
        target = (self.temp_root / str(job_id)).resolve()
        if self.temp_root not in target.parents:
            raise UploadStagingError("Invalid staging path")
        target.mkdir(parents=True, exist_ok=False)
        return target

    def stage(self, job_id, model_file, *, mtl_file=None, textures=()):
        job_dir = self._job_dir(job_id)
        try:
            client_name = model_file.filename or "model"
            safe_name = secure_filename(client_name)
            if not safe_name:
                raise UploadStagingError("Invalid filename")
            uploaded = job_dir / safe_name
            model_file.save(uploaded)

            if uploaded.suffix.lower() == ".zip":
                primary, mtl_path, texture_paths = self._extract_archive(uploaded, job_dir)
                uploaded.unlink(missing_ok=True)
            else:
                if uploaded.suffix.lower() not in self.MODEL_EXTENSIONS:
                    raise UploadStagingError("Unsupported model format")
                primary = uploaded
                mtl_path = self._save_companion(job_dir, mtl_file) if mtl_file else None
                texture_paths = [self._save_companion(job_dir, item) for item in textures if item and item.filename]

            return {
                "temp_dir": str(job_dir),
                "temp_file_path": str(primary),
                "original_filename": primary.name,
                "client_filename": client_name,
                "file_extension": primary.suffix.lower(),
                "mtl_path": str(mtl_path) if mtl_path else None,
                "texture_paths": [str(path) for path in texture_paths],
            }
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise

    @staticmethod
    def _save_companion(job_dir, file_storage):
        name = secure_filename(file_storage.filename or "")
        if not name:
            raise UploadStagingError("Invalid companion filename")
        target = job_dir / name
        file_storage.save(target)
        return target

    def _extract_archive(self, archive_path, job_dir):
        extract_root = job_dir / "archive"
        extract_root.mkdir()
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile as exc:
            raise UploadStagingError("Invalid ZIP archive") from exc
        with archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) > self.max_archive_entries:
                raise UploadStagingError("ZIP archive contains too many files")
            total = sum(item.file_size for item in members)
            if total > self.max_uncompressed_bytes:
                raise UploadStagingError("ZIP uncompressed size exceeds upload limit")
            for item in members:
                relative = PurePosixPath(item.filename)
                if relative.is_absolute() or ".." in relative.parts:
                    raise UploadStagingError("Unsafe path in ZIP archive")
                target = (extract_root / Path(*relative.parts)).resolve()
                if extract_root.resolve() not in target.parents:
                    raise UploadStagingError("Unsafe path in ZIP archive")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)

        models = [p for p in extract_root.rglob("*") if p.is_file() and p.suffix.lower() in self.MODEL_EXTENSIONS]
        if len(models) != 1:
            raise UploadStagingError("ZIP archive must contain exactly one supported 3D model")
        primary = models[0]
        mtl_files = list(primary.parent.glob("*.mtl")) if primary.suffix.lower() == ".obj" else []
        textures = [p for p in extract_root.rglob("*") if p.is_file() and p.suffix.lower() in self.TEXTURE_EXTENSIONS]
        return primary, (mtl_files[0] if mtl_files else None), textures
