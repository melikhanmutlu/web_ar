"""Organization membership/role lookup, shared by the organizations blueprint
and any other domain that needs to check role-gated org permissions
(e.g. material/AI presets scoped to an organization)."""

from flask_login import current_user

from models import OrganizationMember


def _organization_membership(organization_id, roles=None):
    if not current_user.is_authenticated:
        return None
    membership = OrganizationMember.query.filter_by(
        organization_id=organization_id, user_id=current_user.id
    ).first()
    if roles and (not membership or membership.role not in roles):
        return None
    return membership


def org_billing_user(organization):
    """The user whose plan governs an organization's paid features (seats,
    custom domains, white-label): the org's creator, falling back to its
    oldest owner when the creator is gone. None if neither exists."""
    from models import User, db

    if organization is None:
        return None
    if organization.created_by is not None:
        user = db.session.get(User, organization.created_by)
        if user is not None:
            return user
    owner = (
        OrganizationMember.query.filter_by(organization_id=organization.id, role="owner")
        .order_by(OrganizationMember.created_at, OrganizationMember.id)
        .first()
    )
    return owner.user if owner is not None else None


def org_allows(organization, feature):
    """True when the organization's billing user's plan includes `feature`.
    Used both when changing org settings and when serving them, so a
    downgrade stops paid org features without deleting the data."""
    from services.plans import plan_allows

    billing_user = org_billing_user(organization)
    return billing_user is not None and plan_allows(billing_user, feature)


def reassign_orgs_before_user_delete(user):
    """Keep organizations governed when `user` is about to be deleted.

    For every org the user belongs to: drop their membership; if they were its
    owner/creator and no other owner remains, promote the oldest admin (else
    the oldest member) to owner; if nobody is left, delete the org together
    with its domains. Caller commits. Returns {"promoted": n, "deleted": n}.
    """
    from models import Folder, Organization, OrganizationDomain, UserModel, db

    result = {"promoted": 0, "deleted": 0}
    org_ids = {
        m.organization_id for m in OrganizationMember.query.filter_by(user_id=user.id).all()
    } | {o.id for o in Organization.query.filter_by(created_by=user.id).all()}
    for org_id in sorted(org_ids):
        organization = db.session.get(Organization, org_id)
        if organization is None:
            continue
        OrganizationMember.query.filter_by(organization_id=org_id, user_id=user.id).delete(
            synchronize_session=False
        )
        db.session.flush()
        remaining = (
            OrganizationMember.query.filter_by(organization_id=org_id)
            .order_by(OrganizationMember.created_at, OrganizationMember.id)
            .all()
        )
        if not remaining:
            OrganizationDomain.query.filter_by(organization_id=org_id).delete(
                synchronize_session=False
            )
            UserModel.query.filter_by(organization_id=org_id).update(
                {"organization_id": None}, synchronize_session=False
            )
            Folder.query.filter_by(organization_id=org_id).update(
                {"organization_id": None}, synchronize_session=False
            )
            db.session.expire(organization)
            db.session.delete(organization)
            result["deleted"] += 1
            continue
        owner = next((m for m in remaining if m.role == "owner"), None)
        if owner is None:
            owner = next((m for m in remaining if m.role == "admin"), remaining[0])
            owner.role = "owner"
            result["promoted"] += 1
        if organization.created_by in (None, user.id):
            organization.created_by = owner.user_id
    db.session.flush()
    return result
