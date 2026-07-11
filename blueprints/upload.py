"""Upload & conversion pipeline: legacy/direct upload endpoints, the async
upload-job flow (stage -> ConversionJob -> poll/retry), batch uploads, and
the USDZ readiness check."""

import json
import math
import os
import secrets
import shutil
import threading
import traceback
import uuid

from flask import Blueprint, jsonify, request, session, url_for
from flask_login import current_user
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import BATCH_UPLOAD_MAX_FILES, CHUNK_UPLOAD_MAX_CHUNKS, MAX_MODEL_DIMENSION_METERS
from converters import FBXConverter, OBJConverter, STEPConverter, STLConverter
from models import ConversionJob, UserModel, db
from services import UploadStagingError
from services.model_permissions import check_model_mutation_allowed, get_live_model
from services.time_utils import datetime
from site_settings import setting_int

upload_bp = Blueprint("upload", __name__)


def _check_upload_size_limit():
    """Admin-configurable upload cap (max_upload_mb setting). The env-derived
    MAX_CONTENT_LENGTH stays the hard ceiling enforced by Werkzeug; this only
    lowers the effective limit at runtime. Returns a response tuple or None."""
    max_mb = setting_int("max_upload_mb", 0)
    if max_mb and request.content_length and request.content_length > max_mb * 1024 * 1024:
        return jsonify({"error": f"File exceeds the {max_mb} MB upload limit"}), 413
    return None


def _check_storage_quota():
    """Admin-configurable per-user storage cap (storage_quota_mb setting).

    Anonymous uploads (user_id is None) aren't tracked to anyone's quota —
    consistent with my_models.html's storage view, which is per-account.
    request.content_length is an approximation of the incoming file size
    (matches the same approximation _check_upload_size_limit already makes).
    Returns a response tuple or None.
    """
    if not current_user.is_authenticated:
        return None
    quota_mb = setting_int("storage_quota_mb", int(os.environ.get("STORAGE_QUOTA_MB", 1024)))
    if not quota_mb:
        return None
    used = (
        db.session.query(db.func.coalesce(db.func.sum(UserModel.file_size), 0))
        .filter(UserModel.user_id == current_user.id)
        .scalar()
    )
    incoming = request.content_length or 0
    if used + incoming > quota_mb * 1024 * 1024:
        return jsonify(
            {"error": f"Storage quota exceeded ({quota_mb} MB limit). Delete some models or contact an admin."}
        ), 413
    return None


@upload_bp.route("/api/models/<model_id>/usdz_status")
def get_usdz_status(model_id):
    """Check if USDZ file is ready for iOS AR viewing."""
    import app as app_module

    try:
        model = get_live_model(model_id)
        if not model:
            return jsonify({"success": False, "error": "Model not found"}), 404

        usdz_ready = False
        usdz_filename = None

        usdz_path = model.usdz_path
        if usdz_path and os.path.exists(usdz_path):
            usdz_ready = True
            usdz_filename = os.path.basename(usdz_path)
        else:
            # Also check the converted directory for usdz files
            converted_dir = os.path.join(app_module.app.config["CONVERTED_FOLDER"], model_id)
            if os.path.isdir(converted_dir):
                usdz_files = [
                    f for f in os.listdir(converted_dir) if f.endswith(".usdz")
                ]
                if usdz_files:
                    usdz_ready = True
                    usdz_filename = usdz_files[0]

        return jsonify(
            {"success": True, "usdz_ready": usdz_ready, "usdz_filename": usdz_filename}
        )
    except Exception as e:
        app_module.logger.error(f"Error checking USDZ status: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@upload_bp.route("/upload", methods=["POST"])
def upload_file():
    """DEPRECATED: Legacy upload route. Use /upload_model instead.
    Kept for backward compatibility with existing tests."""
    import app as app_module

    return jsonify({"success": False, "error": "Legacy upload endpoint removed; use /upload_model"}), 410

    try:
        app_module.logger.info("Starting upload process")

        size_guard = _check_upload_size_limit()
        if size_guard is not None:
            return size_guard
        quota_guard = _check_storage_quota()
        if quota_guard is not None:
            return quota_guard

        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        app_module.logger.info(f"File object: {file}")

        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

        if not app_module.allowed_file(file.filename):
            return jsonify({"error": "File type not allowed"}), 400

        # Generate unique ID
        unique_id = str(uuid.uuid4())
        edit_token = secrets.token_urlsafe(32) if not current_user.is_authenticated else None
        status_token = secrets.token_urlsafe(32)
        app_module.logger.info(f"Generated unique ID: {unique_id}")

        # Create upload subdirectory
        upload_subdir = os.path.join(app_module.app.config["UPLOAD_FOLDER"], unique_id)
        os.makedirs(upload_subdir, exist_ok=True)
        app_module.logger.info(f"Created upload subdirectory: {upload_subdir}")

        # Save uploaded file
        filename = secure_filename(file.filename)
        file_path = os.path.join(upload_subdir, filename)
        file.save(file_path)
        app_module.logger.info(f"File saved successfully: {file_path}")

        # Get file extension
        file_extension = os.path.splitext(filename)[1].lower()
        app_module.logger.info(f"File extension: {file_extension}")

        # Get color settings
        # Handle both string and boolean values for useColor
        use_color_raw = request.form.get("useColor", "false")
        if isinstance(use_color_raw, str):
            use_color = use_color_raw.lower() in ("true", "1", "yes")
        else:
            use_color = bool(use_color_raw)

        color = request.form.get("color", "#4CAF50")
        try:
            color = app_module.validate_color(color)
        except ValueError as exc:
            return jsonify({"success": False, "error": str(exc)}), 400
        compression = request.form.get("compression")
        if compression not in (None, "none", "meshopt", "draco"):
            return jsonify({"success": False, "error": "Invalid compression mode"}), 400
        app_module.logger.info(f"Color settings - useColor: {use_color}, color: {color}")

        # Get texture removal setting (for FBX)
        remove_textures_raw = request.form.get("removeTextures")
        remove_textures = (
            remove_textures_raw == "true" if remove_textures_raw else False
        )
        app_module.logger.info(f"Remove textures setting: {remove_textures}")

        # Get maximum dimension setting (only if checkbox is checked)
        use_max_dimension_raw = request.form.get("useMaxDimension")
        app_module.logger.info(
            f"DEBUG: useMaxDimension raw value: {use_max_dimension_raw}, type: {type(use_max_dimension_raw)}"
        )
        use_max_dimension = (
            use_max_dimension_raw == "true" if use_max_dimension_raw else False
        )
        app_module.logger.info(f"DEBUG: useMaxDimension parsed: {use_max_dimension}")

        if use_max_dimension:
            max_dimension = float(request.form.get("maxDimension", "50"))  # Keep in cm
            app_module.logger.info(f"Maximum dimension limit enabled: {max_dimension} cm")
        else:
            max_dimension = None  # No scaling
            app_module.logger.info(
                f"Maximum dimension limit disabled - model will keep original size"
            )

        # Create converted directory
        converted_dir = os.path.join(app_module.app.config["CONVERTED_FOLDER"], unique_id)
        os.makedirs(converted_dir, exist_ok=True)
        output_path = os.path.join(converted_dir, "model.glb")

        # Get file info
        file_info = app_module.get_file_info(file_path)

        # Convert based on file type
        if file_extension == ".obj":
            converter = OBJConverter()
            # OBJ is unitless; default 'm' (no scaling) keeps the original behaviour.
            converter.set_source_unit(request.form.get("sourceUnit", "m"))

            # Handle MTL file for OBJ
            if "mtl" in request.files:
                mtl_file = request.files["mtl"]
                if mtl_file and mtl_file.filename:
                    mtl_filename = secure_filename(mtl_file.filename)
                    mtl_path = os.path.join(upload_subdir, mtl_filename)
                    mtl_file.save(mtl_path)
                    converter.set_material_file(mtl_path)
                    app_module.logger.info(f"MTL file saved: {mtl_path}")

            # Handle texture files for OBJ
            if "textures" in request.files:
                texture_files = request.files.getlist("textures")
                for texture_file in texture_files:
                    if texture_file and texture_file.filename:
                        texture_filename = secure_filename(texture_file.filename)
                        texture_path = os.path.join(upload_subdir, texture_filename)
                        texture_file.save(texture_path)
                        converter.add_texture_file(texture_path)
                        app_module.logger.info(f"Texture file saved: {texture_path}")

        elif file_extension == ".stl":
            converter = STLConverter()
            converter.set_source_unit(request.form.get("sourceUnit", "cm"))
        elif file_extension == ".fbx":
            converter = FBXConverter()
            # Set texture removal for FBX if requested
            if remove_textures:
                converter.remove_textures = True
                app_module.logger.info("FBX texture removal enabled")
        elif file_extension in (".step", ".stp"):
            # STEP carries real units; cascadio converts to meters directly
            converter = STEPConverter()
        else:
            return jsonify({"error": "Unsupported file format"}), 400

        # Set maximum dimension — form değeri cm, converter metre bekliyor
        if max_dimension is not None:
            converter.set_max_dimension(max_dimension / 100.0)

        # Apply color if specified
        if use_color and color:
            success = converter.convert(file_path, output_path, color=color)
        else:
            success = converter.convert(file_path, output_path)

        if not success:
            return jsonify({"error": "Conversion failed"}), 500

        # Save model info to database
        model = UserModel(
            id=unique_id,  # Use the same unique_id generated for the folder
            user_id=current_user.id if current_user.is_authenticated else None,
            filename=output_path,  # Store the full path to the GLB file
            file_size=os.path.getsize(output_path),
            file_type=os.path.splitext(filename)[1][1:],  # Remove the dot
            upload_date=datetime.utcnow(),
            color=color if use_color else None,
        )
        db.session.add(model)
        db.session.commit()
        app_module.logger.info(f"Model info saved to database with ID: {unique_id}")

        # Generate QR code
        qr_code_filename = app_module.generate_qr_code(unique_id)
        app_module.logger.info(f"QR code generated: {qr_code_filename}")

        # Return success response
        viewer_url = url_for("viewer.view_model", model_id=unique_id)
        return jsonify(
            {
                "success": True,
                "viewer_url": viewer_url,
                "message": "Model uploaded and converted successfully",
            }
        )

    except Exception as e:
        app_module.logger.error(f"Error during upload: {str(e)}")
        app_module.logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@upload_bp.route("/upload_progress")
def upload_progress():
    """Get the current upload progress."""
    progress = session.get("upload_progress", 0)
    return jsonify({"progress": progress})


def _finalize_staged_upload(unique_id, staged, *, use_color, color, max_dimension,
                            source_unit, compression, edit_token, status_token):
    """Shared tail of every upload entrypoint (single-shot /upload_model and
    the chunked-upload /complete step): build the ConversionJob payload,
    persist it, and kick off processing (queue or inline thread)."""
    import app as app_module

    payload = {
        "unique_id": unique_id,
        "original_filename": staged["original_filename"],
        "client_filename": staged["client_filename"],
        "temp_dir": staged["temp_dir"],
        "temp_file_path": staged["temp_file_path"],
        "file_extension": staged["file_extension"],
        "mtl_path": staged["mtl_path"],
        "texture_paths": staged["texture_paths"],
        "use_color": use_color,
        "color": color,
        "max_dimension": max_dimension,
        "source_unit": source_unit,
        "compression": compression,
        "user_id": current_user.id if current_user.is_authenticated else None,
        "edit_token_hash": generate_password_hash(edit_token) if edit_token else None,
    }
    job = ConversionJob(
        id=unique_id,
        job_type="upload",
        status="pending",
        payload=payload,
        user_id=payload["user_id"],
        status_token_hash=generate_password_hash(status_token),
    )
    db.session.add(job)
    db.session.commit()

    if not app_module.JOB_QUEUE_ENABLED:
        def run_local_job(job_id):
            with app_module.app.app_context():
                queued_job = db.session.get(ConversionJob, job_id)
                if queued_job:
                    app_module.run_conversion_job(queued_job, allow_retry=False)

        threading.Thread(target=run_local_job, args=(unique_id,), daemon=True).start()

    # Worker (queue mode) or the thread just started (inline mode) picks it
    # up; the frontend polls the status endpoint either way.
    return jsonify(
        {
            "success": True,
            "job_id": unique_id,
            "status": "pending",
            "status_url": url_for("upload.upload_job_status", job_id=unique_id),
            "status_token": status_token,
            "edit_token": edit_token,
        }
    ), 202


@upload_bp.route("/upload_model", methods=["POST"])
def upload_model():
    """Upload and convert 3D model. Works with or without login."""
    import app as app_module

    size_guard = _check_upload_size_limit()
    if size_guard is not None:
        return size_guard
    quota_guard = _check_storage_quota()
    if quota_guard is not None:
        return quota_guard

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    original_filename = secure_filename(file.filename)
    if not app_module.allowed_file(original_filename):
        return jsonify({"error": "File type not allowed"}), 400

    temp_dir = None  # Initialize temp_dir
    try:
        compression = request.form.get("compression")
        if compression not in (None, "none", "meshopt", "draco"):
            return jsonify({"success": False, "error": "Invalid compression mode"}), 400
        edit_token = secrets.token_urlsafe(32) if not current_user.is_authenticated else None
        status_token = secrets.token_urlsafe(32)

        # Get form data
        # Handle both string and boolean values for useColor
        use_color_raw = request.form.get("useColor", "false")
        if isinstance(use_color_raw, str):
            use_color = use_color_raw.lower() in ("true", "1", "yes")
        else:
            use_color = bool(use_color_raw)

        color = request.form.get("color", "#4CAF50")
        app_module.logger.info(f"Color settings - useColor: {use_color}, color: {color}")

        # Get maximum dimension setting (only if checkbox is checked)
        use_max_dimension_raw = request.form.get("useMaxDimension")
        use_max_dimension = (
            use_max_dimension_raw == "true" if use_max_dimension_raw else False
        )
        app_module.logger.info(f"useMaxDimension checkbox: {use_max_dimension}")

        max_dimension = None
        if use_max_dimension:
            max_dimension_str = request.form.get("maxDimension")
            if max_dimension_str:
                try:
                    max_dimension = float(max_dimension_str) / 100.0
                    if not math.isfinite(max_dimension) or not 0 < max_dimension <= MAX_MODEL_DIMENSION_METERS:
                        return jsonify({
                            "success": False,
                            "error": f"Maximum dimension must be greater than 0 and no more than {MAX_MODEL_DIMENSION_METERS:g} meters",
                        }), 400
                    app_module.logger.info(
                        f"Maximum dimension limit enabled: {max_dimension_str} cm ({max_dimension} m)"
                    )
                except ValueError:
                    return jsonify({"success": False, "error": "Invalid maximum dimension"}), 400
        else:
            app_module.logger.info(
                "Maximum dimension limit disabled - model will keep original size"
            )

        # --- Start: Consistent File Handling Logic ---
        unique_id = str(uuid.uuid4())
        app_module.logger.info(f"[upload_model - {unique_id}] Generated unique ID")

        staged = app_module.upload_staging.stage(
            unique_id,
            file,
            mtl_file=request.files.get("mtl"),
            textures=request.files.getlist("textures"),
        )
        temp_dir = staged["temp_dir"]
        app_module.logger.info(f"[upload_model - {unique_id}] Staged {staged['temp_file_path']}")

        return _finalize_staged_upload(
            unique_id, staged,
            use_color=use_color, color=color, max_dimension=max_dimension,
            source_unit=request.form.get("sourceUnit"), compression=compression,
            edit_token=edit_token, status_token=status_token,
        )

    except UploadStagingError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                app_module.logger.error(
                    f"[upload_model] Error cleaning up temp directory {temp_dir} during exception: {cleanup_error}"
                )
        app_module.logger.error(f"[upload_model] Error in upload_model: {str(e)}")
        app_module.logger.error(traceback.format_exc())
        return jsonify({"error": str(e)}), 500


class _AssembledFileAdapter:
    """Wraps an already-on-disk assembled file with the .filename/.save()
    shape UploadStagingService.stage() expects from a Werkzeug FileStorage,
    so the chunked-upload completion path can reuse it unchanged."""

    def __init__(self, path, filename):
        self.filename = filename
        self._path = path

    def save(self, dst):
        shutil.move(self._path, str(dst))


def _chunk_session_dir(upload_id):
    """Resolve (and validate) a chunk session's directory. upload_id is
    always server-generated (uuid4), but re-derive+contain the path anyway
    rather than trust a client-echoed value blindly."""
    import app as app_module

    root = os.path.join(app_module.app.config["TEMP_FOLDER"], "chunked")
    target = os.path.realpath(os.path.join(root, secure_filename(upload_id)))
    if os.path.dirname(target) != os.path.realpath(root):
        return None
    return target


def _read_chunk_meta(session_dir):
    try:
        with open(os.path.join(session_dir, "meta.json")) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _write_chunk_meta(session_dir, meta):
    with open(os.path.join(session_dir, "meta.json"), "w") as f:
        json.dump(meta, f)


@upload_bp.route("/api/uploads/chunked/init", methods=["POST"])
def init_chunked_upload():
    """Start a resumable upload session for one large model file (no ZIP/MTL/
    texture companions -- those stay on the single-shot /upload_model path).
    The client slices the file into chunks itself and PUTs each one."""
    import app as app_module

    data = request.get_json(silent=True) or {}
    filename = secure_filename(data.get("filename") or "")
    if not filename or not app_module.allowed_file(filename):
        return jsonify({"success": False, "error": "Unsupported or missing filename"}), 400
    if filename.rsplit(".", 1)[1].lower() == "zip":
        return jsonify({"success": False, "error": "ZIP archives aren't supported for chunked upload"}), 400

    try:
        total_size = int(data.get("total_size"))
        total_chunks = int(data.get("total_chunks"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "total_size and total_chunks must be integers"}), 400
    if total_size <= 0 or total_chunks <= 0 or total_chunks > CHUNK_UPLOAD_MAX_CHUNKS:
        return jsonify({"success": False, "error": "Invalid total_size/total_chunks"}), 400

    max_mb = setting_int("max_upload_mb", 0)
    if max_mb and total_size > max_mb * 1024 * 1024:
        return jsonify({"success": False, "error": f"File exceeds the {max_mb} MB upload limit"}), 413

    if current_user.is_authenticated:
        quota_mb = setting_int("storage_quota_mb", int(os.environ.get("STORAGE_QUOTA_MB", 1024)))
        if quota_mb:
            used = (
                db.session.query(db.func.coalesce(db.func.sum(UserModel.file_size), 0))
                .filter(UserModel.user_id == current_user.id)
                .scalar()
            )
            if used + total_size > quota_mb * 1024 * 1024:
                return jsonify({"success": False, "error": "Storage quota exceeded"}), 413

    upload_id = str(uuid.uuid4())
    session_dir = _chunk_session_dir(upload_id)
    os.makedirs(session_dir)
    _write_chunk_meta(session_dir, {
        "filename": filename, "total_size": total_size,
        "total_chunks": total_chunks, "received": [],
    })
    return jsonify({"success": True, "upload_id": upload_id}), 201


@upload_bp.route("/api/uploads/chunked/<upload_id>/chunks/<int:index>", methods=["PUT"])
def put_upload_chunk(upload_id, index):
    """Store one chunk (raw request body). Safe to retry/re-PUT the same
    index -- that's exactly what makes the upload resumable after a drop."""
    session_dir = _chunk_session_dir(upload_id)
    meta = _read_chunk_meta(session_dir) if session_dir else None
    if not meta:
        return jsonify({"success": False, "error": "Unknown upload_id"}), 404
    if not 0 <= index < meta["total_chunks"]:
        return jsonify({"success": False, "error": "Chunk index out of range"}), 400

    data = request.get_data()
    if not data:
        return jsonify({"success": False, "error": "Empty chunk body"}), 400

    with open(os.path.join(session_dir, f"chunk_{index}"), "wb") as f:
        f.write(data)
    if index not in meta["received"]:
        meta["received"].append(index)
        _write_chunk_meta(session_dir, meta)
    return jsonify({"success": True, "received_count": len(meta["received"]), "total_chunks": meta["total_chunks"]})


@upload_bp.route("/api/uploads/chunked/<upload_id>/status", methods=["GET"])
def get_chunked_upload_status(upload_id):
    """Lets the client resume after a reload: which chunks does the server
    already have?"""
    session_dir = _chunk_session_dir(upload_id)
    meta = _read_chunk_meta(session_dir) if session_dir else None
    if not meta:
        return jsonify({"success": False, "error": "Unknown upload_id"}), 404
    return jsonify({"success": True, **meta})


@upload_bp.route("/api/uploads/chunked/<upload_id>/complete", methods=["POST"])
def complete_chunked_upload(upload_id):
    """Assemble the received chunks in order into one file, then hand off to
    the same staging + ConversionJob pipeline /upload_model uses."""
    import app as app_module

    session_dir = _chunk_session_dir(upload_id)
    meta = _read_chunk_meta(session_dir) if session_dir else None
    if not meta:
        return jsonify({"success": False, "error": "Unknown upload_id"}), 404
    if len(meta["received"]) != meta["total_chunks"]:
        missing = sorted(set(range(meta["total_chunks"])) - set(meta["received"]))
        return jsonify({"success": False, "error": "Upload incomplete", "missing_chunks": missing}), 409

    data = request.get_json(silent=True) or {}
    compression = data.get("compression")
    if compression not in (None, "none", "meshopt", "draco"):
        return jsonify({"success": False, "error": "Invalid compression mode"}), 400
    use_color = bool(data.get("useColor", False))
    color = data.get("color", "#4CAF50")
    max_dimension = None
    if data.get("useMaxDimension"):
        try:
            max_dimension = float(data.get("maxDimension")) / 100.0
            if not math.isfinite(max_dimension) or not 0 < max_dimension <= MAX_MODEL_DIMENSION_METERS:
                return jsonify({
                    "success": False,
                    "error": f"Maximum dimension must be greater than 0 and no more than {MAX_MODEL_DIMENSION_METERS:g} meters",
                }), 400
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid maximum dimension"}), 400

    assembled_path = os.path.join(session_dir, meta["filename"])
    try:
        with open(assembled_path, "wb") as out:
            for i in range(meta["total_chunks"]):
                with open(os.path.join(session_dir, f"chunk_{i}"), "rb") as chunk:
                    shutil.copyfileobj(chunk, out)
        for i in range(meta["total_chunks"]):
            os.remove(os.path.join(session_dir, f"chunk_{i}"))

        edit_token = secrets.token_urlsafe(32) if not current_user.is_authenticated else None
        status_token = secrets.token_urlsafe(32)
        unique_id = upload_id
        staged = app_module.upload_staging.stage(
            unique_id, _AssembledFileAdapter(assembled_path, meta["filename"]),
        )
        return _finalize_staged_upload(
            unique_id, staged,
            use_color=use_color, color=color, max_dimension=max_dimension,
            source_unit=data.get("sourceUnit"), compression=compression,
            edit_token=edit_token, status_token=status_token,
        )
    except UploadStagingError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    finally:
        shutil.rmtree(session_dir, ignore_errors=True)


@upload_bp.route("/api/uploads/batch", methods=["POST"])
def batch_upload_models():
    """Stage several independent models and return one trackable job per file."""
    import app as app_module

    files = [item for item in request.files.getlist("files") if item and item.filename]
    if not files:
        return jsonify({"success": False, "error": "No files uploaded"}), 400
    if len(files) > BATCH_UPLOAD_MAX_FILES:
        return jsonify({"success": False, "error": f"Maximum {BATCH_UPLOAD_MAX_FILES} files per batch"}), 400

    user_id = current_user.id if current_user.is_authenticated else None
    jobs, errors = [], []
    for item in files:
        safe_name = secure_filename(item.filename)
        if not app_module.allowed_file(safe_name):
            errors.append({"filename": item.filename, "error": "File type not allowed"})
            continue
        job_id = str(uuid.uuid4())
        edit_token = secrets.token_urlsafe(32) if user_id is None else None
        status_token = secrets.token_urlsafe(32)
        try:
            staged = app_module.upload_staging.stage(job_id, item)
            payload = {
                **staged,
                "unique_id": job_id,
                "use_color": False,
                "color": "#FFFFFF",
                "max_dimension": None,
                "source_unit": request.form.get("sourceUnit"),
                "compression": request.form.get("compression") if request.form.get("compression") in ("none", "meshopt", "draco") else None,
                "user_id": user_id,
                "edit_token_hash": generate_password_hash(edit_token) if edit_token else None,
            }
            job = ConversionJob(
                id=job_id, job_type="upload", status="pending", payload=payload,
                user_id=user_id, status_token_hash=generate_password_hash(status_token),
            )
            db.session.add(job)
            db.session.commit()
            jobs.append({
                "job_id": job_id,
                "filename": item.filename,
                "status_token": status_token,
                "edit_token": edit_token,
                "status_url": url_for("upload.upload_job_status", job_id=job_id),
            })
            if not app_module.JOB_QUEUE_ENABLED:
                app_module._start_local_conversion(job_id)
        except UploadStagingError as exc:
            errors.append({"filename": item.filename, "error": str(exc)})
        except Exception:
            db.session.rollback()
            shutil.rmtree(os.path.join(app_module.app.config["TEMP_FOLDER"], job_id), ignore_errors=True)
            app_module.logger.exception("Batch staging failed for %s", item.filename)
            errors.append({"filename": item.filename, "error": "Failed to stage upload"})

    status = 202 if jobs else 400
    return jsonify({"success": bool(jobs), "jobs": jobs, "errors": errors}), status


@upload_bp.route("/api/upload-jobs/<job_id>", methods=["GET"])
def upload_job_status(job_id):
    """Poll a conversion job. Job ids are unguessable UUIDs; status is safe to
    expose without auth (mirrors the AI generation status endpoint)."""
    import app as app_module

    job = db.session.get(ConversionJob, job_id)
    if not job:
        return jsonify({"success": False, "error": "Job not found"}), 404
    is_owner = current_user.is_authenticated and job.user_id == current_user.id
    token = request.headers.get("X-Job-Status-Token") or request.args.get("status_token")
    if not is_owner and (not token or not job.status_token_hash or
                         not check_password_hash(job.status_token_hash, token)):
        return jsonify({"success": False, "error": "Valid status token required"}), 403

    app_module._recover_interrupted_inline_job(job)

    # Inline conversions run in a gunicorn worker thread. If that worker is
    # OOM-killed mid-conversion (large/complex FBX), the row is orphaned in
    # "processing" forever and the UI spins at the last percent. There is no
    # worker.py in inline mode to requeue it, so fail it here once it's clearly
    # stalled — the frontend already renders job.status == 'failed'. In queue
    # mode, worker.py's own requeue_stale_jobs() reconciliation owns this.
    if not app_module.JOB_QUEUE_ENABLED and job.status == "processing":
        ref = job.started_at or job.created_at
        if ref and (datetime.utcnow() - ref).total_seconds() > app_module.UPLOAD_STALL_SECONDS:
            job.status = "failed"
            job.error = (
                "Conversion stalled — the file may be too large or complex for "
                "the server to process (it can run out of memory). Try a smaller "
                "or decimated model."
            )
            job.finished_at = datetime.utcnow()
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    data = job.to_dict()
    data["success"] = True
    payload = job.payload or {}
    data["progress"] = payload.get("progress")
    data["stage"] = payload.get("stage")
    data["detail"] = payload.get("detail")
    data["filename"] = payload.get("client_filename") or payload.get("original_filename")
    data["events"] = [event.to_dict() for event in job.events[-50:]]
    if job.status == "completed" and job.model_id:
        data["viewer_url"] = url_for("viewer.view_model", model_id=job.model_id)
    return jsonify(data)


@upload_bp.route("/api/upload-jobs/<job_id>/retry", methods=["POST"])
def retry_upload_job(job_id):
    """Explicitly replay a dead-lettered job after capability authorization."""
    import app as app_module

    job = db.session.get(ConversionJob, job_id)
    if not job:
        return jsonify({"success": False, "error": "Job not found"}), 404
    is_owner = current_user.is_authenticated and job.user_id == current_user.id
    token = request.headers.get("X-Job-Status-Token") or (request.get_json(silent=True) or {}).get("status_token")
    if not is_owner and (not token or not job.status_token_hash or
                         not check_password_hash(job.status_token_hash, token)):
        return jsonify({"success": False, "error": "Valid status token required"}), 403
    if job.status not in {"dead_letter", "failed"}:
        return jsonify({"success": False, "error": "Only failed jobs can be retried"}), 409
    staged_dir = (job.payload or {}).get("temp_dir")
    if not staged_dir or not os.path.isdir(staged_dir):
        return jsonify({"success": False, "error": "Staged upload is no longer available"}), 410
    job.status = "pending"
    job.attempts = 0
    job.error = None
    job.finished_at = None
    job.next_attempt_at = datetime.utcnow()
    db.session.commit()
    app_module.conversion_jobs.record(job, "manually_requeued", "Job manually returned to queue")
    if not app_module.JOB_QUEUE_ENABLED:
        # No worker is polling in inline mode; the retry must start its own run.
        app_module._start_local_conversion(job.id)
    return jsonify({"success": True, "status": job.status}), 202


@upload_bp.route("/convert", methods=["POST"])
def convert():
    import app as app_module

    return jsonify({"success": False, "error": "Legacy conversion endpoint removed; use /upload_model"}), 410

    try:
        app_module.logger.info("Starting model conversion process")
        data = request.get_json()

        if not data or "modelId" not in data:
            app_module.logger.warning("No model ID provided")
            return jsonify({"error": "No model ID provided"}), 400

        model_id = data["modelId"]
        selected_color = data.get("selectedColor", "#FFFFFF")

        guard = check_model_mutation_allowed(model_id)
        if guard is not None:
            return guard

        # Find original file in upload subfirectory
        upload_subdir = os.path.join(app_module.app.config["UPLOAD_FOLDER"], model_id)
        if not os.path.isdir(upload_subdir):
            app_module.logger.error(f"Upload directory not found: {upload_subdir}")
            return jsonify(
                {"success": False, "error": "Upload directory not found"}
            ), 404

        original_files = os.listdir(upload_subdir)
        if not original_files:
            app_module.logger.error("No valid source file found in upload directory")
            return jsonify(
                {"success": False, "error": "No valid source file found"}
            ), 404

        source_file = os.path.join(upload_subdir, original_files[0])

        # Create model-specific directory
        model_dir = os.path.join(app_module.app.config["CONVERTED_FOLDER"], model_id)
        os.makedirs(model_dir, exist_ok=True)
        output_file = os.path.join(model_dir, "model.glb")

        # Convert the model
        file_ext = os.path.splitext(source_file)[1].lower()
        if not app_module.convert_model_new(source_file, output_file, color=selected_color):
            app_module.logger.error(f"Model conversion failed for {model_id}")
            return jsonify({"success": False, "error": "Model conversion failed"}), 500

        app_module.logger.info(f"Model converted successfully: {output_file}")

        # Update database if user is authenticated
        if current_user.is_authenticated:
            session = Session(db.engine)
            model = session.get(UserModel, model_id)
            if model:
                model.converted = True
                model.conversion_date = datetime.utcnow()
                db.session.commit()
                app_module.logger.info(f"Model conversion status updated in database: {model_id}")

        return jsonify(
            {"message": "Model converted successfully", "model_id": model_id}
        ), 200

    except Exception as e:
        app_module.logger.error(f"Error in convert: {str(e)}")
        return jsonify({"error": str(e)}), 500
