import os
import shutil
import tempfile
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

    def _safe_extract(self, archive_path, extract_root):
        """Extract the ZIP into extract_root with the usual entry-count, size
        and path-traversal guards. Raises UploadStagingError on any problem."""
        extract_root.mkdir(parents=True, exist_ok=True)
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

    def _extract_archive(self, archive_path, job_dir):
        extract_root = job_dir / "archive"
        self._safe_extract(archive_path, extract_root)

        models = [p for p in extract_root.rglob("*") if p.is_file() and p.suffix.lower() in self.MODEL_EXTENSIONS]
        if len(models) != 1:
            raise UploadStagingError("ZIP archive must contain exactly one supported 3D model")
        primary = models[0]
        mtl_files = list(primary.parent.glob("*.mtl")) if primary.suffix.lower() == ".obj" else []
        textures = [p for p in extract_root.rglob("*") if p.is_file() and p.suffix.lower() in self.TEXTURE_EXTENSIONS]
        return primary, (mtl_files[0] if mtl_files else None), textures

    def stage_archive_models(self, archive_file, make_job_id):
        """Extract a ZIP and stage EVERY supported model it contains as its own
        independent job (each with a fresh job dir), so one ZIP of N models
        fans out into N conversion jobs.

        Companions are grouped per model by the model's own folder: an OBJ
        picks up a sibling .mtl, and image textures in the same folder ride
        along (unused ones are simply ignored downstream). Returns a list of
        (job_id, staged_payload); the payload shape matches stage()."""
        scratch = Path(tempfile.mkdtemp(dir=self.temp_root))
        try:
            zip_path = scratch / "upload.zip"
            archive_file.save(zip_path)
            extract_root = scratch / "extract"
            self._safe_extract(zip_path, extract_root)

            models = sorted(
                p for p in extract_root.rglob("*")
                if p.is_file() and p.suffix.lower() in self.MODEL_EXTENSIONS
            )
            if not models:
                raise UploadStagingError("ZIP archive contains no supported 3D model")

            staged = []
            for model_path in models:
                job_id = make_job_id()
                job_dir = self._job_dir(job_id)
                dest_model = job_dir / (secure_filename(model_path.name) or "model")
                shutil.copyfile(model_path, dest_model)

                mtl_dest = None
                if model_path.suffix.lower() == ".obj":
                    siblings = list(model_path.parent.glob("*.mtl"))
                    if siblings:
                        mtl_dest = job_dir / (secure_filename(siblings[0].name) or "model.mtl")
                        shutil.copyfile(siblings[0], mtl_dest)

                texture_dests = []
                for sibling in sorted(model_path.parent.iterdir()):
                    if sibling.is_file() and sibling.suffix.lower() in self.TEXTURE_EXTENSIONS:
                        tex_dest = job_dir / (secure_filename(sibling.name) or sibling.name)
                        shutil.copyfile(sibling, tex_dest)
                        texture_dests.append(tex_dest)

                staged.append((job_id, {
                    "temp_dir": str(job_dir),
                    "temp_file_path": str(dest_model),
                    "original_filename": dest_model.name,
                    "client_filename": model_path.name,
                    "file_extension": dest_model.suffix.lower(),
                    "mtl_path": str(mtl_dest) if mtl_dest else None,
                    "texture_paths": [str(p) for p in texture_dests],
                }))
            return staged
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
