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
