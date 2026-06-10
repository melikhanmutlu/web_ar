"""Conversion job lifecycle: enqueue on upload, execute in worker or inline.

run_conversion_job() is imported by worker.py (started next to gunicorn by
the Railway start command) and also called inline from the upload endpoint
when JOB_QUEUE is disabled.
"""

import logging
import shutil
from pathlib import Path

from flask import current_app

from .conversion import (ConversionError, apply_customizations,
                         convert_to_glb, export_usdz, inspect_glb)
from .extensions import db
from .models import ConversionJob, Model3D, utcnow
from .qr import generate_qr

logger = logging.getLogger(__name__)


def enqueue_conversion(user_id: int, upload_file, original_name: str,
                       folder_id: int | None,
                       options: dict | None = None) -> ConversionJob:
    """Stage the uploaded file on disk and create a pending job row."""
    job = ConversionJob(user_id=user_id)
    db.session.add(job)
    db.session.flush()  # assigns job.id

    ext = Path(original_name).suffix.lower().lstrip(".")
    staging_dir = Path(current_app.config["UPLOAD_DIR"]) / job.id
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_path = staging_dir / f"source.{ext}"
    upload_file.save(str(staged_path))

    job.payload = {
        "staged_path": str(staged_path),
        "original_name": original_name,
        "ext": ext,
        "folder_id": folder_id,
        "options": options or {},
    }
    db.session.commit()
    return job


def run_conversion_job(job: ConversionJob) -> None:
    """Run one job to completion (or failure). Commits its own transitions."""
    config = current_app.config
    job.status = "processing"
    job.started_at = utcnow()
    job.attempts = (job.attempts or 0) + 1
    db.session.commit()

    payload = job.payload or {}
    staged_path = Path(payload.get("staged_path", ""))

    try:
        if not staged_path.exists():
            raise ConversionError("Staged upload file is missing")

        model_id = job.id  # job id becomes the model id
        glb_name = f"{model_id}.glb"
        glb_path = Path(config["CONVERTED_DIR"]) / glb_name
        convert_to_glb(staged_path, glb_path, config["TOOLS_DIR"])

        options = payload.get("options") or {}
        apply_customizations(
            glb_path,
            color=options.get("color"),
            target_size=options.get("target_size"),
        )

        stats = inspect_glb(glb_path)

        usdz_name = None
        if config.get("USDZ_EXPORT"):
            usdz_path = Path(config["CONVERTED_DIR"]) / f"{model_id}.usdz"
            if export_usdz(glb_path, usdz_path, config["TOOLS_DIR"]):
                usdz_name = usdz_path.name

        qr_name = generate_qr(model_id)

        original = payload.get("original_name") or staged_path.name
        custom_name = (options.get("name") or "").strip()
        model = Model3D(
            id=model_id,
            user_id=job.user_id,
            folder_id=payload.get("folder_id"),
            name=(custom_name or Path(original).stem)[:255] or "Model",
            source_format=payload.get("ext", staged_path.suffix.lstrip(".")),
            glb_filename=glb_name,
            usdz_filename=usdz_name,
            qr_filename=qr_name,
            file_size=glb_path.stat().st_size,
            vertices=stats["vertices"],
            faces=stats["faces"],
            dimensions=stats["dimensions"],
        )
        db.session.add(model)

        job.status = "completed"
        job.model_id = model_id
        job.finished_at = utcnow()
        db.session.commit()

        shutil.rmtree(staged_path.parent, ignore_errors=True)
        logger.info(f"Job {job.id} completed -> model {model_id}")

    except Exception as e:
        db.session.rollback()
        retryable = job.attempts < (job.max_attempts or 1)
        job.status = "pending" if retryable else "failed"
        job.error = str(e)[:2000]
        if not retryable:
            job.finished_at = utcnow()
            shutil.rmtree(staged_path.parent, ignore_errors=True)
        db.session.commit()
        logger.error(f"Job {job.id} attempt {job.attempts} failed: {e}")
