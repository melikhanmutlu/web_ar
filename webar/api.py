"""JSON API: upload + conversion job polling + small model mutations."""

from pathlib import Path

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from .extensions import db, limiter
from .jobs import enqueue_conversion, run_conversion_job
from .models import ConversionJob, Folder, Model3D

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/upload", methods=["POST"])
@login_required
@limiter.limit("30 per hour")
def upload():
    file = request.files.get("file")
    if not file or not file.filename:
        return jsonify(error="Dosya seçilmedi."), 400

    ext = Path(file.filename).suffix.lower().lstrip(".")
    allowed = current_app.config["ALLOWED_EXTENSIONS"]
    if ext not in allowed:
        return jsonify(error=f"Desteklenmeyen format: .{ext}. "
                             f"Desteklenenler: {', '.join(sorted(allowed))}"), 400

    folder_id = request.form.get("folder_id", type=int)
    if folder_id:
        folder = db.session.get(Folder, folder_id)
        if not folder or folder.user_id != current_user.id:
            return jsonify(error="Klasör bulunamadı."), 404
    else:
        folder_id = None

    job = enqueue_conversion(current_user.id, file, file.filename, folder_id)

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
            folder = db.session.get(Folder, int(folder_id))
            if not folder or folder.user_id != current_user.id:
                return jsonify(error="Klasör bulunamadı."), 404
            model.folder_id = folder.id
    db.session.commit()
    return jsonify(ok=True, name=model.name, folder_id=model.folder_id)
