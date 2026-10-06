"""Organizations: membership, shared folders, custom domains, and assigning
a model to a team."""

import logging
import re
import secrets

from flask import Blueprint, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from slugify import slugify

from services.time_utils import datetime
from services.request_json import json_dict
from models import (
    Folder,
    Organization,
    OrganizationDomain,
    OrganizationInvite,
    OrganizationMember,
    User,
    UserModel,
    db,
)
from services.org_invites import (
    INVITE_ROLES, create_invite, find_invite, invite_state, pending_invites_query,
)
from services.org_membership import (
    _organization_membership, org_allows, org_billing_user, org_seat_usage,
)
from services import send_email
from services.org_branding import resolved_org_branding
from services.email_verification import is_verified
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
    data = json_dict()
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


def _check_org_seat_limit(organization_id, exclude_email=None):
    """Block a new member/invite when members + pending invites reach the org
    owner's plan seat cap (max_org_members). Governed by the org creator's plan
    -- they're who pays. `exclude_email` skips that address's own pending invite
    (re-inviting it, or accepting it, does not need a second seat).
    Returns a response tuple or None."""
    organization = db.session.get(Organization, organization_id)
    if organization is None:
        return None
    # cap floors to 0 (not None): a plan with no seat entitlement -- Free, or a
    # Business owner who lapsed/downgraded -- must NOT fall through to
    # "unlimited". 0 means no new members may be added; existing members stay.
    members, pending, cap = org_seat_usage(organization)
    if exclude_email:
        pending -= pending_invites_query(organization_id).filter(
            db.func.lower(OrganizationInvite.email) == exclude_email.lower()
        ).count()
    if members + pending >= cap:
        return jsonify({
            "success": False,
            "error": f"Seat limit reached ({cap}). The organization owner's plan has to be "
                     "upgraded to add more members.",
            "upgrade": upgrade_hint("org_seats"),
        }), 403
    return None


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
    data = json_dict()
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
        seat_guard = _check_org_seat_limit(organization_id, exclude_email=user.email)
        if seat_guard is not None:
            return seat_guard
        pending_invites_query(organization_id).filter(
            db.func.lower(OrganizationInvite.email) == (user.email or "").lower()
        ).delete(synchronize_session=False)
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
    role = (json_dict()).get("role")
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
    data = json_dict()
    name = str(data.get("name", "")).strip()[:100]
    if not name:
        return jsonify({"success": False, "error": "Folder name is required"}), 400
    parent_id = data.get("parent_id")
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "Invalid parent folder id"}), 400
    if parent_id is not None and not Folder.query.filter_by(
        id=parent_id, organization_id=organization_id
    ).first():
        return jsonify({"success": False, "error": "Parent folder not found"}), 404
    if Folder.query.filter_by(
        name=name,
        parent_id=parent_id,
        organization_id=organization_id,
    ).first():
        return jsonify({"success": False, "error": "A folder with this name already exists"}), 409
    base = slugify(name)[:80] or "folder"
    folder = Folder(
        name=name,
        slug=f"{base}-{secrets.token_hex(4)}",
        user_id=current_user.id,
        organization_id=organization_id,
        parent_id=parent_id,
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
    name = str((json_dict()).get("name", "")).strip()[:100]
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
    if not org_allows(db.session.get(Organization, organization_id), "custom_domains"):
        return jsonify({
            "success": False,
            "error": "Custom domains require a Business plan.",
            "upgrade": upgrade_hint("custom_domains"),
        }), 403
    raw_hostname = str((json_dict()).get("hostname", "")).strip().lower().rstrip(".")
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
    organization_id = (json_dict()).get("organization_id")
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
    if not org_allows(organization, "white_label"):
        return jsonify({
            "success": False,
            "error": "White-label branding requires a Business plan.",
            "upgrade": upgrade_hint("white_label"),
        }), 403
    data = json_dict()
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


_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _invite_json(invite):
    return {
        "id": invite.id, "email": invite.email, "role": invite.role,
        "expires_at": invite.expires_at.isoformat(),
    }


@organizations_bp.route("/api/organizations/<int:organization_id>/invites", methods=["GET", "POST"])
@login_required
def organization_invites_api(organization_id):
    if not _organization_membership(organization_id, {"owner", "admin"}):
        return jsonify({"success": False, "error": "Admin role required"}), 403
    if request.method == "GET":
        invites = pending_invites_query(organization_id).order_by(OrganizationInvite.id).all()
        return jsonify({"success": True, "invites": [_invite_json(i) for i in invites]})
    data = json_dict()
    email = str(data.get("email", "")).strip().lower()
    role = data.get("role", "viewer")
    if len(email) > 255 or not _EMAIL_RE.fullmatch(email):
        return jsonify({"success": False, "error": "A valid email address is required"}), 400
    if role not in INVITE_ROLES:
        return jsonify({"success": False, "error": "Invalid role"}), 400
    already = (
        OrganizationMember.query.join(User, User.id == OrganizationMember.user_id)
        .filter(OrganizationMember.organization_id == organization_id,
                db.func.lower(User.email) == email).first()
    )
    if already:
        return jsonify({"success": False, "error": "This person is already a member"}), 409
    seat_guard = _check_org_seat_limit(organization_id, exclude_email=email)
    if seat_guard is not None:
        return seat_guard
    organization = db.session.get(Organization, organization_id)
    invite, token = create_invite(organization, email, role, current_user.id)
    db.session.commit()
    link = url_for("organizations.invite_page", token=token, _external=True)
    sent = send_email(
        email, f"You're invited to join {organization.name} on ARVision",
        f"{current_user.username} invited you to join {organization.name} as {role}.\n\n"
        f"Accept the invitation (valid for 7 days):\n{link}\n\n"
        "Sign in or create an account with this email address to accept it.",
    )
    if not sent:
        # SMTP not configured/failed: the admin can still relay the link.
        logger.info("Organization invite for %s (org %s): %s", email, organization_id, link)
    return jsonify({"success": True, "invite": _invite_json(invite), "email_sent": bool(sent)}), 201


@organizations_bp.route("/api/organizations/<int:organization_id>/invites/<int:invite_id>", methods=["DELETE"])
@login_required
def revoke_organization_invite(organization_id, invite_id):
    if not _organization_membership(organization_id, {"owner", "admin"}):
        return jsonify({"success": False, "error": "Admin role required"}), 403
    invite = OrganizationInvite.query.filter_by(
        id=invite_id, organization_id=organization_id, accepted_at=None
    ).first_or_404()
    db.session.delete(invite)
    db.session.commit()
    return jsonify({"success": True})


@organizations_bp.route("/invites/<token>", methods=["GET"])
def invite_page(token):
    """Landing page for an emailed invite link. Anonymous visitors are asked to
    sign in / register (with `next` back here); accepting itself is a POST."""
    invite = find_invite(token)
    state = invite_state(invite) if invite else "invalid"
    organization = invite.organization if invite and state == "pending" else None
    matches = bool(
        organization and current_user.is_authenticated and current_user.email
        and current_user.email.lower() == invite.email
    )
    return render_template(
        "invite_accept.html", token=token, invite=invite, state=state,
        organization=organization, matches=matches,
        verified=bool(current_user.is_authenticated and is_verified(current_user)),
    )


@organizations_bp.route("/api/invites/<token>/accept", methods=["POST"])
@login_required
def accept_organization_invite(token):
    invite = find_invite(token)
    if invite is None:
        return jsonify({"success": False, "error": "Invitation not found"}), 404
    state = invite_state(invite)
    if state != "pending":
        return jsonify({"success": False, "error": f"This invitation is {state}"}), 410
    if not current_user.email or current_user.email.lower() != invite.email:
        return jsonify({"success": False,
                        "error": "This invitation was sent to a different email address"}), 403
    if not is_verified(current_user):
        return jsonify({"success": False,
                        "error": "Verify your email address before accepting an invitation"}), 403
    organization_id = invite.organization_id
    existing = OrganizationMember.query.filter_by(
        organization_id=organization_id, user_id=current_user.id
    ).first()
    if existing is None:
        seat_guard = _check_org_seat_limit(organization_id, exclude_email=invite.email)
        if seat_guard is not None:
            return seat_guard
    # Single use: only the request that flips accepted_at proceeds.
    claimed = OrganizationInvite.query.filter_by(id=invite.id, accepted_at=None).update(
        {"accepted_at": datetime.utcnow()}, synchronize_session=False
    )
    if not claimed:
        db.session.rollback()
        return jsonify({"success": False, "error": "This invitation is accepted"}), 410
    if existing is None:
        db.session.add(OrganizationMember(
            organization_id=organization_id, user_id=current_user.id, role=invite.role
        ))
    db.session.commit()
    return jsonify({"success": True, "organization_id": organization_id}), 200


@organizations_bp.route("/api/organizations/<int:organization_id>/leave", methods=["POST"])
@login_required
def leave_organization(organization_id):
    membership = _organization_membership(organization_id)
    if not membership:
        return jsonify({"success": False, "error": "Forbidden"}), 403
    organization = db.session.get(Organization, organization_id)
    if membership.role == "owner":
        other_owner = OrganizationMember.query.filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.role == "owner",
            OrganizationMember.user_id != current_user.id,
        ).order_by(OrganizationMember.created_at, OrganizationMember.id).first()
        if other_owner is None:
            return jsonify({"success": False,
                            "error": "Transfer ownership to another member before leaving"}), 409
        if organization.created_by == current_user.id:
            organization.created_by = other_owner.user_id
    db.session.delete(membership)
    db.session.commit()
    return jsonify({"success": True})


@organizations_bp.route("/api/organizations/<int:organization_id>/transfer", methods=["POST"])
@login_required
def transfer_organization_ownership(organization_id):
    actor = _organization_membership(organization_id, {"owner"})
    if not actor:
        return jsonify({"success": False, "error": "Owner role required"}), 403
    try:
        target_id = int((json_dict()).get("user_id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "A member user_id is required"}), 400
    if target_id == current_user.id:
        return jsonify({"success": False, "error": "You already own this organization"}), 400
    target = OrganizationMember.query.filter_by(
        organization_id=organization_id, user_id=target_id
    ).first()
    if target is None:
        return jsonify({"success": False, "error": "Target must be an existing member"}), 404
    # created_by is the billing user (plan gates, seats): the new owner's plan
    # must be able to carry organizations or the team would silently lock up.
    if not plan_allows(db.session.get(User, target_id), "organizations"):
        return jsonify({
            "success": False,
            "error": "The new owner's plan does not include organizations.",
            "upgrade": upgrade_hint("organizations"),
        }), 409
    organization = db.session.get(Organization, organization_id)
    target.role = "owner"
    actor.role = "admin"
    organization.created_by = target_id
    db.session.commit()
    return jsonify({"success": True, "owner_id": target_id})
