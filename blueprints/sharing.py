"""Model share-link creation/revocation and the public /s/<token> redeemer."""

import hashlib
import secrets
from datetime import timedelta

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from services.time_utils import datetime
from models import ModelShareLink, UserModel, db
from services import send_email
from services.plans import plan_allows

sharing_bp = Blueprint("sharing", __name__)


@sharing_bp.route("/api/models/<model_id>/share-links", methods=["POST"])
@login_required
def create_model_share_link(model_id):
    model = UserModel.query.get_or_404(model_id)
    if model.user_id != current_user.id:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    data = request.get_json(silent=True) or {}
    permission = data.get("permission", "view")
    if permission not in {"view", "edit"}:
        return jsonify({"success": False, "error": "Invalid permission"}), 400
    expires_in = data.get("expires_in_hours", 168)
    try:
        expires_in = int(expires_in) if expires_in is not None else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid expiry"}), 400
    if expires_in is not None and not 1 <= expires_in <= 24 * 365:
        return jsonify({"success": False, "error": "Expiry must be between 1 hour and 1 year"}), 400
    token = secrets.token_urlsafe(32)
    password = data.get("password")
    # Password-protected share links are a paid feature; existing links keep
    # working (this only gates creating a new password-protected one).
    if password and not plan_allows(current_user, "password_protected_shares"):
        return jsonify({
            "success": False,
            "error": "Password-protected share links require a Pro or Business plan.",
        }), 403
    link = ModelShareLink(
        model_id=model_id,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
        permission=permission,
        password_hash=generate_password_hash(str(password)) if password else None,
        expires_at=datetime.utcnow() + timedelta(hours=expires_in) if expires_in else None,
    )
    db.session.add(link)
    db.session.commit()
    share_url = url_for("sharing.open_model_share_link", token=token, _external=True)
    if current_user.email:
        send_email(
            current_user.email, "Share link created",
            f"A new {permission} share link was created for your model:\n{share_url}",
        )
    return jsonify({
        "success": True,
        "id": link.id,
        "permission": permission,
        "expires_at": link.expires_at.isoformat() if link.expires_at else None,
        "url": share_url,
    }), 201


@sharing_bp.route("/api/models/<model_id>/share-links/<int:link_id>", methods=["DELETE"])
@login_required
def revoke_model_share_link(model_id, link_id):
    model = UserModel.query.get_or_404(model_id)
    if model.user_id != current_user.id:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    link = ModelShareLink.query.filter_by(id=link_id, model_id=model_id).first_or_404()
    link.revoked_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})


@sharing_bp.route("/s/<token>", methods=["GET", "POST"])
def open_model_share_link(token):
    # Rate-limited in app.py after blueprint registration (limiter is
    # constructed after this module is imported) — see app.py's
    # "app.view_functions['sharing.open_model_share_link'] = ..." line.
    digest = hashlib.sha256(token.encode()).hexdigest()
    link = ModelShareLink.query.filter_by(token_digest=digest).first()
    if not link or not link.is_active or link.model.deleted_at is not None:
        abort(404)
    if link.password_hash:
        password = (request.get_json(silent=True) or {}).get("password") or request.form.get("password")
        if not password or not check_password_hash(link.password_hash, password):
            if request.method == "GET":
                return render_template("share_password.html", token=token), 401
            return jsonify({"success": False, "error": "Invalid password"}), 403
    grants = dict(session.get("model_share_grants", {}))
    grants[link.model_id] = {"link_id": link.id}
    session["model_share_grants"] = grants
    return redirect(url_for("viewer.view_model", model_id=link.model_id))
