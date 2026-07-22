"""Seat-based org member limit (growth F2.5): a new member is refused once the
org hits its owner's plan seat cap (max_org_members)."""

from app import db
from models import Organization, OrganizationMember, User


def _user(username, plan="business", is_admin=False):
    user = User(username=username, email=f"{username}@test.com", plan=plan, is_admin=is_admin)
    user.set_password("testpassword123")
    db.session.add(user)
    db.session.commit()
    return user


def _org_with_owner(owner, name="Acme"):
    org = Organization(name=name, slug=f"{name.lower()}-{owner.id}", created_by=owner.id)
    db.session.add(org)
    db.session.commit()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    db.session.commit()
    return org


def _fill_to(org, n):
    """Add member rows until the org has n members total."""
    have = OrganizationMember.query.filter_by(organization_id=org.id).count()
    for i in range(have, n):
        u = _user(f"seat_{org.id}_{i}", plan="free")
        db.session.add(OrganizationMember(organization_id=org.id, user_id=u.id, role="viewer"))
    db.session.commit()


def test_new_member_blocked_at_seat_cap(client):
    owner = _user("seat_owner", plan="business")  # business seed cap = 10
    org = _org_with_owner(owner)
    _fill_to(org, 10)  # at cap
    invitee = _user("seat_invitee", plan="free")
    client.post("/login", data={"username": "seat_owner", "password": "testpassword123"})

    resp = client.post(f"/api/organizations/{org.id}/members",
                       json={"email": invitee.email, "role": "viewer"})
    assert resp.status_code == 403
    body = resp.get_json()
    assert body["upgrade"]["reason"] == "org_seats"
    assert OrganizationMember.query.filter_by(user_id=invitee.id).count() == 0


def test_member_added_below_cap(client):
    owner = _user("seat_owner2", plan="business")
    org = _org_with_owner(owner)
    _fill_to(org, 3)  # well under 10
    invitee = _user("seat_invitee2", plan="free")
    client.post("/login", data={"username": "seat_owner2", "password": "testpassword123"})

    resp = client.post(f"/api/organizations/{org.id}/members",
                       json={"email": invitee.email, "role": "editor"})
    assert resp.status_code == 201
    assert OrganizationMember.query.filter_by(user_id=invitee.id, organization_id=org.id).count() == 1


def test_role_change_of_existing_member_is_not_seat_gated(client):
    owner = _user("seat_owner3", plan="business")
    org = _org_with_owner(owner)
    _fill_to(org, 10)  # at cap
    # Promote an existing member — no new seat consumed, so it must succeed.
    existing = OrganizationMember.query.filter_by(
        organization_id=org.id, role="viewer"
    ).first()
    member_email = db.session.get(User, existing.user_id).email
    client.post("/login", data={"username": "seat_owner3", "password": "testpassword123"})

    resp = client.post(f"/api/organizations/{org.id}/members",
                       json={"email": member_email, "role": "editor"})
    assert resp.status_code == 201
    assert db.session.get(OrganizationMember, existing.id).role == "editor"
