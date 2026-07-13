"""Scoped API tokens and the versioned public read API (/api/v1/...)."""

import hashlib
import os
import secrets

from flask import Blueprint, current_app, jsonify, request, send_file, url_for
from flask_login import current_user, login_required

from services.time_utils import datetime
from datetime import timedelta
from models import ApiToken, Folder, ModelAnalyticsEvent, User, UserModel, db
from services.org_membership import _organization_membership
from services.plans import plan_allows

api_tokens_bp = Blueprint("api_tokens", __name__)

API_TOKEN_SCOPES = {"models:read", "analytics:read", "models:write"}

# Scopes granted to a token minted by the mobile app's own login/register
# (blueprints/auth.py's /api/v1/auth/* routes) -- full read+write over the
# user's own models, unlike a self-serve developer token (which defaults to
# read-only and is scoped by whatever the user explicitly requests).
MOBILE_TOKEN_SCOPES = ["models:read", "models:write"]


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


def _bearer_user(required_scope):
    """Like _bearer_token, but resolves the token's owning User row instead
    of the ApiToken itself -- for routes that need to pass an explicit
    `user=` into helpers written around Flask-Login's current_user (e.g.
    blueprints/upload.py's chunked-upload internals, which read
    user.is_authenticated/user.id)."""
    token, error = _bearer_token(required_scope)
    if error:
        return None, error
    user = db.session.get(User, token.user_id)
    if user is None or not user.is_active:
        return None, (jsonify({"success": False, "error": "Invalid or expired API token"}), 401)
    return user, None


def _issue_api_token(user, *, name, scopes, organization_id=None, expires_in_days=90):
    """Mint and persist a new ApiToken for `user`. Callers are responsible for
    validating name/scopes/organization_id/expires_in_days themselves -- this
    does no input validation, so it's safe to call with fixed, code-controlled
    values (e.g. the mobile login/register routes) as well as from the
    user-submitted /api/tokens form below."""
    plaintext = "arv_" + secrets.token_urlsafe(32)
    token = ApiToken(
        user_id=user.id,
        organization_id=organization_id,
        name=name or "API token",
        token_prefix=plaintext[:12],
        token_digest=hashlib.sha256(plaintext.encode()).hexdigest(),
        scopes=','.join(sorted(set(scopes))),
        expires_at=datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None,
    )
    db.session.add(token)
    db.session.commit()
    return {"id": token.id, "token": plaintext, "prefix": token.token_prefix,
            "scopes": token.scopes.split(',')}


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
    issued = _issue_api_token(
        current_user, name=name, scopes=scopes,
        organization_id=organization_id, expires_in_days=expires_in_days,
    )
    return jsonify({"success": True, **issued}), 201


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


def _token_folder_query(token):
    if token.organization_id:
        return Folder.query.filter(Folder.organization_id == token.organization_id)
    return Folder.query.filter(Folder.user_id == token.user_id)


@api_tokens_bp.route("/api/v1/folders", methods=["GET"])
def api_v1_folders():
    token, error = _bearer_token("models:read")
    if error:
        return error
    query = _token_folder_query(token)
    parent_id = request.args.get("parent_id")
    if parent_id:
        try:
            query = query.filter(Folder.parent_id == int(parent_id))
        except ValueError:
            return jsonify({"error": "Invalid parent_id"}), 400
    else:
        query = query.filter(Folder.parent_id.is_(None))
    folders = query.order_by(Folder.name).all()
    return jsonify({"data": [{
        "id": folder.id, "name": folder.name, "parent_id": folder.parent_id,
        "model_count": folder.model_count,
    } for folder in folders]})


@api_tokens_bp.route("/api/v1/models", methods=["GET"])
def api_v1_models():
    token, error = _bearer_token("models:read")
    if error:
        return error
    limit = min(100, max(1, request.args.get("limit", 50, type=int)))
    query = _token_model_query(token)
    # folder_id omitted -> unfiltered (back-compat); "" -> root only;
    # "<int>" -> that folder.
    if "folder_id" in request.args:
        folder_id = request.args["folder_id"]
        if folder_id == "":
            query = query.filter(UserModel.folder_id.is_(None))
        else:
            try:
                query = query.filter(UserModel.folder_id == int(folder_id))
            except ValueError:
                return jsonify({"error": "Invalid folder_id"}), 400
    models = query.order_by(UserModel.upload_date.desc()).limit(limit).all()
    return jsonify({"data": [{
        "id": model.id, "name": model.display_name or model.original_filename,
        "file_type": model.file_type, "file_size": model.file_size,
        "visibility": model.visibility, "organization_id": model.organization_id,
        "folder_id": model.folder_id,
        "upload_date": model.upload_date.isoformat() if model.upload_date else None,
        "thumbnail_url": url_for("api_tokens.api_v1_model_thumbnail", model_id=model.id, _external=True),
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
    usdz_ready = bool(model.usdz_path and os.path.exists(model.usdz_path))
    return jsonify({"data": {
        "id": model.id, "name": model.display_name or model.original_filename,
        "description": model.description, "visibility": model.visibility,
        "file_type": model.file_type, "file_size": model.file_size,
        "vertices": model.vertices, "triangles": model.faces,
        "validation": model.validation_report,
        "folder_id": model.folder_id,
        "upload_date": model.upload_date.isoformat() if model.upload_date else None,
        "usdz_ready": usdz_ready,
        "thumbnail_url": url_for("api_tokens.api_v1_model_thumbnail", model_id=model.id, _external=True),
        "glb_url": url_for("api_tokens.api_v1_model_glb", model_id=model.id, _external=True),
        "usdz_url": url_for("api_tokens.api_v1_model_usdz", model_id=model.id, _external=True) if usdz_ready else None,
        # Unauthenticated URL (same one templates/view.html hands to
        # <model-viewer>'s src=) -- Android's Scene Viewer app fetches this
        # itself and can't carry the Bearer header the glb_url route above
        # requires, so the mobile app's AR handoff uses this one instead (see
        # mobile/src/ar/launchAR.js). Only meaningful while the model stays
        # at its default "unlisted" visibility, same as the web AR flow.
        "public_glb_url": url_for("model_files.serve_converted_file", unique_id=model.id,
                                  filename="model.glb", _external=True),
        "viewer_url": url_for("viewer.view_model", model_id=model.id, _external=True),
        "embed_url": url_for("viewer.embed_view", model_id=model.id, _external=True),
    }})


def _serve_owned_model_file(token, model_id, path_attr, missing_message):
    """Bearer-auth file download shared by the glb/usdz routes below. The
    native OS AR viewers (iOS Quick Look / Android Scene Viewer) that the
    mobile app hands a downloaded file off to can't carry an Authorization
    header themselves, so the app must download the file first via this
    authenticated route and hand the viewer a local copy (see mobile/src/ar)."""
    model = _token_model_query(token).filter(UserModel.id == model_id).first()
    if not model:
        return jsonify({"error": "Model not found"}), 404
    path = getattr(model, path_attr)
    if not path or not os.path.exists(path):
        return jsonify({"error": missing_message}), 404
    return send_file(path, mimetype="application/octet-stream")


@api_tokens_bp.route("/api/v1/models/<model_id>/glb", methods=["GET"])
def api_v1_model_glb(model_id):
    token, error = _bearer_token("models:read")
    if error:
        return error
    return _serve_owned_model_file(token, model_id, "glb_path", "GLB not available")


@api_tokens_bp.route("/api/v1/models/<model_id>/usdz", methods=["GET"])
def api_v1_model_usdz(model_id):
    token, error = _bearer_token("models:read")
    if error:
        return error
    return _serve_owned_model_file(token, model_id, "usdz_path", "USDZ not available yet")


@api_tokens_bp.route("/api/v1/models/<model_id>/thumbnail", methods=["GET"])
def api_v1_model_thumbnail(model_id):
    """Serves only an already-cached thumbnail; unlike /thumbnail/<id> (see
    blueprints/model_files.py) it deliberately does not reproduce the
    on-the-fly trimesh/SVG generation fallback -- the mobile list view shows
    a generic placeholder for the rare not-yet-cached case instead."""
    token, error = _bearer_token("models:read")
    if error:
        return error
    model = _token_model_query(token).filter(UserModel.id == model_id).first()
    if not model:
        return jsonify({"error": "Model not found"}), 404
    thumb_path = os.path.join(current_app.config["CONVERTED_FOLDER"], model.id, "thumbnail.png")
    if not os.path.exists(thumb_path):
        return jsonify({"error": "Thumbnail not available"}), 404
    return send_file(thumb_path, mimetype="image/png")


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
