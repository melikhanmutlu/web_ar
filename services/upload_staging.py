import json
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

from werkzeug.utils import secure_filename


class UploadStagingError(ValueError):
    pass


class UploadStagingService:
    """Safely stage model uploads and resolve ZIP companions."""

    MODEL_EXTENSIONS = {".obj", ".stl", ".fbx", ".glb", ".gltf", ".step", ".stp"}
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

            warnings = []
            if uploaded.suffix.lower() == ".zip":
                primary, mtl_path, texture_paths, warnings = self._extract_archive(uploaded, job_dir)
                uploaded.unlink(missing_ok=True)
            else:
                if uploaded.suffix.lower() not in self.MODEL_EXTENSIONS:
                    raise UploadStagingError("Unsupported model format")
                primary = uploaded
                mtl_path = self._save_companion(job_dir, mtl_file) if mtl_file else None
                companions = [
                    (item.filename, self._save_companion(job_dir, item))
                    for item in textures if item and item.filename
                ]
                mtl_path, texture_paths, warnings = self._stage_loose_companions(
                    primary, job_dir, mtl_path, companions
                )

            return {
                "temp_dir": str(job_dir),
                "temp_file_path": str(primary),
                "original_filename": primary.name,
                "client_filename": client_name,
                "file_extension": primary.suffix.lower(),
                "mtl_path": str(mtl_path) if mtl_path else None,
                "texture_paths": [str(path) for path in texture_paths],
                "staging_warnings": warnings,
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

    # ---- companion resolution (OBJ/MTL textures, glTF buffers/images) ------

    _MTL_TEXTURE_KEYS = {"bump", "disp", "decal", "refl"}
    # MTL texture options and how many arguments each consumes.
    _MTL_OPTION_ARGS = {
        "-blendu": 1, "-blendv": 1, "-cc": 1, "-clamp": 1, "-imfchan": 1,
        "-mm": 2, "-o": 3, "-s": 3, "-t": 3, "-texres": 1, "-bm": 1, "-type": 1,
    }

    @staticmethod
    def _is_unsafe_reference(ref):
        """Absolute, drive/URL-scheme, home-relative or '..' references are
        never honoured."""
        token = (ref or "").strip().strip('"').replace("\\", "/")
        if not token or token.startswith(("/", "~")):
            return True
        if re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", token):
            return True
        return any(part == ".." for part in token.split("/"))

    def _resolver(self, extract_root, base_dir):
        """Return resolve(ref) -> Path|None looking for `ref` inside the
        extracted archive only (relative to the model, then the archive root,
        then by case-insensitive file name)."""
        root = Path(extract_root).resolve()
        index = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                index.setdefault(path.name.lower(), []).append(path)

        def resolve(ref):
            token = (ref or "").strip().strip('"').replace("\\", "/")
            if self._is_unsafe_reference(token):
                return None
            relative = PurePosixPath(token)
            for base in (Path(base_dir).resolve(), root):
                candidate = (base / Path(*relative.parts)).resolve()
                if candidate.is_file() and root in candidate.parents:
                    return candidate
            matches = index.get(relative.name.lower(), [])
            return matches[0] if matches else None

        return resolve

    @staticmethod
    def _unique_name(name, taken):
        safe = secure_filename(name) or "file"
        stem, ext = os.path.splitext(safe)
        candidate, counter = safe, 2
        while candidate.lower() in taken:
            candidate = f"{stem}_{counter}{ext}"
            counter += 1
        taken.add(candidate.lower())
        return candidate

    def _copy_companion(self, source, job_dir, taken, copied):
        """Copy `source` into job_dir under a unique safe name (once per
        source file) and return that name."""
        source = Path(source)
        if source in copied:
            return copied[source]
        if source.parent == job_dir:
            copied[source] = source.name
            return source.name
        name = self._unique_name(source.name, taken)
        shutil.copyfile(source, job_dir / name)
        copied[source] = name
        return name

    @classmethod
    def _parse_mtl_texture_line(cls, line):
        """Split an MTL texture directive into (head, filename) where head is
        everything before the file name (key + options); None if the line is
        not a texture directive. File names may contain spaces."""
        match = re.match(r"^(\s*)(\S+)(\s+)(.*?)\s*$", line.rstrip("\r\n"))
        if not match:
            return None
        key = match.group(2).lower()
        if not (key.startswith("map_") or key in cls._MTL_TEXTURE_KEYS):
            return None
        rest = match.group(4)
        tokens = rest.split()
        position = 0
        while position < len(tokens) and tokens[position].startswith("-"):
            position += 1 + cls._MTL_OPTION_ARGS.get(tokens[position].lower(), 0)
        if position >= len(tokens):
            return None
        cursor = 0
        for token in tokens[:position]:
            cursor = rest.index(token, cursor) + len(token)
        offset = rest.index(tokens[position], cursor)
        head = match.group(1) + match.group(2) + match.group(3) + rest[:offset]
        return head, rest[offset:]

    def _stage_mtl(self, mtl_source, job_dir, resolve, taken, copied):
        """Copy an MTL into job_dir, pulling the textures it references from
        wherever resolve() finds them and rewriting every reference to the
        staged (safe, flat) file name. Returns (mtl_dest, texture_dests,
        warnings)."""
        mtl_source = Path(mtl_source)
        text = mtl_source.read_text(encoding="utf-8", errors="surrogateescape")
        textures, warnings, seen_missing, out_lines = [], [], set(), []
        for line in text.splitlines(keepends=True):
            parsed = self._parse_mtl_texture_line(line)
            if parsed is None:
                out_lines.append(line)
                continue
            head, ref = parsed
            if self._is_unsafe_reference(ref):
                out_lines.append(line)  # the converter rejects unsafe references
                continue
            source = resolve(ref)
            if source is None or source.suffix.lower() not in self.TEXTURE_EXTENSIONS:
                key = ref.strip().lower()
                if key not in seen_missing:
                    seen_missing.add(key)
                    leaf = os.path.basename(ref.replace("\\", "/"))
                    warnings.append(
                        f"Texture '{leaf}' referenced by {mtl_source.name} was not found "
                        "in the upload; the model may appear untextured."
                    )
                out_lines.append(line)
                continue
            name = self._copy_companion(source, job_dir, taken, copied)
            textures.append(job_dir / name)
            ending = line[len(line.rstrip("\r\n")):]
            out_lines.append(f"{head}{name}{ending}")
        if mtl_source.parent == job_dir:
            dest = mtl_source
        else:
            dest = job_dir / self._unique_name(mtl_source.name, taken)
        dest.write_text("".join(out_lines), encoding="utf-8", errors="surrogateescape")
        return dest, textures, warnings

    @staticmethod
    def _obj_mtllib_names(obj_path):
        names = []
        with open(obj_path, "rb") as handle:
            for raw in handle:
                if raw[:6].lower() == b"mtllib" and raw[6:7] in (b" ", b"\t"):
                    value = raw[6:].decode("utf-8", errors="surrogateescape").strip()
                    if value:
                        names.append(value)
        return names

    @staticmethod
    def _rewrite_obj_mtllib(obj_path, mtl_name):
        """Point the mtllib line(s) at the staged MTL name (streamed; the OBJ
        can be large)."""
        tmp_path = Path(str(obj_path) + ".rewrite")
        wrote = False
        with open(obj_path, "rb") as source, open(tmp_path, "wb") as target:
            for raw in source:
                if raw[:6].lower() == b"mtllib" and raw[6:7] in (b" ", b"\t"):
                    if not wrote:
                        target.write(b"mtllib " + mtl_name.encode("utf-8", "surrogateescape") + b"\n")
                        wrote = True
                    continue
                target.write(raw)
        os.replace(tmp_path, obj_path)

    def _stage_obj_materials(self, obj_path, mtl_source, job_dir, resolve, taken, copied):
        """Stage the MTL + textures of an OBJ already placed at obj_path and
        make the OBJ's mtllib reference match the staged MTL name."""
        mtl_dest, textures, warnings = self._stage_mtl(mtl_source, job_dir, resolve, taken, copied)
        if self._obj_mtllib_names(obj_path) != [mtl_dest.name]:
            self._rewrite_obj_mtllib(obj_path, mtl_dest.name)
        return mtl_dest, textures, warnings

    def _stage_gltf(self, source, dest, job_dir, resolve, taken, copied):
        """Copy a .gltf to `dest`, staging the external buffers/images it
        references (never absolute, '..' or URL references) next to it and
        rewriting their URIs. Raises UploadStagingError when a reference is
        unsafe or cannot be found."""
        try:
            document = json.loads(Path(source).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError) as exc:
            raise UploadStagingError("This .gltf file is not valid glTF (it could not be parsed).") from exc
        if not isinstance(document, dict):
            raise UploadStagingError("This .gltf file is not valid glTF (it could not be parsed).")
        for section in ("buffers", "images"):
            for entry in document.get(section) or []:
                uri = entry.get("uri") if isinstance(entry, dict) else None
                if not uri or uri.startswith("data:"):
                    continue
                decoded = unquote(uri)
                if self._is_unsafe_reference(decoded):
                    raise UploadStagingError(
                        "This glTF references an external file path that is not allowed "
                        "(absolute, '..' or URL paths). Re-export it with relative paths."
                    )
                found = resolve(decoded)
                if found is None:
                    raise UploadStagingError(
                        f"This glTF needs the external file '{os.path.basename(decoded)}', which was "
                        "not included. Upload the .gltf together with its .bin and texture files "
                        "as a ZIP archive (or export a single .glb)."
                    )
                entry["uri"] = quote(self._copy_companion(found, job_dir, taken, copied))
        Path(dest).write_text(json.dumps(document), encoding="utf-8")

    def _stage_extracted_model(self, model_path, extract_root, job_dir):
        """Copy one model found in an extracted archive (plus its companions)
        into job_dir. Returns (dest_model, mtl_dest, texture_dests, warnings)."""
        taken, copied = set(), {}
        extension = model_path.suffix.lower()
        dest_model = job_dir / self._unique_name(model_path.name, taken)
        warnings, texture_dests, mtl_dest = [], [], None
        resolve = self._resolver(extract_root, model_path.parent)

        if extension == ".gltf":
            self._stage_gltf(model_path, dest_model, job_dir, resolve, taken, copied)
        else:
            shutil.copyfile(model_path, dest_model)

        if extension == ".obj":
            mtl_source = None
            for value in self._obj_mtllib_names(dest_model):
                # Blender may write names with spaces: try the whole value
                # first, then each whitespace-separated name.
                for candidate in [value, *value.split()]:
                    found = resolve(candidate)
                    if found is not None and found.suffix.lower() == ".mtl":
                        mtl_source = found
                        break
                if mtl_source is not None:
                    break
            if mtl_source is None:
                siblings = sorted(model_path.parent.glob("*.mtl"))
                mtl_source = siblings[0] if siblings else None
            if mtl_source is not None:
                mtl_dest, texture_dests, warnings = self._stage_obj_materials(
                    dest_model, mtl_source, job_dir, resolve, taken, copied
                )

        # Image files beside the model keep riding along (unused ones are ignored).
        for sibling in sorted(model_path.parent.iterdir()):
            if sibling.is_file() and sibling.suffix.lower() in self.TEXTURE_EXTENSIONS:
                name = self._copy_companion(sibling, job_dir, taken, copied)
                texture_dests.append(job_dir / name)
        return dest_model, mtl_dest, list(dict.fromkeys(texture_dests)), warnings

    def _stage_loose_companions(self, primary, job_dir, mtl_path, companion_paths):
        """Single-file upload with separately uploaded MTL/textures/buffers:
        make the companions' (secure_filename-renamed) names consistent with
        the references inside the model. Returns (mtl_path, texture_paths,
        warnings)."""
        by_client_name = {}
        for client_name, path in companion_paths:
            by_client_name[os.path.basename(client_name.replace("\\", "/")).lower()] = path
        taken = {p.name.lower() for p in job_dir.iterdir()}
        copied = {}

        def resolve(ref):
            if self._is_unsafe_reference(ref):
                return None
            return by_client_name.get(os.path.basename(ref.replace("\\", "/")).lower())

        extension = primary.suffix.lower()
        if extension == ".gltf":
            self._stage_gltf(primary, primary, job_dir, resolve, taken, copied)
            return mtl_path, [p for _, p in companion_paths], []
        warnings = []
        texture_paths = [p for _, p in companion_paths]
        if extension == ".obj" and mtl_path is not None:
            mtl_path, extra, warnings = self._stage_obj_materials(
                primary, mtl_path, job_dir, resolve, taken, copied
            )
            texture_paths = list(dict.fromkeys([*texture_paths, *extra]))
        return mtl_path, texture_paths, warnings

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
        dest_model, mtl_dest, textures, warnings = self._stage_extracted_model(
            models[0], extract_root, job_dir
        )
        shutil.rmtree(extract_root, ignore_errors=True)
        return dest_model, mtl_dest, textures, warnings

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
                dest_model, mtl_dest, texture_dests, warnings = self._stage_extracted_model(
                    model_path, extract_root, job_dir
                )

                staged.append((job_id, {
                    "temp_dir": str(job_dir),
                    "temp_file_path": str(dest_model),
                    "original_filename": dest_model.name,
                    "client_filename": model_path.name,
                    "file_extension": dest_model.suffix.lower(),
                    "mtl_path": str(mtl_dest) if mtl_dest else None,
                    "texture_paths": [str(p) for p in texture_dests],
                    "staging_warnings": warnings,
                }))
            return staged
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
