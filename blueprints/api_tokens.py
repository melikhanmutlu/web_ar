"""Scoped API tokens and the versioned public read API (/api/v1/...)."""

import hashlib
import secrets

from flask import Blueprint, jsonify, request, url_for
from flask_login import current_user, login_required

from services.time_utils import datetime
from datetime import timedelta
from models import ApiToken, ModelAnalyticsEvent, UserModel, db
from services.org_membership import _organization_membership

api_tokens_bp = Blueprint("api_tokens", __name__)

API_TOKEN_SCOPES = {"models:read", "analytics:read", "models:write"}


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
        "viewer_url": url_for("view_model", model_id=model.id, _external=True),
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
        "viewer_url": url_for("view_model", model_id=model.id, _external=True),
        "embed_url": url_for("embed_view", model_id=model.id, _external=True),
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
