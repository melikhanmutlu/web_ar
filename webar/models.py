"""Database models.

Kept deliberately small: a user owns folders and 3D models; every upload is
tracked through a ConversionJob row that doubles as the work queue for
worker.py (the same pattern the previous deployment used, so the Railway
start command keeps working unchanged).
"""

import uuid
from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


class User(UserMixin, db.Model):
    __tablename__ = "webar_user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    folders = db.relationship(
        "Folder", backref="owner", lazy=True, cascade="all, delete-orphan"
    )
    models = db.relationship("Model3D", backref="owner", lazy=True)

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class Folder(db.Model):
    __tablename__ = "webar_folder"
    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_folder_user_name"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("webar_user.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    models = db.relationship("Model3D", backref="folder", lazy=True)

    def __repr__(self) -> str:
        return f"<Folder {self.name}>"


class Model3D(db.Model):
    __tablename__ = "webar_model"

    # UUID primary key: the public share/AR link is /m/<id>, so ids must be
    # unguessable rather than sequential.
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    user_id = db.Column(db.Integer, db.ForeignKey("webar_user.id"), nullable=False, index=True)
    folder_id = db.Column(db.Integer, db.ForeignKey("webar_folder.id"), nullable=True, index=True)

    name = db.Column(db.String(255), nullable=False)
    source_format = db.Column(db.String(10), nullable=False)  # obj|stl|fbx|glb|gltf
    glb_filename = db.Column(db.String(255), nullable=False)  # inside CONVERTED_DIR
    usdz_filename = db.Column(db.String(255), nullable=True)  # iOS Quick Look, optional
    qr_filename = db.Column(db.String(255), nullable=True)    # inside QR_DIR

    file_size = db.Column(db.Integer, nullable=True)          # GLB bytes
    vertices = db.Column(db.Integer, nullable=True)
    faces = db.Column(db.Integer, nullable=True)
    dimensions = db.Column(db.JSON, nullable=True)            # {"x":..,"y":..,"z":..} metres

    view_count = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)

    def __repr__(self) -> str:
        return f"<Model3D {self.name} ({self.id})>"

    @property
    def file_size_human(self) -> str:
        size = self.file_size or 0
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @property
    def dimensions_human(self) -> str | None:
        if not self.dimensions:
            return None
        try:
            return " × ".join(f"{float(self.dimensions[a]):.2f} m" for a in ("x", "y", "z"))
        except (KeyError, TypeError, ValueError):
            return None


class AIGenerationJob(db.Model):
    """Tracks a Meshy text/image -> 3D generation.

    No long-lived server thread: the frontend polls /api/ai/jobs/<id> and
    each poll advances the Meshy state machine (text is two-stage:
    preview -> refine). Gunicorn multi-worker safe.
    """

    __tablename__ = "webar_ai_job"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    user_id = db.Column(db.Integer, db.ForeignKey("webar_user.id"), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)        # 'text' | 'image'
    prompt = db.Column(db.Text, nullable=True)

    meshy_preview_id = db.Column(db.String(80), nullable=True)
    meshy_refine_id = db.Column(db.String(80), nullable=True)
    meshy_image_id = db.Column(db.String(80), nullable=True)
    stage = db.Column(db.String(20), nullable=True)        # 'preview' | 'refine' | 'image'

    status = db.Column(db.String(20), nullable=False, default="generating")
    # generating | ready | failed
    progress = db.Column(db.Integer, nullable=False, default=0)
    model_id = db.Column(db.String(36), nullable=True)
    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "kind": self.kind,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "model_id": self.model_id,
            "error": self.error,
        }


class ConversionJob(db.Model):
    """DB-backed conversion queue.

    The upload request stages the source file and inserts a pending row.
    With JOB_QUEUE=true worker.py claims and runs it; otherwise the request
    processes it inline. The frontend polls /api/jobs/<id> in both modes.
    """

    __tablename__ = "webar_job"

    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    user_id = db.Column(db.Integer, db.ForeignKey("webar_user.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="pending", index=True)
    # pending | processing | completed | failed

    payload = db.Column(db.JSON, nullable=True)   # staged path, original name, options
    model_id = db.Column(db.String(36), nullable=True)
    error = db.Column(db.Text, nullable=True)

    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=2)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self) -> dict:
        return {
            "job_id": self.id,
            "status": self.status,
            "model_id": self.model_id,
            "error": self.error,
            "attempts": self.attempts,
        }
