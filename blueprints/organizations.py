"""Organizations: membership, shared folders, custom domains, and assigning
a model to a team."""

import logging
import re
import secrets

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required
from slugify import slugify

from services.time_utils import datetime
from models import (
    Folder,
    Organization,
    OrganizationDomain,
    OrganizationMember,
    User,
    UserModel,
    db,
)
from services.org_membership import _organization_membership
from services import send_email
from services.org_branding import resolved_org_branding
from services.plans import plan_allows
from services.upgrade import upgrade_hint

organizations_bp = Blueprint("organizations", __name__)
logger = logging.getLogger(__name__)


@organizations_bp.route("/api/organizations", methods=["GET", "POST"])
@login_required
def organizations_api():
    if request.method == "GET":
        memberships = OrganizationMember.query.filter_by(user_id=current_user.id).all()
        return jsonify({"success": True, "organizations": [
            {"id": item.organization.id, "name": item.organization.name,
             "slug": item.organization.slug, "role": item.role}
            for item in memberships
        ]})
    if not plan_allows(current_user, "organizations"):
        return jsonify({
            "success": False,
            "error": "Organizations require a Business plan.",
            "upgrade": upgrade_hint("organizations"),
        }), 403
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:120]
    if not name:
        return jsonify({"success": False, "error": "Organization name is required"}), 400
    base = slugify(name)[:120] or "organization"
    candidate = base
    while Organization.query.filter_by(slug=candidate).first():
        candidate = f"{base[:110]}-{secrets.token_hex(4)}"
    organization = Organization(name=name, slug=candidate, created_by=current_user.id)
    db.session.add(organization)
    db.session.flush()
    db.session.add(OrganizationMember(
        organization_id=organization.id, user_id=current_user.id, role="owner"
    ))
    db.session.commit()
    return jsonify({"success": True, "organization": {
        "id": organization.id, "name": organization.name, "slug": organization.slug,
        "role": "owner",
    }}), 201


@organizations_bp.route("/api/organizations/<int:organization_id>/members", methods=["GET", "POST"])
@login_required
def organization_members_api(organization_id):
    membership = _organization_membership(organization_id)
    if not membership:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    if request.method == "GET":
        members = OrganizationMember.query.filter_by(organization_id=organization_id).all()
        return jsonify({"success": True, "members": [
            {"user_id": item.user_id, "username": item.user.username,
             "email": item.user.email, "role": item.role}
            for item in members
        ]})
    if membership.role not in {"owner", "admin"}:
        return jsonify({"success": False, "error": "Admin role required"}), 403
    data = request.get_json(silent=True) or {}
    role = data.get("role", "viewer")
    if role not in {"admin", "editor", "viewer"}:
        return jsonify({"success": False, "error": "Invalid role"}), 400
    user = User.query.filter(db.func.lower(User.email) == str(data.get("email", "")).strip().lower()).first()
    if not user:
        return jsonify({"success": False, "error": "Registered user not found"}), 404
    existing = OrganizationMember.query.filter_by(
        organization_id=organization_id, user_id=user.id
    ).first()
    is_new_member = existing is None
    if existing:
        if existing.role == "owner":
            return jsonify({"success": False, "error": "Owner membership cannot be changed"}), 409
        existing.role = role
    else:
        db.session.add(OrganizationMember(
            organization_id=organization_id, user_id=user.id, role=role
        ))
    db.session.commit()
    if is_new_member and user.email:
        organization = db.session.get(Organization, organization_id)
        send_email(
            user.email, "You've been added to an organization",
            f"You were added to {organization.name if organization else 'an organization'} "
            f"as {role}.",
        )
    return jsonify({"success": True, "user_id": user.id, "role": role}), 201


@organizations_bp.route("/api/organizations/<int:organization_id>/members/<int:user_id>", methods=["PATCH", "DELETE"])
@login_required
def organization_member_api(organization_id, user_id):
    actor = _organization_membership(organization_id, {"owner", "admin"})
    if not actor:
        return jsonify({"success": False, "error": "Admin role required"}), 403
    target = OrganizationMember.query.filter_by(
        organization_id=organization_id, user_id=user_id
    ).first_or_404()
    if target.role == "owner":
        return jsonify({"success": False, "error": "Owner membership cannot be changed"}), 409
    if request.method == "DELETE":
        db.session.delete(target)
        db.session.commit()
        return jsonify({"success": True})
    role = (request.get_json(silent=True) or {}).get("role")
    if role not in {"admin", "editor", "viewer"}:
        return jsonify({"success": False, "error": "Invalid role"}), 400
    target.role = role
    db.session.commit()
    return jsonify({"success": True, "role": role})


@organizations_bp.route("/api/organizations/<int:organization_id>/folders", methods=["GET", "POST"])
@login_required
def organization_folders_api(organization_id):
    membership = _organization_membership(organization_id)
    if not membership:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    if request.method == "GET":
        folders = Folder.query.filter_by(organization_id=organization_id).order_by(Folder.name).all()
        return jsonify({"success": True, "folders": [{
            "id": folder.id, "name": folder.name, "slug": folder.slug,
            "parent_id": folder.parent_id,
            "model_count": UserModel.query.filter_by(folder_id=folder.id, deleted_at=None).count(),
        } for folder in folders]})
    if membership.role not in {"owner", "admin", "editor"}:
        return jsonify({"success": False, "error": "Editor role required"}), 403
    data = request.get_json(silent=True) or {}
    name = str(data.get("name", "")).strip()[:100]
    if not name:
        return jsonify({"success": False, "error": "Folder name is required"}), 400
    parent_id = data.get("parent_id")
    if parent_id is not None and not Folder.query.filter_by(
        id=int(parent_id), organization_id=organization_id
    ).first():
        return jsonify({"success": False, "error": "Parent folder not found"}), 404
    if Folder.query.filter_by(
        name=name,
        parent_id=int(parent_id) if parent_id is not None else None,
        organization_id=organization_id,
    ).first():
        return jsonify({"success": False, "error": "A folder with this name already exists"}), 409
    base = slugify(name)[:80] or "folder"
    folder = Folder(
        name=name,
        slug=f"{base}-{secrets.token_hex(4)}",
        user_id=current_user.id,
        organization_id=organization_id,
        parent_id=int(parent_id) if parent_id is not None else None,
    )
    db.session.add(folder)
    db.session.commit()
    return jsonify({"success": True, "folder": {
        "id": folder.id, "name": folder.name, "parent_id": folder.parent_id,
    }}), 201


@organizations_bp.route("/api/organizations/<int:organization_id>/folders/<int:folder_id>", methods=["PATCH", "DELETE"])
@login_required
def organization_folder_api(organization_id, folder_id):
    membership = _organization_membership(organization_id, {"owner", "admin", "editor"})
    if not membership:
        return jsonify({"success": False, "error": "Editor role required"}), 403
    folder = Folder.query.filter_by(id=folder_id, organization_id=organization_id).first_or_404()
    if request.method == "DELETE":
        UserModel.query.filter_by(folder_id=folder.id).update({"folder_id": None})
        for child in Folder.query.filter_by(parent_id=folder.id, organization_id=organization_id).all():
            child.parent_id = folder.parent_id
        db.session.delete(folder)
        db.session.commit()
        return jsonify({"success": True})
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()[:100]
    if not name:
        return jsonify({"success": False, "error": "Folder name is required"}), 400
    folder.name = name
    db.session.commit()
    return jsonify({"success": True, "name": folder.name})


@organizations_bp.route("/api/organizations/<int:organization_id>/folders/<int:folder_id>/models/<model_id>", methods=["PUT", "DELETE"])
@login_required
def organization_folder_model_api(organization_id, folder_id, model_id):
    if not _organization_membership(organization_id, {"owner", "admin", "editor"}):
        return jsonify({"success": False, "error": "Editor role required"}), 403
    folder = Folder.query.filter_by(id=folder_id, organization_id=organization_id).first_or_404()
    model = UserModel.query.filter_by(id=model_id, organization_id=organization_id, deleted_at=None).first_or_404()
    model.folder_id = folder.id if request.method == "PUT" else None
    db.session.commit()
    return jsonify({"success": True, "folder_id": model.folder_id})


@organizations_bp.route("/api/organizations/<int:organization_id>/domains", methods=["GET", "POST"])
@login_required
def organization_domains_api(organization_id):
    if not _organization_membership(organization_id, {"owner", "admin"}):
        return jsonify({"success": False, "error": "Organization admin role required"}), 403
    if request.method == "GET":
        domains = OrganizationDomain.query.filter_by(organization_id=organization_id).all()
        return jsonify({"success": True, "domains": [{
            "id": domain.id, "hostname": domain.hostname,
            "verified": domain.verified_at is not None,
            "verified_at": domain.verified_at.isoformat() if domain.verified_at else None,
            "dns_record": {
                "type": "TXT", "name": f"_arvision.{domain.hostname}",
                "value": f"arvision-verification={domain.verification_token}",
            },
        } for domain in domains]})
    if not plan_allows(current_user, "custom_domains"):
        return jsonify({
            "success": False,
            "error": "Custom domains require a Business plan.",
            "upgrade": upgrade_hint("custom_domains"),
        }), 403
    raw_hostname = str((request.get_json(silent=True) or {}).get("hostname", "")).strip().lower().rstrip(".")
    try:
        hostname = raw_hostname.encode("idna").decode("ascii")
    except UnicodeError:
        return jsonify({"success": False, "error": "Invalid hostname"}), 400
    if (len(hostname) > 253 or hostname in {"localhost", "127.0.0.1"} or
            not re.fullmatch(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", hostname)):
        return jsonify({"success": False, "error": "A valid public hostname is required"}), 400
    if OrganizationDomain.query.filter_by(hostname=hostname).first():
        return jsonify({"success": False, "error": "Hostname is already registered"}), 409
    domain = OrganizationDomain(
        organization_id=organization_id,
        hostname=hostname,
        verification_token=secrets.token_urlsafe(24),
    )
    db.session.add(domain)
    db.session.commit()
    return jsonify({
        "success": True, "id": domain.id, "hostname": hostname,
        "dns_record": {
            "type": "TXT", "name": f"_arvision.{hostname}",
            "value": f"arvision-verification={domain.verification_token}",
        },
    }), 201


@organizations_bp.route("/api/organizations/<int:organization_id>/domains/<int:domain_id>/verify", methods=["POST"])
@login_required
def verify_organization_domain(organization_id, domain_id):
    if not _organization_membership(organization_id, {"owner", "admin"}):
        return jsonify({"success": False, "error": "Organization admin role required"}), 403
    domain = OrganizationDomain.query.filter_by(
        id=domain_id, organization_id=organization_id
    ).first_or_404()
    import requests as http_requests
    try:
        response = http_requests.get(
            "https://dns.google/resolve",
            params={"name": f"_arvision.{domain.hostname}", "type": "TXT"},
            timeout=10,
        )
        response.raise_for_status()
        answers = response.json().get("Answer", [])
    except Exception as exc:
        logger.warning("Domain DNS verification failed for %s: %s", domain.hostname, exc)
        return jsonify({"success": False, "error": "DNS lookup failed"}), 502
    expected = f"arvision-verification={domain.verification_token}"
    values = [str(answer.get("data", "")).strip('"').replace('" "', '') for answer in answers]
    if expected not in values:
        return jsonify({"success": False, "verified": False,
                        "error": "Verification TXT record was not found"}), 409
    domain.verified_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True, "verified": True, "hostname": domain.hostname})


@organizations_bp.route("/api/organizations/<int:organization_id>/domains/<int:domain_id>", methods=["DELETE"])
@login_required
def delete_organization_domain(organization_id, domain_id):
    if not _organization_membership(organization_id, {"owner", "admin"}):
        return jsonify({"success": False, "error": "Organization admin role required"}), 403
    domain = OrganizationDomain.query.filter_by(
        id=domain_id, organization_id=organization_id
    ).first_or_404()
    db.session.delete(domain)
    db.session.commit()
    return jsonify({"success": True})


@organizations_bp.route("/api/models/<model_id>/organization", methods=["PATCH"])
@login_required
def assign_model_organization(model_id):
    model = UserModel.query.get_or_404(model_id)
    if model.user_id != current_user.id:
        return jsonify({"success": False, "error": "Only the model owner can assign a team"}), 403
    organization_id = (request.get_json(silent=True) or {}).get("organization_id")
    try:
        organization_id = int(organization_id) if organization_id is not None else None
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid organization id"}), 400
    if organization_id is not None and not _organization_membership(
        organization_id, {"owner", "admin"}
    ):
        return jsonify({"success": False, "error": "Organization admin role required"}), 403
    model.organization_id = organization_id
    db.session.commit()
    return jsonify({"success": True, "organization_id": model.organization_id})


@organizations_bp.route("/api/organizations/<int:organization_id>/branding", methods=["GET", "PATCH"])
@login_required
def organization_branding_api(organization_id):
    """Tenant white-label theme for the org's custom-domain gallery. Any member
    can read it; only owner/admin can change it, and only on a plan that
    unlocks white_label."""
    membership = _organization_membership(organization_id)
    if not membership:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    organization = db.session.get(Organization, organization_id)
    if request.method == "GET":
        return jsonify({"success": True, "branding": resolved_org_branding(organization)})
    if membership.role not in {"owner", "admin"}:
        return jsonify({"success": False, "error": "Admin role required"}), 403
    if not plan_allows(current_user, "white_label"):
        return jsonify({
            "success": False,
            "error": "White-label branding requires a Business plan.",
            "upgrade": upgrade_hint("white_label"),
        }), 403
    data = request.get_json(silent=True) or {}
    branding = dict(organization.branding or {})
    if "name" in data:
        branding["name"] = str(data["name"]).strip()[:80] or None
    if "logo_url" in data:
        logo = data["logo_url"]
        if logo and not str(logo).startswith("https://"):
            return jsonify({"success": False, "error": "Logo URL must use HTTPS"}), 400
        branding["logo_url"] = str(logo)[:500] if logo else None
    if "primary_color" in data:
        color = str(data["primary_color"])
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            return jsonify({"success": False, "error": "Invalid primary color"}), 400
        branding["primary_color"] = color
    if "hide_powered_by" in data:
        if not isinstance(data["hide_powered_by"], bool):
            return jsonify({"success": False, "error": "hide_powered_by must be a boolean"}), 400
        branding["hide_powered_by"] = data["hide_powered_by"]
    organization.branding = branding
    db.session.commit()
    return jsonify({"success": True, "branding": resolved_org_branding(organization)})
