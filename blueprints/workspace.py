"""Workspace pages: the owner/admin-facing UI for organizations (members,
invites, shared folders, custom domains, branding). All mutations go through the
JSON API in blueprints/organizations.py; these routes only render state, using
the same membership/plan helpers as the API."""

from flask import Blueprint, abort, render_template
from flask_login import current_user, login_required

from models import (
    Folder,
    Organization,
    OrganizationDomain,
    OrganizationInvite,
    OrganizationMember,
    UserModel,
    db,
)
from services.org_branding import resolved_org_branding
from services.org_invites import pending_invites_query
from services.org_membership import (
    _organization_membership,
    org_allows,
    org_seat_usage,
)
from services.plans import plan_allows

workspace_bp = Blueprint("workspace", __name__)

_ROLE_ORDER = {"owner": 0, "admin": 1, "editor": 2, "viewer": 3}
_SEAT_DISPLAY_LIMIT = 1_000_000


@workspace_bp.route("/workspace")
@login_required
def workspace_home():
    memberships = (
        OrganizationMember.query.filter_by(user_id=current_user.id)
        .order_by(OrganizationMember.created_at, OrganizationMember.id).all()
    )
    organizations = [{
        "id": m.organization.id,
        "name": m.organization.name,
        "role": m.role,
        "member_count": OrganizationMember.query.filter_by(
            organization_id=m.organization.id).count(),
    } for m in memberships]
    return render_template(
        "workspace.html",
        organizations=organizations,
        can_create=plan_allows(current_user, "organizations"),
    )


@workspace_bp.route("/workspace/<int:organization_id>")
@login_required
def workspace_org(organization_id):
    membership = _organization_membership(organization_id)
    if not membership:
        abort(404)
    organization = db.session.get(Organization, organization_id)
    role = membership.role
    can_manage = role in {"owner", "admin"}
    members = sorted(
        OrganizationMember.query.filter_by(organization_id=organization_id).all(),
        key=lambda m: (_ROLE_ORDER.get(m.role, 9), m.user.username.lower()),
    )
    used, pending, cap = org_seat_usage(organization)
    folders = Folder.query.filter_by(organization_id=organization_id).order_by(Folder.name).all()
    folder_counts = {
        f.id: UserModel.query.filter_by(folder_id=f.id, deleted_at=None).count() for f in folders
    }
    ctx = dict(
        organization=organization,
        role=role,
        can_manage=can_manage,
        can_edit_folders=role in {"owner", "admin", "editor"},
        is_owner=role == "owner",
        members=members,
        seats_used=used + pending,
        seats_pending=pending,
        seats_cap=None if cap >= _SEAT_DISPLAY_LIMIT else cap,
        folders=folders,
        folder_counts=folder_counts,
        branding=resolved_org_branding(organization),
        domains_allowed=org_allows(organization, "custom_domains"),
        white_label_allowed=org_allows(organization, "white_label"),
        invites=[], domains=[],
    )
    if can_manage:
        ctx["invites"] = pending_invites_query(organization_id).order_by(
            OrganizationInvite.id).all()
        ctx["domains"] = OrganizationDomain.query.filter_by(
            organization_id=organization_id).order_by(OrganizationDomain.id).all()
    return render_template("workspace_org.html", **ctx)

