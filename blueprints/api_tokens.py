"""Scoped API tokens and the versioned public API (/api/v1/...): read plus a
programmatic write surface (upload/convert, job status, update, delete)."""

import hashlib
import os
import secrets
import uuid

from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from services.time_utils import datetime
from datetime import timedelta
from models import ApiToken, ConversionJob, ModelAnalyticsEvent, User, UserModel, db
from services import UploadStagingError
from services.org_membership import _organization_membership
from services.plans import effective_storage_quota_mb, plan_allows, plan_limit
from site_settings import setting_int

api_tokens_bp = Blueprint("api_tokens", __name__)

API_TOKEN_SCOPES = {"models:read", "analytics:read", "models:write"}


def api_token_rate_limit_key():
    """Rate-limit key for the /api/v1 endpoints: keyed per API token so one
    integration's traffic can't exhaust another's budget (falls back to the
    caller IP for unauthenticated hits, which the endpoints reject anyway)."""
    from flask_limiter.util import get_remote_address
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return "apitoken:" + hashlib.sha256(header[7:].strip().encode()).hexdigest()
    return get_remote_address()


def _bearer_token(required_scope):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None, (jsonify({"success": False, "error": "Bearer token required"}), 401)
    plaintext = header[7:].strip()
    if not plaintext.startswith("arv_") or len(plaintext) < 24:
        return None, (jsonify({"success": False, "error": "Invalid API token"}), 401)
    digest = hashlib.sha256(plaintext.encode()).hexdigest()
    token = ApiToken.query.filter_by(token_digest=digest).first()
    if not token or not token.is_active:
        return None, (jsonify({"success": False, "error": "Invalid or expired API token"}), 401)
    if not token.has_scope(required_scope):
        return None, (jsonify({"success": False, "error": f"Missing scope: {required_scope}"}), 403)
    token.last_used_at = datetime.utcnow()
    db.session.commit()
    return token, None


@api_tokens_bp.route("/api/tokens", methods=["GET", "POST"])
@login_required
def api_tokens():
    if request.method == "GET":
        tokens = ApiToken.query.filter_by(user_id=current_user.id).order_by(ApiToken.created_at.desc()).all()
        return jsonify({"success": True, "tokens": [{
            "id": token.id, "name": token.name, "prefix": token.token_prefix,
            "scopes": token.scopes.split(','), "organization_id": token.organization_id,
            "created_at": token.created_at.isoformat(),
            "expires_at": token.expires_at.isoformat() if token.expires_at else None,
            "last_used_at": token.last_used_at.isoformat() if token.last_used_at else None,
            "revoked": token.revoked_at is not None,
        } for token in tokens]})
    if not plan_allows(current_user, "api_access"):
        return jsonify({
            "success": False,
            "error": "API access requires a Pro or Business plan.",
        }), 403
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "API token")).strip()[:120]
    scopes = data.get("scopes", ["models:read"])
    if not isinstance(scopes, list) or not scopes or not set(scopes) <= API_TOKEN_SCOPES:
        return jsonify({"success": False, "error": "Invalid scopes"}), 400
    organization_id = data.get("organization_id")
    try:
        organization_id = int(organization_id) if organization_id is not None else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid organization id"}), 400
    if organization_id is not None and not _organization_membership(
        organization_id, {"owner", "admin"}
    ):
        return jsonify({"success": False, "error": "Organization admin role required"}), 403
    expires_in_days = data.get("expires_in_days", 90)
    try:
        expires_in_days = int(expires_in_days) if expires_in_days is not None else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid expiry"}), 400
    if expires_in_days is not None and not 1 <= expires_in_days <= 365:
        return jsonify({"success": False, "error": "Expiry must be 1-365 days"}), 400
    plaintext = "arv_" + secrets.token_urlsafe(32)
    token = ApiToken(
        user_id=current_user.id,
        organization_id=organization_id,
        name=name or "API token",
        token_prefix=plaintext[:12],
        token_digest=hashlib.sha256(plaintext.encode()).hexdigest(),
        scopes=','.join(sorted(set(scopes))),
        expires_at=datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.session.add(token)
    db.session.commit()
    return jsonify({"success": True, "id": token.id, "token": plaintext,
                    "prefix": token.token_prefix, "scopes": token.scopes.split(',')}), 201


@api_tokens_bp.route("/api/tokens/<int:token_id>", methods=["DELETE"])
@login_required
def revoke_api_token(token_id):
    token = ApiToken.query.filter_by(id=token_id, user_id=current_user.id).first_or_404()
    token.revoked_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})


def _token_model_query(token):
    query = UserModel.query.filter(UserModel.deleted_at.is_(None))
    if token.organization_id:
        return query.filter(UserModel.organization_id == token.organization_id)
    return query.filter(UserModel.user_id == token.user_id)


@api_tokens_bp.route("/api/v1/models", methods=["GET"])
def api_v1_models():
    token, error = _bearer_token("models:read")
    if error:
        return error
    limit = min(100, max(1, request.args.get("limit", 50, type=int)))
    models = _token_model_query(token).order_by(UserModel.upload_date.desc()).limit(limit).all()
    return jsonify({"data": [{
        "id": model.id, "name": model.display_name or model.original_filename,
        "file_type": model.file_type, "file_size": model.file_size,
        "visibility": model.visibility, "organization_id": model.organization_id,
        "viewer_url": url_for("viewer.view_model", model_id=model.id, _external=True),
        "validation": model.validation_report,
    } for model in models]})


@api_tokens_bp.route("/api/v1/models/<model_id>", methods=["GET"])
def api_v1_model(model_id):
    token, error = _bearer_token("models:read")
    if error:
        return error
    model = _token_model_query(token).filter(UserModel.id == model_id).first()
    if not model:
        return jsonify({"error": "Model not found"}), 404
    return jsonify({"data": {
        "id": model.id, "name": model.display_name or model.original_filename,
        "description": model.description, "visibility": model.visibility,
        "file_type": model.file_type, "file_size": model.file_size,
        "vertices": model.vertices, "triangles": model.faces,
        "validation": model.validation_report,
        "viewer_url": url_for("viewer.view_model", model_id=model.id, _external=True),
        "embed_url": url_for("viewer.embed_view", model_id=model.id, _external=True),
    }})


@api_tokens_bp.route("/api/v1/models/<model_id>/analytics", methods=["GET"])
def api_v1_model_analytics(model_id):
    token, error = _bearer_token("analytics:read")
    if error:
        return error
    model = _token_model_query(token).filter(UserModel.id == model_id).first()
    if not model:
        return jsonify({"error": "Model not found"}), 404
    totals = dict(
        db.session.query(ModelAnalyticsEvent.event_type, db.func.count(ModelAnalyticsEvent.id))
        .filter(ModelAnalyticsEvent.model_id == model_id)
        .group_by(ModelAnalyticsEvent.event_type).all()
    )
    return jsonify({"data": {"model_id": model_id, "totals": totals}})


def _token_max_upload_mb(user):
    """Smallest positive per-file upload cap across the admin-global setting and
    the token owner's plan (mirrors upload._effective_max_upload_mb, but keyed
    off the token's user since API requests have no logged-in session)."""
    caps = [setting_int("max_upload_mb", 0), plan_limit(user, "max_upload_mb")]
    positive = [cap for cap in caps if cap]
    return min(positive) if positive else 0


def _token_quota_error(token, user, incoming_bytes):
    """Enforce the token owner's model-count and storage caps before staging an
    API upload. Returns an error string or None. Mirrors the session-upload
    guards in blueprints/upload.py, keyed off the token's user."""
    cap = plan_limit(user, "max_models")
    if cap:
        count = (
            db.session.query(db.func.count(UserModel.id))
            .filter(UserModel.user_id == token.user_id, UserModel.deleted_at.is_(None))
            .scalar()
        )
        if count >= cap:
            return f"Model limit reached ({cap}). Delete some models or upgrade your plan."
    global_default_mb = setting_int("storage_quota_mb", int(os.environ.get("STORAGE_QUOTA_MB", 1024)))
    quota_mb = effective_storage_quota_mb(user, global_default_mb)
    if quota_mb:
        used = (
            db.session.query(db.func.coalesce(db.func.sum(UserModel.file_size), 0))
            .filter(UserModel.user_id == token.user_id)
            .scalar()
        )
        if used + incoming_bytes > quota_mb * 1024 * 1024:
            return f"Storage quota exceeded ({quota_mb} MB limit)."
    return None


@api_tokens_bp.route("/api/v1/models", methods=["POST"])
def api_v1_create_model():
    """Programmatic upload+convert. Stages the multipart `file`, enqueues a
    ConversionJob (same pipeline as the UI upload), and returns a job to poll.
    An org-scoped token files the resulting model under its organization."""
    import app as app_module

    token, error = _bearer_token("models:write")
    if error:
        return error
    if "file" not in request.files or not request.files["file"].filename:
        return jsonify({"error": "A multipart 'file' field is required"}), 400
    file = request.files["file"]
    if not app_module.allowed_file(secure_filename(file.filename)):
        return jsonify({"error": "File type not allowed"}), 400
    user = db.session.get(User, token.user_id)
    if user is None:
        return jsonify({"error": "Token owner no longer exists"}), 401
    max_mb = _token_max_upload_mb(user)
    if max_mb and request.content_length and request.content_length > max_mb * 1024 * 1024:
        return jsonify({"error": f"File exceeds the {max_mb} MB upload limit"}), 413
    quota_error = _token_quota_error(token, user, request.content_length or 0)
    if quota_error:
        return jsonify({"error": quota_error}), 413

    job_id = str(uuid.uuid4())
    try:
        staged = app_module.upload_staging.stage(job_id, file)
    except UploadStagingError as exc:
        return jsonify({"error": str(exc)}), 400
    name = str(request.form.get("name", "")).strip()[:255] or None
    payload = {
        **staged,
        "unique_id": job_id,
        "user_id": token.user_id,
        "organization_id": token.organization_id,
        "display_name": name,
    }
    job = ConversionJob(
        id=job_id, job_type="upload", status="pending",
        payload=payload, user_id=token.user_id,
    )
    db.session.add(job)
    db.session.commit()
    if not app_module.JOB_QUEUE_ENABLED:
        app_module._start_local_conversion(job_id)
    return jsonify({"data": {
        "job_id": job_id,
        "model_id": job_id,  # the job id becomes the model id on success
        "status": "pending",
        "status_url": url_for("api_tokens.api_v1_job_status", job_id=job_id, _external=True),
    }}), 202


@api_tokens_bp.route("/api/v1/jobs/<job_id>", methods=["GET"])
def api_v1_job_status(job_id):
    """Poll a conversion job created via the write API."""
    token, error = _bearer_token("models:read")
    if error:
        return error
    job = db.session.get(ConversionJob, job_id)
    if not job or job.user_id != token.user_id:
        return jsonify({"error": "Job not found"}), 404
    payload = job.payload or {}
    data = {
        "job_id": job.id, "status": job.status, "model_id": job.model_id,
        "error": job.error, "progress": payload.get("progress"),
    }
    if job.status == "completed" and job.model_id:
        data["viewer_url"] = url_for("viewer.view_model", model_id=job.model_id, _external=True)
        data["embed_url"] = url_for("viewer.embed_view", model_id=job.model_id, _external=True)
    return jsonify({"data": data})


@api_tokens_bp.route("/api/v1/models/<model_id>", methods=["PATCH"])
def api_v1_update_model(model_id):
    """Update a model's name, description, or visibility."""
    token, error = _bearer_token("models:write")
    if error:
        return error
    model = _token_model_query(token).filter(UserModel.id == model_id).first()
    if not model:
        return jsonify({"error": "Model not found"}), 404
    data = request.get_json(silent=True) or {}
    if "name" in data:
        model.display_name = str(data["name"])[:255] or None
    if "description" in data:
        model.description = str(data["description"])[:2000] or None
    if "visibility" in data:
        if data["visibility"] not in {"private", "unlisted", "public"}:
            return jsonify({"error": "Invalid visibility"}), 400
        model.visibility = data["visibility"]
    db.session.commit()
    return jsonify({"data": {
        "id": model.id, "name": model.display_name,
        "description": model.description, "visibility": model.visibility,
    }})


@api_tokens_bp.route("/api/v1/models/<model_id>", methods=["DELETE"])
def api_v1_delete_model(model_id):
    """Soft-delete a model (moves it to trash, like the UI delete)."""
    token, error = _bearer_token("models:write")
    if error:
        return error
    model = _token_model_query(token).filter(UserModel.id == model_id).first()
    if not model:
        return jsonify({"error": "Model not found"}), 404
    model.deleted_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"data": {"id": model.id, "deleted": True}})
