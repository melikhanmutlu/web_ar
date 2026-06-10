"""Meshy AI integration: text-to-3D and image-to-3D.

Design: no background thread. The frontend polls GET /api/ai/jobs/<id>;
every poll calls advance_job(), which queries Meshy, moves the two-stage
text pipeline (preview -> refine) forward and, on success, downloads the
GLB and finalises it through the same path uploads take (stats, QR, USDZ,
Model3D row). Safe under multiple gunicorn workers because all state lives
in the AIGenerationJob row.
"""

import base64
import logging
from pathlib import Path

import requests
from flask import current_app

from .conversion import export_usdz, inspect_glb
from .extensions import db
from .models import AIGenerationJob, Model3D, utcnow
from .qr import generate_qr

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
DOWNLOAD_TIMEOUT = 120

# Map Meshy stages to overall progress bands so the UI shows one smooth bar.
_TEXT_BANDS = {"preview": (0, 45), "refine": (45, 95)}


class MeshyError(Exception):
    pass


def enabled() -> bool:
    return bool(current_app.config.get("MESHY_API_KEY"))


def remaining_quota(user_id: int) -> int:
    limit = current_app.config["AI_GEN_DAILY_LIMIT"]
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used = AIGenerationJob.query.filter(
        AIGenerationJob.user_id == user_id,
        AIGenerationJob.created_at >= day_start,
    ).count()
    return max(0, limit - used)


def _headers() -> dict:
    return {"Authorization": f"Bearer {current_app.config['MESHY_API_KEY']}"}


def _base() -> str:
    return current_app.config["MESHY_API_BASE"].rstrip("/")


def _post(path: str, payload: dict) -> str:
    try:
        resp = requests.post(f"{_base()}{path}", json=payload,
                             headers=_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise MeshyError(f"Meshy'ye ulaşılamadı: {e}") from e
    if resp.status_code >= 400:
        raise MeshyError(f"Meshy hatası ({resp.status_code}): {resp.text[:300]}")
    task_id = (resp.json() or {}).get("result")
    if not task_id:
        raise MeshyError("Meshy görev kimliği döndürmedi.")
    return task_id


def _get_task(path: str, task_id: str) -> dict:
    try:
        resp = requests.get(f"{_base()}{path}/{task_id}",
                            headers=_headers(), timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        raise MeshyError(f"Meshy'ye ulaşılamadı: {e}") from e
    if resp.status_code >= 400:
        raise MeshyError(f"Meshy hatası ({resp.status_code}): {resp.text[:300]}")
    return resp.json() or {}


# --- job creation ------------------------------------------------------------

def start_text_job(user_id: int, prompt: str, art_style: str = "realistic") -> AIGenerationJob:
    task_id = _post("/v2/text-to-3d", {
        "mode": "preview",
        "prompt": prompt[:600],
        "art_style": art_style if art_style in ("realistic", "sculpture") else "realistic",
        "ai_model": current_app.config["MESHY_AI_MODEL"],
    })
    job = AIGenerationJob(user_id=user_id, kind="text", prompt=prompt[:600],
                          stage="preview", meshy_preview_id=task_id)
    db.session.add(job)
    db.session.commit()
    return job


def start_image_job(user_id: int, image_bytes: bytes, mime: str,
                    prompt: str | None = None) -> AIGenerationJob:
    data_uri = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
    task_id = _post("/v1/image-to-3d", {
        "image_url": data_uri,
        "ai_model": current_app.config["MESHY_AI_MODEL"],
        "should_texture": True,
        "enable_pbr": True,
    })
    job = AIGenerationJob(user_id=user_id, kind="image", prompt=prompt,
                          stage="image", meshy_image_id=task_id)
    db.session.add(job)
    db.session.commit()
    return job


# --- polling / state machine -------------------------------------------------

def advance_job(job: AIGenerationJob) -> AIGenerationJob:
    """Poll Meshy once and advance the job. Commits its own transitions."""
    if job.status != "generating":
        return job
    try:
        if job.kind == "text":
            _advance_text(job)
        else:
            _advance_image(job)
    except MeshyError as e:
        job.status = "failed"
        job.error = str(e)[:2000]
        logger.error(f"AI job {job.id} failed: {e}")
    except Exception as e:  # noqa: BLE001 — a poll must never 500 the API
        job.status = "failed"
        job.error = f"Beklenmeyen hata: {e}"
        logger.error(f"AI job {job.id} crashed: {e}", exc_info=True)
    db.session.commit()
    return job


def _advance_text(job: AIGenerationJob) -> None:
    if job.stage == "preview":
        task = _get_task("/v2/text-to-3d", job.meshy_preview_id)
        _apply_progress(job, task, *_TEXT_BANDS["preview"])
        if task.get("status") == "SUCCEEDED":
            job.meshy_refine_id = _post("/v2/text-to-3d", {
                "mode": "refine",
                "preview_task_id": job.meshy_preview_id,
                "ai_model": current_app.config["MESHY_AI_MODEL"],
            })
            job.stage = "refine"
            job.progress = _TEXT_BANDS["refine"][0]
        elif task.get("status") in ("FAILED", "CANCELED"):
            raise MeshyError(_task_error(task))
    elif job.stage == "refine":
        task = _get_task("/v2/text-to-3d", job.meshy_refine_id)
        _apply_progress(job, task, *_TEXT_BANDS["refine"])
        if task.get("status") == "SUCCEEDED":
            _finalize(job, task)
        elif task.get("status") in ("FAILED", "CANCELED"):
            raise MeshyError(_task_error(task))


def _advance_image(job: AIGenerationJob) -> None:
    task = _get_task("/v1/image-to-3d", job.meshy_image_id)
    _apply_progress(job, task, 0, 95)
    if task.get("status") == "SUCCEEDED":
        _finalize(job, task)
    elif task.get("status") in ("FAILED", "CANCELED"):
        raise MeshyError(_task_error(task))


def _apply_progress(job: AIGenerationJob, task: dict, lo: int, hi: int) -> None:
    pct = int(task.get("progress") or 0)
    job.progress = max(job.progress or 0, lo + (hi - lo) * pct // 100)


def _task_error(task: dict) -> str:
    err = (task.get("task_error") or {}).get("message")
    return err or f"Meshy görevi başarısız oldu ({task.get('status')})."


def _finalize(job: AIGenerationJob, task: dict) -> None:
    """Download the generated GLB and register it like a normal upload."""
    glb_url = (task.get("model_urls") or {}).get("glb")
    if not glb_url:
        raise MeshyError("Meshy GLB çıktısı vermedi.")

    config = current_app.config
    model_id = job.id
    glb_path = Path(config["CONVERTED_DIR"]) / f"{model_id}.glb"
    glb_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with requests.get(glb_url, stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
            resp.raise_for_status()
            with open(glb_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
    except requests.RequestException as e:
        raise MeshyError(f"Model indirilemedi: {e}") from e

    stats = inspect_glb(glb_path)

    usdz_name = None
    if config.get("USDZ_EXPORT"):
        usdz_path = Path(config["CONVERTED_DIR"]) / f"{model_id}.usdz"
        if export_usdz(glb_path, usdz_path, config["TOOLS_DIR"]):
            usdz_name = usdz_path.name

    name = (job.prompt or "AI Model").strip()[:80] or "AI Model"
    model = Model3D(
        id=model_id,
        user_id=job.user_id,
        name=name,
        source_format="ai",
        glb_filename=glb_path.name,
        usdz_filename=usdz_name,
        qr_filename=generate_qr(model_id),
        file_size=glb_path.stat().st_size,
        vertices=stats["vertices"],
        faces=stats["faces"],
        dimensions=stats["dimensions"],
    )
    db.session.add(model)
    job.model_id = model_id
    job.status = "ready"
    job.progress = 100
