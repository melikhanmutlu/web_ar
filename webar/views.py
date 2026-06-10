"""Page views: landing, dashboard, model viewer, folders, file serving."""

from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_from_directory, url_for)
from flask_login import current_user, login_required

from .extensions import db
from .forms import FolderForm
from .models import Folder, Model3D
from .qr import public_base_url

bp = Blueprint("views", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


@bp.route("/dashboard")
@login_required
def dashboard():
    folder_id = request.args.get("folder", type=int)
    active_folder = None
    query = Model3D.query.filter_by(user_id=current_user.id)
    if folder_id:
        active_folder = db.session.get(Folder, folder_id)
        if not active_folder or active_folder.user_id != current_user.id:
            abort(404)
        query = query.filter_by(folder_id=folder_id)
    models = query.order_by(Model3D.created_at.desc()).all()
    folders = (Folder.query.filter_by(user_id=current_user.id)
               .order_by(Folder.name).all())
    return render_template(
        "dashboard.html",
        models=models,
        folders=folders,
        active_folder=active_folder,
        folder_form=FolderForm(),
        allowed_extensions=sorted(current_app.config["ALLOWED_EXTENSIONS"]),
    )


@bp.route("/folders", methods=["POST"])
@login_required
def create_folder():
    form = FolderForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        exists = Folder.query.filter(
            Folder.user_id == current_user.id,
            db.func.lower(Folder.name) == name.lower(),
        ).first()
        if exists:
            flash("Bu isimde bir klasör zaten var.", "error")
        else:
            folder = Folder(user_id=current_user.id, name=name)
            db.session.add(folder)
            db.session.commit()
            flash(f"“{name}” klasörü oluşturuldu.", "success")
            return redirect(url_for("views.dashboard", folder=folder.id))
    else:
        flash("Klasör adı geçersiz.", "error")
    return redirect(url_for("views.dashboard"))


@bp.route("/folders/<int:folder_id>/delete", methods=["POST"])
@login_required
def delete_folder(folder_id: int):
    folder = db.session.get(Folder, folder_id)
    if not folder or folder.user_id != current_user.id:
        abort(404)
    # Models survive folder deletion; they just become uncategorised.
    for model in folder.models:
        model.folder_id = None
    db.session.delete(folder)
    db.session.commit()
    flash(f"“{folder.name}” klasörü silindi.", "success")
    return redirect(url_for("views.dashboard"))


@bp.route("/m/<model_id>")
def viewer(model_id: str):
    """Public viewer page — this is what the QR code / share link opens."""
    model = db.session.get(Model3D, model_id)
    if not model:
        abort(404)
    model.view_count = (model.view_count or 0) + 1
    db.session.commit()
    return render_template(
        "viewer.html",
        model=model,
        share_url=f"{public_base_url()}/m/{model.id}",
        is_owner=current_user.is_authenticated and current_user.id == model.user_id,
    )


@bp.route("/m/<model_id>/embed")
def embed(model_id: str):
    model = db.session.get(Model3D, model_id)
    if not model:
        abort(404)
    return render_template("embed.html", model=model)


@bp.route("/m/<model_id>/delete", methods=["POST"])
@login_required
def delete_model(model_id: str):
    model = db.session.get(Model3D, model_id)
    if not model or model.user_id != current_user.id:
        abort(404)
    converted = Path(current_app.config["CONVERTED_DIR"])
    qr_dir = Path(current_app.config["QR_DIR"])
    for path in (converted / (model.glb_filename or ""),
                 converted / (model.usdz_filename or "x.none"),
                 qr_dir / (model.qr_filename or "x.none")):
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass
    db.session.delete(model)
    db.session.commit()
    flash(f"“{model.name}” silindi.", "success")
    return redirect(url_for("views.dashboard"))


# --- file serving ------------------------------------------------------------
# Model ids are unguessable UUIDs and the viewer link is meant to be shared
# (QR scans open it logged-out on a phone), so GLB/USDZ/QR files are public.

@bp.route("/files/models/<path:filename>")
def model_file(filename: str):
    return send_from_directory(current_app.config["CONVERTED_DIR"], filename)


@bp.route("/files/qr/<path:filename>")
def qr_file(filename: str):
    return send_from_directory(current_app.config["QR_DIR"], filename)


@bp.route("/healthz")
def healthz():
    return {"status": "ok"}
