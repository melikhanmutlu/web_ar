"""Conversion job runner and the upload/derived-asset pipelines.

Extracted from app.py. ``app.py`` builds the shared service singletons and
hands them over through :func:`configure`; everything else here is looked up
at module level, so tests can monkeypatch ``services.upload_pipeline.X``.
Callers (blueprints, worker.py) should reference the functions through the
module (``upload_pipeline.run_conversion_job``) for the same reason.
"""

import json
import logging
import os
import secrets
import shutil
import threading
import traceback
import uuid
from datetime import timedelta

from flask import current_app, has_app_context
from pygltflib import GLTF2

from config import INLINE_STALE_JOB_MINUTES, SITE_URL
from converters.glb_quality import finalize_glb
from glb_modifier import normalize_model_to_center
from models import (
    ConversionJob,
    ModelDerivedAsset,
    ModelLOD,
    User,
    UserModel,
    db,
)
from services import thumbnails
from services import usdz as usdz_service
from services.conversion import ConversionService
from services.email import send_email
from services.model_permissions import get_live_model
from services.time_utils import datetime
from services.webhooks import dispatch_webhook_event
from version_manager import create_version

logger = logging.getLogger(__name__)

# Shared singletons built by app.py (they need the configured app / DB);
# injected once at startup via configure().
conversion_jobs = None
conversion_service = None
asset_quality = None


def configure(*, conversion_jobs, conversion_service, asset_quality):
    globals().update(
        conversion_jobs=conversion_jobs,
        conversion_service=conversion_service,
        asset_quality=asset_quality,
    )


JOB_QUEUE_ENABLED = os.environ.get("JOB_QUEUE", "false").lower() in (
    "true",
    "1",
    "yes",
)

# UPLOAD_STALL_SECONDS and INLINE_STALE_JOB_MINUTES come from config.py
# (via `from config import *` above).


def _recover_interrupted_inline_job(job):
    """Restart (or fail) a job whose inline thread died with the process."""
    if JOB_QUEUE_ENABLED or job.status not in {"pending", "processing"}:
        return
    last_signal = job.last_heartbeat_at or job.started_at or job.created_at
    if not last_signal or last_signal > datetime.utcnow() - timedelta(
        minutes=INLINE_STALE_JOB_MINUTES
    ):
        return
    staged_dir = (job.payload or {}).get("temp_dir")
    recoverable = job.job_type != "upload" or (staged_dir and os.path.isdir(staged_dir))
    # Compare-and-set on the observed state so concurrent polls cannot both
    # claim the recovery and start duplicate inline threads.
    claimed = ConversionJob.query.filter(
        ConversionJob.id == job.id,
        ConversionJob.status == job.status,
        ConversionJob.last_heartbeat_at == job.last_heartbeat_at,
    ).update(
        {
            "status": "pending" if recoverable else "failed",
            "last_heartbeat_at": datetime.utcnow(),
            "next_attempt_at": datetime.utcnow() if recoverable else None,
            "finished_at": None if recoverable else datetime.utcnow(),
        }
        | ({} if recoverable else {"error": "Conversion was interrupted by a server restart"})
    )
    db.session.commit()
    if not claimed:
        db.session.refresh(job)
        return
    db.session.refresh(job)
    if recoverable:
        conversion_jobs.record(
            job, "inline_recovered", "Restarted after a server interruption"
        )
        _start_local_conversion(job.id)
    else:
        conversion_jobs.record(
            job, "failed", "Staged upload lost in a server interruption", level="error"
        )


def _start_local_conversion(job_id):
    flask_app = current_app._get_current_object()

    def run_local_job():
        with flask_app.app_context():
            queued_job = db.session.get(ConversionJob, job_id)
            if queued_job:
                run_conversion_job(queued_job, allow_retry=False)
    threading.Thread(target=run_local_job, daemon=True).start()


def _enqueue_internal_job(job_type, model_id, payload):
    """Persist a follow-up asset job before optionally starting it locally."""
    job_id = str(uuid.uuid4())
    job = ConversionJob(
        id=job_id,
        job_type=job_type,
        status="pending",
        model_id=model_id,
        user_id=payload.get("user_id"),
        payload={**payload, "model_id": model_id, "job_id": job_id},
    )
    db.session.add(job)
    db.session.commit()
    if not JOB_QUEUE_ENABLED:
        _start_local_conversion(job_id)
    return job


def update_conversion_progress(job, *, progress=None, stage=None, detail=None, extra=None):
    conversion_jobs.update_progress(
        job, progress=progress, stage=stage, detail=detail, extra=extra
    )


def _notify_user_by_email(user_id, subject, body_text):
    """Best-effort notification helper -- see services/email.py. No-op for
    anonymous (user_id is None) jobs/actions."""
    if not user_id:
        return
    user = db.session.get(User, user_id)
    if user and user.email:
        send_email(user.email, subject, body_text)


def run_conversion_job(job, allow_retry=True):
    """Run a ConversionJob through the pipeline with status transitions.

    Failure puts the job back to 'pending' while attempts remain (so the
    worker retries), or 'failed' otherwise. Inline callers pass
    allow_retry=False because nothing would re-poll a pending job.
    """
    conversion_jobs.start(job)
    update_conversion_progress(
        job,
        progress=45,
        stage="Starting conversion",
        detail="The model has been received and the converter is starting.",
    )
    try:
        callback = lambda progress, stage, detail, **extra: update_conversion_progress(
            job, progress=progress, stage=stage, detail=detail, extra=extra
        )
        if job.job_type == "lod":
            model_id = _run_lod_pipeline(job.payload, progress_callback=callback)
        elif job.job_type == "optimize_mobile":
            model_id = _run_optimize_mobile_pipeline(job.payload, progress_callback=callback)
        elif job.job_type in {"retopology", "texture_upscale"}:
            model_id = _run_derived_pipeline(job.payload, progress_callback=callback)
        elif job.job_type in {"thumbnail", "usdz"}:
            model_id = _run_auxiliary_asset_pipeline(job.payload, progress_callback=callback)
        else:
            model_id = _run_upload_pipeline(job.payload, progress_callback=callback)
        conversion_jobs.succeed(job, model_id)
        update_conversion_progress(
            job,
            progress=100,
            stage="Ready",
            detail="The model is ready for the viewer.",
        )
        if job.job_type == "upload":
            dispatch_webhook_event("conversion.completed", job.user_id, {
                "job_id": job.id, "model_id": model_id,
            })
            _notify_user_by_email(
                job.user_id, "Your model is ready",
                # Built without url_for(): this runs from a background
                # thread (inline/JOB_QUEUE=false mode) with only an app
                # context pushed, not a request context, and url_for()
                # requires one or the other (or SERVER_NAME configured).
                f"Your model has finished converting and is ready to view:\n"
                f"{SITE_URL}/view/{model_id}",
            )
    except Exception as e:
        retry = conversion_jobs.fail(job, e, allow_retry=allow_retry)
        update_conversion_progress(
            job,
            progress=35 if retry else 100,
            stage="Retrying" if retry else ("Dead letter" if allow_retry else "Failed"),
            detail=str(e)[:240],
        )
        logger.error(
            f"[conversion_job - {job.id}] attempt {job.attempts} failed "
            f"({'will retry' if retry else 'giving up'}): {e}"
        )
        if not retry and job.job_type == "upload":
            dispatch_webhook_event("conversion.failed", job.user_id, {
                "job_id": job.id, "error": str(e)[:240],
            })
        # Keep dead-letter staging for explicit replay/inspection. Inline jobs
        # cannot be replayed, so their staged files are cleaned immediately.
        if not retry and not allow_retry:
            staged_dir = (job.payload or {}).get("temp_dir")
            if staged_dir and os.path.exists(staged_dir):
                try:
                    shutil.rmtree(staged_dir)
                except Exception as cleanup_error:
                    logger.error(
                        f"[conversion_job - {job.id}] staged cleanup failed: {cleanup_error}"
                    )


def _run_optimize_mobile_pipeline(payload, progress_callback=None):
    """Meshopt-compress a model's GLB for mobile delivery (owner-triggered)."""
    from converters.glb_optimizer import glb_compression_mode, optimize_glb
    from services.model_lock import ModelEditLock
    from version_manager import create_version

    model_id = payload["model_id"]
    model = get_live_model(model_id)
    if not model or not os.path.isfile(model.glb_path):
        raise RuntimeError("Model source is unavailable")
    report = progress_callback or (lambda *_: None)
    report(50, "Optimizing for mobile", "Compressing the model so it loads faster on phones.")
    glb_path = model.glb_path
    with ModelEditLock(os.path.dirname(glb_path)):
        if glb_compression_mode(glb_path) is not None:
            raise RuntimeError("This model is already compressed")
        before = os.path.getsize(glb_path)
        if not optimize_glb(glb_path, enabled=True, mode="meshopt"):
            raise RuntimeError("Optimization could not make this model smaller")
        after = os.path.getsize(glb_path)
        model.file_size = after
        model.validation_report = asset_quality.inspect(glb_path)
        model.bump_asset_version()
        db.session.commit()
        create_version(model_id, "optimize", {
            "compression": "meshopt", "bytes_before": before, "bytes_after": after,
        }, "Optimized for mobile (meshopt)")
    return model_id


def _run_lod_pipeline(payload, progress_callback=None):
    from converters.lod_generator import generate_lods
    model_id = payload["model_id"]
    model = get_live_model(model_id)
    if not model or not model.filename or not os.path.isfile(model.filename):
        raise RuntimeError("Model source is unavailable")
    report = progress_callback or (lambda *_: None)
    report(50, "Generating LODs", "Simplifying geometry into streaming variants.")
    model_dir = os.path.dirname(model.filename)
    temp_dir = os.path.join(model_dir, ".lod_" + payload.get("job_id", secrets.token_hex(4)))
    shutil.rmtree(temp_dir, ignore_errors=True)
    try:
        outputs = generate_lods(
            model.filename,
            temp_dir,
            ratios=payload.get("ratios", [0.5, 0.25, 0.1]),
            meshopt=bool(payload.get("meshopt", True)),
        )
        report(85, "Publishing LODs", "Writing LOD manifest and assets.")
        ModelLOD.query.filter_by(model_id=model_id).delete()
        for output in outputs:
            destination = os.path.join(model_dir, output["filename"])
            os.replace(output["path"], destination)
            db.session.add(ModelLOD(
                model_id=model_id,
                level=output["level"], ratio=output["ratio"],
                filename=destination, file_size=output["file_size"],
            ))
        db.session.commit()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return model_id


def _run_derived_pipeline(payload, progress_callback=None):
    model_id = payload["model_id"]
    kind = payload["kind"]
    model = get_live_model(model_id)
    if not model or not os.path.isfile(model.filename):
        raise RuntimeError("Model source is unavailable")
    report = progress_callback or (lambda *_: None)
    model_dir = os.path.dirname(model.filename)
    if kind == "retopology":
        from converters.lod_generator import generate_lods
        report(55, "Retopologizing", "Building a cleaner reduced-topology variant.")
        temp_dir = os.path.join(model_dir, ".retopology_" + payload["job_id"])
        shutil.rmtree(temp_dir, ignore_errors=True)
        try:
            output = generate_lods(
                model.filename, temp_dir,
                ratios=[payload.get("ratio", 0.65)], meshopt=False,
            )[0]
            filename = "model_retopology.glb"
            destination = os.path.join(model_dir, filename)
            os.replace(output["path"], destination)
            metadata = {"ratio": output["ratio"], "method": "gltfpack-simplify"}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
    elif kind == "texture_upscale":
        from converters.texture_upscale import upscale_embedded_textures
        report(55, "Upscaling textures", "Resampling embedded textures into a high-resolution variant.")
        filename = f"model_textures_{int(payload.get('factor', 2))}x.glb"
        destination = os.path.join(model_dir, filename)
        temp = destination + ".tmp"
        metadata = upscale_embedded_textures(
            model.filename, temp, factor=payload.get("factor", 2)
        )
        finalize_glb(temp, search_dirs=[model_dir], strict=True)
        os.replace(temp, destination)
    else:
        raise RuntimeError("Unknown derived asset kind")
    ModelDerivedAsset.query.filter_by(model_id=model_id, kind=kind).delete()
    db.session.add(ModelDerivedAsset(
        model_id=model_id, kind=kind, filename=destination,
        file_size=os.path.getsize(destination), asset_metadata=metadata,
    ))
    db.session.commit()
    return model_id


def _run_auxiliary_asset_pipeline(payload, progress_callback=None):
    model_id = payload["model_id"]
    model = get_live_model(model_id)
    if not model or not model.filename or not os.path.isfile(model.filename):
        raise RuntimeError("Model source is unavailable")
    report = progress_callback or (lambda *_: None)
    if payload.get("kind") == "usdz":
        report(55, "Preparing iOS AR", "Converting the model to USDZ.")
        output_path = os.path.join(os.path.dirname(model.filename), "model.usdz")
        if not usdz_service.convert_to_usdz(model.filename, output_path):
            raise RuntimeError("USDZ conversion failed")
        model.usdz_filename = output_path
        db.session.commit()
    elif payload.get("kind") == "thumbnail":
        report(55, "Creating preview", "Rendering the model thumbnail.")
        thumbnails.generate_thumbnail_async(model_id, model.filename, payload.get("color"))
        output_path = os.path.join(os.path.dirname(model.filename), "thumbnail.png")
        if not os.path.isfile(output_path):
            raise RuntimeError("Thumbnail generation failed")
    else:
        raise RuntimeError("Unknown auxiliary asset kind")
    report(95, "Publishing asset", "The generated asset is ready.")
    return model_id


def _run_upload_pipeline(payload, progress_callback=None):
    """The conversion pipeline: converter -> GLB -> optimize -> normalize ->
    quality pass -> USDZ/thumbnail threads -> UserModel row + initial version.

    Pure function of the payload (no request context) so it can run inline or
    in worker.py. Returns the model id; raises RuntimeError on failure.
    """
    unique_id = payload["unique_id"]
    original_filename = payload["original_filename"]
    temp_dir = payload.get("temp_dir")
    temp_file_path = payload["temp_file_path"]
    file_extension = payload["file_extension"]
    use_color = bool(payload.get("use_color"))
    color = payload.get("color")
    max_dimension = payload.get("max_dimension")
    user_id = payload.get("user_id")
    # Set by the programmatic write API (POST /api/v1/models): an org-scoped
    # token files the model under its org, and an optional caller-supplied name
    # overrides the filename-derived display name.
    organization_id = payload.get("organization_id")
    display_name_override = payload.get("display_name")

    # Idempotency guard: if a prior attempt already completed the UserModel
    # insert (below) but the job was retried anyway -- e.g. it failed/crashed
    # afterward, or a stale-job sweep requeued it before its "completed"
    # status was recorded (the very case where the staged temp source below
    # has often already been cleaned up) -- re-running the whole pipeline
    # would redo a perfectly good conversion and then crash on the duplicate
    # primary key. Short-circuit instead: the id is a UUID the pipeline chose
    # once, so its presence in the table means this exact attempt already
    # succeeded. Guarded by has_app_context() so this otherwise-pure function
    # can still be called (and reach the file-existence check below) with no
    # Flask app/request context active -- true of every real caller (worker.py
    # and inline request handlers both run inside one) but not of a raw
    # function-level test.
    if has_app_context():
        existing = db.session.get(UserModel, unique_id)
        if existing is not None:
            logger.info(f"[upload_model - {unique_id}] UserModel already exists; retry is a no-op")
            return existing.id

    # Staged source must still exist. Requeued/stale jobs (e.g. picked up
    # after a redeploy) often point at a temp file that was already cleaned
    # up; fail fast and clearly instead of cascading into assimp "Could not
    # import file!" and an FBX2glTF cwd FileNotFoundError.
    if not temp_file_path or not os.path.exists(temp_file_path):
        raise RuntimeError(
            "Source file is no longer available — please re-upload the model."
        )

    converted_dir = os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id)
    os.makedirs(converted_dir, exist_ok=True)
    output_path = os.path.join(converted_dir, "model.glb")
    logger.info(
        f"[upload_model - {unique_id}] Defined final output path: {output_path}"
    )

    def report(progress, stage, detail, **extra):
        if progress_callback:
            progress_callback(progress, stage, detail, **extra)

    try:
        report(48, "Reading source", f"Inspecting {original_filename} and selected conversion options.")
        conversion_result = conversion_service.convert(payload, output_path, progress=report)
        converter = conversion_result["converter"]

        # Check file size before saving to DB
        final_file_size = 0
        if os.path.exists(output_path):
            final_file_size = os.path.getsize(output_path)
            logger.info(
                f"[upload_model - {unique_id}] Final file size of {output_path}: {final_file_size} bytes"
            )
        else:
            logger.error(
                f"[upload_model - {unique_id}] CRITICAL: Output file {output_path} does not exist before saving to DB!"
            )
            raise RuntimeError("Processed file missing")

        if final_file_size == 0:
            logger.warning(
                f"[upload_model - {unique_id}] WARNING: Final file size of {output_path} is 0 bytes!"
            )
            # Decide if 0-byte file is an error
            # return jsonify({'error': 'Internal server error: Processed file is empty'}), 500

        # Pivot normalization, quality pass, compression and dimension
        # measurement all happen inside ConversionService.convert() (compression
        # last, so nothing may re-save the GLB here).
        quality_warnings = conversion_result.get("quality_warnings") or []
        asset_report = conversion_result.get("asset_report")
        # Companion files (e.g. an OBJ texture) missing from the upload.
        staging_warnings = payload.get("staging_warnings") or []
        if staging_warnings:
            quality_warnings = [*quality_warnings, *staging_warnings]
            if isinstance(asset_report, dict):
                asset_report = {
                    **asset_report,
                    "valid": False,
                    "warnings": [*(asset_report.get("warnings") or []), *staging_warnings],
                }

        # Clean up temporary file and directory
        try:
            if temp_dir:
                shutil.rmtree(temp_dir)
                logger.info(
                    f"[upload_model - {unique_id}] Cleaned up temporary directory: {temp_dir}"
                )
        except Exception as cleanup_error:
            logger.error(
                f"[upload_model - {unique_id}] Error cleaning up temp directory {temp_dir}: {cleanup_error}"
            )

        # --- End: Consistent File Handling Logic ---

        # Calculate model dimensions for database
        model_bounds = None
        # resolved_unit: the unit actually applied to unitless STL/OBJ input
        # (what "auto" resolved to); exposed by the job status response.
        report(91, "Measuring model", "Calculating dimensions for the model details panel.",
               resolved_unit=conversion_result.get("source_unit"))

        # For FBX, try to use original dimensions from converter
        # BUT if scaling was applied, we need to scale the dimensions too!
        if (
            file_extension == ".fbx"
            and hasattr(converter, "original_dimensions")
            and converter.original_dimensions
        ):
            try:
                import json

                orig_dims = converter.original_dimensions

                # Check if scaling was applied
                scale_factor = 1.0
                if hasattr(converter, "max_dimension") and converter.max_dimension > 0:
                    # Scaling was applied - calculate the scale factor
                    orig_max_m = orig_dims["max"]
                    target_max_m = converter.max_dimension
                    scale_factor = min(1.0, target_max_m / orig_max_m)
                    logger.info(
                        f"[upload_model - {unique_id}] FBX was scaled: {scale_factor:.4f}x (orig: {orig_max_m:.4f}m -> target: {target_max_m:.4f}m)"
                    )

                # Apply scale factor to dimensions
                x_cm = round(orig_dims["x"] * scale_factor * 100, 2)
                y_cm = round(orig_dims["y"] * scale_factor * 100, 2)
                z_cm = round(orig_dims["z"] * scale_factor * 100, 2)
                max_cm = round(orig_dims["max"] * scale_factor * 100, 2)

                model_bounds = json.dumps(
                    {"extents": [x_cm, y_cm, z_cm], "max": max_cm}
                )
                logger.info(
                    f"[upload_model - {unique_id}] Using FBX dimensions (after scaling): {x_cm} x {y_cm} x {z_cm} cm (max: {max_cm} cm)"
                )
            except Exception as e:
                logger.warning(
                    f"[upload_model - {unique_id}] Could not use original FBX dimensions: {str(e)}"
                )

        # Prefer the dimensions ConversionService measured on the UNcompressed
        # geometry (before its final compression step). Re-measuring the stored
        # file here is unreliable once it's meshopt-compressed (quantized
        # coordinates), so use the service's value when available.
        if not model_bounds:
            svc_dims = conversion_result.get("dimensions_cm")
            if svc_dims:
                import json
                model_bounds = json.dumps({
                    "extents": [svc_dims["x"], svc_dims["y"], svc_dims["z"]],
                    "max": svc_dims["max"],
                })
                logger.info(f"[upload_model - {unique_id}] Using service dimensions: {svc_dims}")

        # If not FBX or FBX dimensions failed, try from GLB
        if not model_bounds:
            try:
                import trimesh
                import numpy as np
                import json
                from converters.glb_optimizer import readable_glb

                # If the output was meshopt/draco compressed, trimesh reads it
                # as empty geometry -- decompress to a temp copy first, or the
                # stored dimensions would be all zeros (and the viewer would
                # show 0 x 0 x 0, blocking slicing).
                with readable_glb(output_path) as readable_path:
                    mesh = trimesh.load(readable_path)
                logger.info(
                    f"[upload_model - {unique_id}] Loaded mesh type: {type(mesh)}"
                )

                # Get extents
                if isinstance(mesh, trimesh.Scene):
                    logger.info(
                        f"[upload_model - {unique_id}] Scene has {len(mesh.geometry)} geometries"
                    )
                    all_vertices = []
                    for geom in mesh.geometry.values():
                        if isinstance(geom, trimesh.Trimesh):
                            all_vertices.append(geom.vertices)

                    if all_vertices:
                        combined_vertices = np.vstack(all_vertices)
                        logger.info(
                            f"[upload_model - {unique_id}] Combined {len(all_vertices)} vertex arrays, total vertices: {len(combined_vertices)}"
                        )
                        min_bounds = combined_vertices.min(axis=0)
                        max_bounds = combined_vertices.max(axis=0)
                        extents = max_bounds - min_bounds
                        logger.info(
                            f"[upload_model - {unique_id}] Extents from vertices: {extents}"
                        )
                    else:
                        bounds = mesh.bounds
                        extents = bounds[1] - bounds[0]
                        logger.info(
                            f"[upload_model - {unique_id}] Extents from scene bounds: {extents}"
                        )
                else:
                    extents = mesh.extents
                    logger.info(
                        f"[upload_model - {unique_id}] Extents from mesh: {extents}"
                    )

                # Convert to cm and store (4 decimals below 1 cm so sub-mm parts
                # are not dropped or rounded to zero)
                dims = ConversionService.dimensions_cm_from_extents(extents)
                if dims:
                    x_cm, y_cm, z_cm, max_cm = dims["x"], dims["y"], dims["z"], dims["max"]

                    model_bounds = json.dumps(
                        {"extents": [x_cm, y_cm, z_cm], "max": max_cm}
                    )
                    logger.info(
                        f"[upload_model - {unique_id}] Model dimensions: {x_cm} x {y_cm} x {z_cm} cm (max: {max_cm} cm)"
                    )
                else:
                    logger.warning(
                        f"[upload_model - {unique_id}] Extents zero: {extents}"
                    )
            except Exception as e:
                logger.warning(
                    f"[upload_model - {unique_id}] Could not calculate dimensions: {str(e)}"
                )

        # Store original (pre-scaling) dimensions separately from current bounds
        # original_dimensions = dimensions BEFORE any user scaling was applied
        # bounds = current dimensions (after scaling if any)
        original_dims = None
        if (
            hasattr(converter, "original_dimensions")
            and converter.original_dimensions
        ):
            try:
                orig = converter.original_dimensions
                original_dims = {
                    "x": round(orig["x"] * 100, 2),
                    "y": round(orig["y"] * 100, 2),
                    "z": round(orig["z"] * 100, 2),
                    "max": round(orig["max"] * 100, 2),
                }
            except Exception:
                pass
        # Fallback: if no pre-scaling dims available, use current bounds
        if not original_dims and model_bounds:
            try:
                bounds_data = json.loads(model_bounds)
                original_dims = {
                    "x": bounds_data["extents"][0],
                    "y": bounds_data["extents"][1],
                    "z": bounds_data["extents"][2],
                    "max": bounds_data["max"],
                }
            except Exception:
                pass

        # Create model record in database using the unique_id
        # user_id is optional - can be None if user is not logged in
        report(94, "Saving model", "Writing model metadata and version history.")
        model = UserModel(
            id=unique_id,  # Use the same ID as the directory
            user_id=user_id,
            filename=output_path,  # Store the full path to the GLB file
            usdz_filename=None,  # USDZ conversion runs async, will be updated when complete
            file_size=final_file_size,  # Use the checked size
            file_type=os.path.splitext(original_filename)[1][1:],  # Original extension
            upload_date=datetime.utcnow(),
            color=color if use_color else None,
            organization_id=organization_id,
            display_name=(display_name_override or os.path.splitext(
                payload.get("client_filename", original_filename)
            )[0])[:255],
            bounds=model_bounds,  # Store dimensions
            original_dimensions=original_dims,  # Store original dimensions
            cumulative_scale=1.0,  # Initial scale is 1.0
            edit_token_hash=payload.get("edit_token_hash"),
            validation_report=asset_report,
            vertices=(asset_report or {}).get("vertices"),
            faces=(asset_report or {}).get("triangles"),
            source_filename=str(payload.get("client_filename", original_filename))[:255],
        )
        db.session.add(model)
        db.session.commit()
        logger.info(
            f"[upload_model - {unique_id}] Model info saved to database. User: {user_id if user_id is not None else 'anonymous'}"
        )

        # Create initial version entry
        try:
            create_version(
                model_id=unique_id,
                operation_type="upload",
                operation_details={
                    "original_filename": payload.get("client_filename", original_filename),
                    "file_type": file_extension,
                    "max_dimension": max_dimension,
                },
                comment="Initial upload",
            )
            logger.info(f"[upload_model - {unique_id}] Created initial version entry")
        except Exception as version_error:
            logger.error(
                f"[upload_model - {unique_id}] Failed to create initial version: {version_error}"
            )

        # Follow-up assets are durable jobs. A process restart can no longer
        # silently lose thumbnail or iOS AR generation work.
        report(97, "Creating previews", "Queueing thumbnail and iOS AR assets.")
        _enqueue_internal_job(
            "thumbnail", unique_id,
            {"kind": "thumbnail", "color": color if use_color else None, "user_id": user_id},
        )
        _enqueue_internal_job(
            "usdz", unique_id,
            {"kind": "usdz", "user_id": user_id},
        )

        return unique_id

    except Exception as e:
        # Staged files are NOT deleted here — a retrying worker needs them.
        # run_conversion_job cleans up when it gives up for good.
        logger.error(f"[upload_model - {unique_id}] Pipeline error: {str(e)}")
        logger.error(traceback.format_exc())
        raise


def register_glb_as_model(glb_path, *, user_id=None, source="ai", prompt=None,
                          usdz_src_path=None, color=None):
    """Register an already-prepared GLB into the same pipeline as /upload_model.

    Mirrors the upload flow: UUID dir -> converted/<uuid>/model.glb -> bounds via
    trimesh -> UserModel -> async thumbnail (+ USDZ: use the provided file if any,
    otherwise fall back to the Blender async path). Returns the committed UserModel.
    """
    import json as _json

    unique_id = str(uuid.uuid4())
    converted_dir = os.path.join(current_app.config["CONVERTED_FOLDER"], unique_id)
    os.makedirs(converted_dir, exist_ok=True)
    output_path = os.path.join(converted_dir, "model.glb")
    shutil.copy2(glb_path, output_path)

    # Best-effort centre-normalize (same as upload) for consistent pivot
    try:
        g = GLTF2().load(output_path)
        g = normalize_model_to_center(g)
        g.save(output_path)
    except Exception as e:
        logger.warning(f"[register_glb] normalize skipped: {e}")

    # GLB quality pass (warn-only): embedded textures + PBR guarantee + validation
    quality_warnings = []
    try:
        quality_warnings = finalize_glb(output_path, search_dirs=[converted_dir,
                                                                  os.path.dirname(glb_path)])
        for w in quality_warnings:
            logger.warning(f"[register_glb] GLB quality: {w}")
    except Exception as e:
        logger.warning(f"[register_glb] GLB quality pass skipped: {e}")

    # Dimensions / bounds (mirror upload_model GLB branch)
    model_bounds = None
    try:
        import trimesh
        import numpy as np

        from converters.glb_optimizer import readable_glb

        with readable_glb(output_path) as readable_path:
            mesh = trimesh.load(readable_path)
        if isinstance(mesh, trimesh.Scene):
            verts = [gm.vertices for gm in mesh.geometry.values()
                     if isinstance(gm, trimesh.Trimesh)]
            if verts:
                cv = np.vstack(verts)
                extents = cv.max(axis=0) - cv.min(axis=0)
            else:
                b = mesh.bounds
                extents = b[1] - b[0]
        else:
            extents = mesh.extents
        if max(extents) > 0.001:
            model_bounds = _json.dumps({
                "extents": [round(float(extents[0]) * 100, 2),
                            round(float(extents[1]) * 100, 2),
                            round(float(extents[2]) * 100, 2)],
                "max": round(float(max(extents)) * 100, 2),
            })
    except Exception as e:
        logger.warning(f"[register_glb] bounds calc failed: {e}")

    # USDZ: prefer the supplied file (e.g. Meshy) so we skip Blender entirely
    usdz_path = os.path.join(converted_dir, "model.usdz")
    usdz_filename = None
    if usdz_src_path and os.path.exists(usdz_src_path):
        try:
            shutil.copy2(usdz_src_path, usdz_path)
            usdz_filename = usdz_path
        except Exception as e:
            logger.warning(f"[register_glb] usdz copy failed: {e}")

    try:
        ai_asset_report = asset_quality.inspect(output_path, quality_warnings)
    except Exception as e:
        ai_asset_report = {"valid": False, "warnings": [f"Inspection failed: {e}"]}
    clean_prompt = (prompt or "").strip()
    seo_title = (clean_prompt[:60] if clean_prompt else "AI generated 3D model")
    seo_description = (
        f"Interactive AR-ready 3D model generated from: {clean_prompt[:150]}"
        if clean_prompt else "Interactive AR-ready AI generated 3D model."
    )
    model = UserModel(
        id=unique_id,
        user_id=user_id,
        filename=output_path,
        usdz_filename=usdz_filename,
        file_size=os.path.getsize(output_path),
        file_type="glb",
        upload_date=datetime.utcnow(),
        color=color,
        bounds=model_bounds,
        original_dimensions=None,
        cumulative_scale=1.0,
        display_name=(prompt[:80] if prompt else None),
        description=(
            (f"AI generated ({source})" if source.startswith("ai") else f"Combined scene ({source})")
            + (f": {prompt}" if prompt else "")
        ),
        validation_report=ai_asset_report,
        vertices=ai_asset_report.get("vertices"),
        faces=ai_asset_report.get("triangles"),
        seo_metadata={
            "title": seo_title,
            "description": seo_description,
            "keywords": ["3D model", "AR", "AI generated", source],
        },
        source=source,
    )
    db.session.add(model)
    db.session.commit()

    try:
        create_version(model_id=unique_id, operation_type="upload",
                       operation_details={"source": source, "prompt": prompt},
                       comment="AI generation")
    except Exception as e:
        logger.error(f"[register_glb] version failed: {e}")

    _enqueue_internal_job(
        "thumbnail", unique_id,
        {"kind": "thumbnail", "color": color, "user_id": user_id},
    )
    if not usdz_filename:
        _enqueue_internal_job(
            "usdz", unique_id,
            {"kind": "usdz", "user_id": user_id},
        )

    return model
