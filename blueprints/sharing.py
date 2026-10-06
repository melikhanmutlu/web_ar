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
        from services.upgrade import upgrade_hint
        return jsonify({
            "success": False,
            "error": "Password-protected share links require a Pro or Business plan.",
            "upgrade": upgrade_hint("password_protected_shares"),
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


@sharing_bp.route("/api/models/<model_id>/share-links", methods=["GET"])
@login_required
def list_model_share_links(model_id):
    """Active (non-revoked, non-expired) links. Only the token digest is stored,
    so a link's URL is only ever available in the response that created it."""
    model = UserModel.query.get_or_404(model_id)
    if model.user_id != current_user.id:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    links = (
        ModelShareLink.query.filter_by(model_id=model_id, revoked_at=None)
        .order_by(ModelShareLink.created_at.desc()).all()
    )
    return jsonify({
        "success": True,
        "password_allowed": plan_allows(current_user, "password_protected_shares"),
        "links": [
            {
                "id": link.id,
                "permission": link.permission,
                "expires_at": link.expires_at.isoformat() if link.expires_at else None,
                "has_password": bool(link.password_hash),
                "created_at": link.created_at.isoformat() if link.created_at else None,
            }
            for link in links if link.is_active
        ],
    })


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


def _share_unavailable(status, title, message):
    return render_template("share_unavailable.html", title=title, message=message), status


def _share_password_page(token, link, error=None, status=401):
    owner = link.model.user
    return render_template(
        "share_password.html", token=token, error=error,
        model_name=link.model.display_name or "Shared model",
        owner_name=owner.username if owner else None,
    ), status


@sharing_bp.route("/s/<token>", methods=["GET", "POST"])
def open_model_share_link(token):
    # Rate-limited in app.py after blueprint registration (limiter is
    # constructed after this module is imported) — see app.py's
    # "app.view_functions['sharing.open_model_share_link'] = ..." line.
    digest = hashlib.sha256(token.encode()).hexdigest()
    link = ModelShareLink.query.filter_by(token_digest=digest).first()
    if not link or link.model.deleted_at is not None:
        return _share_unavailable(
            404, "Link not found",
            "This share link doesn't exist or the model is no longer available. "
            "Check that the whole link was copied, or ask the owner for a new one.")
    if not link.is_active:
        if link.revoked_at is not None:
            return _share_unavailable(
                410, "Link revoked", "The owner has turned this share link off. Ask them for a new link.")
        return _share_unavailable(
            410, "Link expired", "This share link has expired. Ask the owner for a new link.")
    if link.password_hash:
        body = request.get_json(silent=True) or {}
        password = body.get("password") or request.form.get("password")
        if not password or not check_password_hash(link.password_hash, password):
            if request.method == "GET":
                return _share_password_page(token, link)
            if request.is_json:
                return jsonify({"success": False, "error": "Invalid password"}), 403
            return _share_password_page(token, link, error="Incorrect password. Please try again.", status=403)
    grants = dict(session.get("model_share_grants", {}))
    grants[link.model_id] = {"link_id": link.id}
    session["model_share_grants"] = grants
    return redirect(url_for("viewer.view_model", model_id=link.model_id))
