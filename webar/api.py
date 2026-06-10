"""JSON API: uploads, conversion polling, AI generation, model editing."""

import re
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from . import ai
from .conversion import (ConversionError, apply_customizations, export_usdz,
                         inspect_glb, slice_glb)
from .extensions import db, limiter
from .jobs import enqueue_conversion, run_conversion_job
from .models import AIGenerationJob, ConversionJob, Folder, Model3D

bp = Blueprint("api", __name__, url_prefix="/api")

HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
MAX_AI_IMAGE_BYTES = 12 * 1024 * 1024


def _parse_options(form) -> tuple[dict, str | None]:
    """Validate shared customisation options (upload + edit)."""
    options: dict = {}
    name = (form.get("name") or "").strip()
    if name:
        options["name"] = name[:255]

    color = (form.get("color") or "").strip()
    if color:
        if not HEX_COLOR.match(color):
            return {}, "Geçersiz renk kodu."
        options["color"] = color

    target_size = (form.get("target_size") or "").strip()
    if target_size:
        try:
            value = float(target_size)
        except ValueError:
            return {}, "Hedef boyut sayı olmalı."
        if not 0.01 <= value <= 50:
            return {}, "Hedef boyut 0.01–50 m aralığında olmalı."
        options["target_size"] = value
    return options, None


def _own_folder_or_none(folder_id):
    if not folder_id:
        return None, None
    folder = db.session.get(Folder, int(folder_id))
    if not folder or folder.user_id != current_user.id:
        return None, "Klasör bulunamadı."
    return folder.id, None


# --- upload & conversion ------------------------------------------------------

@bp.route("/upload", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Dosya seçilmedi."), 400

    ext = Path(file.filename).suffix.lower().lstrip(".")
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    if ext not in allowed:
        return jsonify(error=f"Desteklenmeyen format: .{ext}. "
                             f"Desteklenenler: {', '.join(sorted(allowed))}"), 400

    folder_id, err = _own_folder_or_none(request.form.get("folder_id", type=int))
    if err:
        return jsonify(error=err), 404

    options, err = _parse_options(request.form)
    if err:
        return jsonify(error=err), 400

    job = enqueue_conversion(current_user.id, file, file.filename, folder_id, options)

    if not current_app.config["JOB_QUEUE"]:
        # No worker handoff — convert inline; the job row still records the
        # outcome so the client-side polling flow is identical.
        run_conversion_job(job)

    return jsonify(job.to_dict()), 202


@bp.route("/jobs/<job_id>")
@login_required
def job_status(job_id: str):
    job = db.session.get(ConversionJob, job_id)
    if not job or job.user_id != current_user.id:
        return jsonify(error="İş bulunamadı."), 404
    return jsonify(job.to_dict())


# --- AI generation (Meshy) ----------------------------------------------------

@bp.route("/ai/status")
@login_required
def ai_status():
    if not ai.enabled():
        return jsonify(enabled=False, remaining=0)
    return jsonify(enabled=True,
                   remaining=ai.remaining_quota(current_user.id),
                   limit=current_app.config["AI_GEN_DAILY_LIMIT"])


@bp.route("/ai/text", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def ai_text():
    if not ai.enabled():
        return jsonify(error="AI üretimi bu sunucuda yapılandırılmamış."), 503
    if ai.remaining_quota(current_user.id) <= 0:
        return jsonify(error="Günlük AI üretim hakkınız doldu."), 429

    data = request.get_json(silent=True) or {}
    prompt = (data.get("prompt") or "").strip()
    if len(prompt) < 3:
        return jsonify(error="Lütfen ne üretmek istediğinizi yazın."), 400
    try:
        job = ai.start_text_job(current_user.id, prompt,
                                art_style=data.get("art_style") or "realistic")
    except ai.MeshyError as e:
        return jsonify(error=str(e)), 502
    return jsonify(job.to_dict()), 202


@bp.route("/ai/image", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def ai_image():
    if not ai.enabled():
        return jsonify(error="AI üretimi bu sunucuda yapılandırılmamış."), 503
    if ai.remaining_quota(current_user.id) <= 0:
        return jsonify(error="Günlük AI üretim hakkınız doldu."), 429

    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify(error="Görsel seçilmedi."), 400
    mime = (file.mimetype or "").lower()
    if mime not in IMAGE_MIMES:
        return jsonify(error="PNG, JPEG veya WebP görsel yükleyin."), 400
    payload = file.read()
    if len(payload) > MAX_AI_IMAGE_BYTES:
        return jsonify(error="Görsel 12 MB'dan küçük olmalı."), 400
    try:
        job = ai.start_image_job(current_user.id, payload, mime,
                                 prompt=(request.form.get("name") or "").strip() or None)
    except ai.MeshyError as e:
        return jsonify(error=str(e)), 502
    return jsonify(job.to_dict()), 202


@bp.route("/ai/jobs/<job_id>")
@login_required
def ai_job_status(job_id: str):
    job = db.session.get(AIGenerationJob, job_id)
    if not job or job.user_id != current_user.id:
        return jsonify(error="İş bulunamadı."), 404
    return jsonify(ai.advance_job(job).to_dict())


# --- model editing --------------------------------------------------------------

@bp.route("/models/<model_id>", methods=["PATCH"])
@login_required
def update_model(model_id: str):
    model = db.session.get(Model3D, model_id)
    if not model or model.user_id != current_user.id:
        return jsonify(error="Model bulunamadı."), 404

    data = request.get_json(silent=True) or {}

    if "name" in data:
        name = str(data["name"]).strip()
        if not name:
            return jsonify(error="İsim boş olamaz."), 400
        model.name = name[:255]

    if "folder_id" in data:
        folder_id = data["folder_id"]
        if folder_id is None:
            model.folder_id = None
        else:
            fid, err = _own_folder_or_none(folder_id)
            if err:
                return jsonify(error=err), 404
            model.folder_id = fid

    # Geometry/material edits rewrite the GLB in place and refresh stats.
    color = (str(data.get("color") or "")).strip() or None
    target_size = data.get("target_size")
    if color and not HEX_COLOR.match(color):
        return jsonify(error="Geçersiz renk kodu."), 400
    if target_size is not None:
        try:
            target_size = float(target_size)
        except (TypeError, ValueError):
            return jsonify(error="Hedef boyut sayı olmalı."), 400
        if not 0.01 <= target_size <= 50:
            return jsonify(error="Hedef boyut 0.01–50 m aralığında olmalı."), 400

    if color or target_size:
        config = current_app.config
        glb_path = Path(config["CONVERTED_DIR"]) / model.glb_filename
        if not glb_path.exists():
            return jsonify(error="Model dosyası bulunamadı."), 500
        try:
            apply_customizations(glb_path, color=color, target_size=target_size)
        except ConversionError as e:
            return jsonify(error=str(e)), 422
        stats = inspect_glb(glb_path)
        model.file_size = glb_path.stat().st_size
        model.vertices = stats["vertices"]
        model.faces = stats["faces"]
        model.dimensions = stats["dimensions"]
        if config.get("USDZ_EXPORT"):
            usdz_path = Path(config["CONVERTED_DIR"]) / f"{model.id}.usdz"
            if export_usdz(glb_path, usdz_path, config["TOOLS_DIR"]):
                model.usdz_filename = usdz_path.name

    db.session.commit()
    return jsonify(ok=True, name=model.name, folder_id=model.folder_id,
                   file_size=model.file_size_human,
                   dimensions=model.dimensions)


@bp.route("/models/<model_id>/slice", methods=["POST"])
@login_required
@limiter.limit("60 per hour")
def slice_model(model_id: str):
    """Destructively cut the GLB with an axis-aligned plane.

    The slicer UI shows a live three.js clipping preview; this endpoint
    performs the real cut with trimesh and refreshes stats + USDZ.
    """
    model = db.session.get(Model3D, model_id)
    if not model or model.user_id != current_user.id:
        return jsonify(error="Model bulunamadı."), 404

    data = request.get_json(silent=True) or {}
    axis = str(data.get("axis") or "").lower()
    keep = "below" if data.get("keep") == "below" else "above"
    cap = bool(data.get("cap", True))
    try:
        position = float(data.get("position"))
    except (TypeError, ValueError):
        return jsonify(error="Kesim konumu 0–1 aralığında olmalı."), 400
    if axis not in ("x", "y", "z") or not 0.0 <= position <= 1.0:
        return jsonify(error="Geçersiz kesim parametreleri."), 400

    config = current_app.config
    glb_path = Path(config["CONVERTED_DIR"]) / model.glb_filename
    if not glb_path.exists():
        return jsonify(error="Model dosyası bulunamadı."), 500

    try:
        slice_glb(glb_path, axis=axis, position=position, keep=keep, cap=cap)
    except ConversionError as e:
        return jsonify(error=str(e)), 422

    stats = inspect_glb(glb_path)
    model.file_size = glb_path.stat().st_size
    model.vertices = stats["vertices"]
    model.faces = stats["faces"]
    model.dimensions = stats["dimensions"]
    if config.get("USDZ_EXPORT"):
        usdz_path = Path(config["CONVERTED_DIR"]) / f"{model.id}.usdz"
        if export_usdz(glb_path, usdz_path, config["TOOLS_DIR"]):
            model.usdz_filename = usdz_path.name
    db.session.commit()
    return jsonify(ok=True, file_size=model.file_size_human,
                   vertices=model.vertices, faces=model.faces,
                   dimensions=model.dimensions)
