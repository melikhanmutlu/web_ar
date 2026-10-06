"""Organization email invitations: create, look up and consume.

Only the SHA-256 of the emailed token is stored. A pending invite (not accepted,
not expired) holds a seat, see services.org_membership.org_seat_usage.
"""

import hashlib
import secrets
from datetime import timedelta

from models import OrganizationInvite, db
from services.time_utils import datetime

INVITE_TTL = timedelta(days=7)
INVITE_ROLES = {"admin", "editor", "viewer"}


def hash_token(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def pending_invites_query(organization_id):
    return OrganizationInvite.query.filter(
        OrganizationInvite.organization_id == organization_id,
        OrganizationInvite.accepted_at.is_(None),
        OrganizationInvite.expires_at > datetime.utcnow(),
    )


def create_invite(organization, email, role, invited_by):
    """Replace any pending invite for `email` and return (invite, raw_token).
    The raw token exists only here (to be emailed); the caller commits."""
    email = str(email).strip().lower()
    pending_invites_query(organization.id).filter(
        db.func.lower(OrganizationInvite.email) == email
    ).delete(synchronize_session=False)
    token = secrets.token_urlsafe(32)
    invite = OrganizationInvite(
        organization_id=organization.id, email=email, role=role,
        token_hash=hash_token(token), invited_by=invited_by,
        expires_at=datetime.utcnow() + INVITE_TTL,
    )
    db.session.add(invite)
    db.session.flush()
    return invite, token


def find_invite(token):
    if not token:
        return None
    return OrganizationInvite.query.filter_by(token_hash=hash_token(token)).first()


def invite_state(invite):
    """'pending', 'accepted' or 'expired'."""
    if invite.accepted_at is not None:
        return "accepted"
    if invite.expires_at <= datetime.utcnow():
        return "expired"
    return "pending"
