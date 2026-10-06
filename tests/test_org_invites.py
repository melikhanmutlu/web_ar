"""Organization invites, leave and ownership transfer (Faz 6)."""

from datetime import timedelta

import pytest

from app import db
from models import Organization, OrganizationInvite, OrganizationMember, User
from services.org_invites import hash_token
from services.time_utils import datetime


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "blueprints.organizations.send_email",
        lambda to, subject, body: sent.append((to, subject, body)) or True,
    )
    return sent


def _user(username, plan="business", verified=True):
    user = User(username=username, email=f"{username}@test.com", plan=plan)
    user.set_password("testpassword123")
    if verified:
        user.email_verified_at = datetime.utcnow()
    db.session.add(user)
    db.session.commit()
    return user


def _org(owner, name="Acme"):
    org = Organization(name=name, slug=f"{name.lower()}-{owner.id}", created_by=owner.id)
    db.session.add(org)
    db.session.commit()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    db.session.commit()
    return org


def _member(org, user, role):
    db.session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
    db.session.commit()


def _login(client, username):
    client.post("/login", data={"username": username, "password": "testpassword123"})


def _token_from(mails):
    body = mails[-1][2]
    return body.split("/invites/")[1].split()[0]


def _invite(client, org, email, role="editor"):
    return client.post(f"/api/organizations/{org.id}/invites", json={"email": email, "role": role})


# ---- creating invites -------------------------------------------------------

def test_owner_invites_by_email_and_token_is_hashed(client, mails):
    owner = _user("inv_owner")
    org = _org(owner)
    _login(client, "inv_owner")
    resp = _invite(client, org, "Newbie@Example.com", "editor")
    assert resp.status_code == 201
    assert "token" not in resp.get_data(as_text=True)
    assert mails[0][0] == "newbie@example.com"
    token = _token_from(mails)
    invite = OrganizationInvite.query.one()
    assert invite.email == "newbie@example.com" and invite.role == "editor"
    assert invite.token_hash == hash_token(token) and token not in invite.token_hash
    assert invite.invited_by == owner.id
    listing = client.get(f"/api/organizations/{org.id}/invites").get_json()
    assert [i["email"] for i in listing["invites"]] == ["newbie@example.com"]


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_non_admin_cannot_invite_or_list(client, mails, role):
    owner = _user(f"inv_o_{role}")
    org = _org(owner)
    member = _user(f"inv_m_{role}", plan="free")
    _member(org, member, role)
    _login(client, member.username)
    assert _invite(client, org, "x@example.com").status_code == 403
    assert client.get(f"/api/organizations/{org.id}/invites").status_code == 403
    assert OrganizationInvite.query.count() == 0


def test_admin_can_invite_but_not_as_owner(client, mails):
    owner = _user("inv_o2")
    org = _org(owner)
    admin = _user("inv_a2", plan="free")
    _member(org, admin, "admin")
    _login(client, "inv_a2")
    assert _invite(client, org, "a@example.com", "viewer").status_code == 201
    assert _invite(client, org, "b@example.com", "owner").status_code == 400
    assert _invite(client, org, "not-an-email", "viewer").status_code == 400


def test_invite_requires_login(client):
    owner = _user("inv_o3")
    org = _org(owner)
    resp = client.post(f"/api/organizations/{org.id}/invites", json={"email": "a@example.com"})
    assert resp.status_code in (302, 401)


def test_invite_existing_member_conflicts(client, mails):
    owner = _user("inv_o4")
    org = _org(owner)
    member = _user("inv_m4", plan="free")
    _member(org, member, "viewer")
    _login(client, "inv_o4")
    assert _invite(client, org, member.email).status_code == 409


def test_reinvite_replaces_pending_invite(client, mails):
    owner = _user("inv_o5")
    org = _org(owner)
    _login(client, "inv_o5")
    _invite(client, org, "r@example.com")
    first = _token_from(mails)
    _invite(client, org, "r@example.com", "viewer")
    assert OrganizationInvite.query.count() == 1
    assert OrganizationInvite.query.one().role == "viewer"
    assert OrganizationInvite.query.filter_by(token_hash=hash_token(first)).count() == 0


def test_invite_email_failure_does_not_break(client, monkeypatch):
    monkeypatch.setattr("blueprints.organizations.send_email", lambda *a, **k: False)
    owner = _user("inv_o6")
    org = _org(owner)
    _login(client, "inv_o6")
    resp = _invite(client, org, "n@example.com")
    assert resp.status_code == 201 and resp.get_json()["email_sent"] is False


# ---- seats ------------------------------------------------------------------

def test_pending_invites_hold_seats(client, mails):
    owner = _user("seat_o")  # business cap = 10
    org = _org(owner)
    for i in range(8):
        _member(org, _user(f"seat_m{i}", plan="free"), "viewer")
    _login(client, "seat_o")
    assert _invite(client, org, "p1@example.com").status_code == 201   # 10th seat
    over = _invite(client, org, "p2@example.com")
    assert over.status_code == 403 and over.get_json()["upgrade"]["reason"] == "org_seats"
    # the same address can be re-invited without a second seat
    assert _invite(client, org, "p1@example.com").status_code == 201
    # a direct add also sees the pending invite
    other = _user("seat_x", plan="free")
    resp = client.post(f"/api/organizations/{org.id}/members",
                       json={"email": other.email, "role": "viewer"})
    assert resp.status_code == 403


def test_expired_invite_frees_its_seat(client, mails):
    owner = _user("seat_o2")
    org = _org(owner)
    for i in range(8):
        _member(org, _user(f"seat2_m{i}", plan="free"), "viewer")
    _login(client, "seat_o2")
    _invite(client, org, "p1@example.com")
    OrganizationInvite.query.update({"expires_at": datetime.utcnow() - timedelta(minutes=1)})
    db.session.commit()
    assert _invite(client, org, "p2@example.com").status_code == 201


def test_lapsed_owner_cannot_invite(client, mails):
    owner = _user("seat_o3")
    org = _org(owner)
    owner.plan = "free"
    db.session.commit()
    _login(client, "seat_o3")
    resp = _invite(client, org, "p@example.com")
    assert resp.status_code == 403 and resp.get_json()["upgrade"]["reason"] == "org_seats"


def test_direct_add_clears_matching_pending_invite(client, mails):
    owner = _user("seat_o4")
    org = _org(owner)
    invitee = _user("seat_i4", plan="free")
    _login(client, "seat_o4")
    _invite(client, org, invitee.email)
    resp = client.post(f"/api/organizations/{org.id}/members",
                       json={"email": invitee.email, "role": "viewer"})
    assert resp.status_code == 201
    assert OrganizationInvite.query.count() == 0


# ---- accepting --------------------------------------------------------------

def _send_invite(client, owner_name, org, email, role="editor", mails=None):
    _login(client, owner_name)
    assert _invite(client, org, email, role).status_code == 201
    token = _token_from(mails)
    client.post("/logout")
    return token


def test_accept_adds_member_with_role_and_is_single_use(client, mails):
    owner = _user("acc_o")
    org = _org(owner)
    invitee = _user("acc_i", plan="free")
    token = _send_invite(client, "acc_o", org, invitee.email, "editor", mails)
    _login(client, "acc_i")
    resp = client.post(f"/api/invites/{token}/accept")
    assert resp.status_code == 200
    member = OrganizationMember.query.filter_by(organization_id=org.id, user_id=invitee.id).one()
    assert member.role == "editor"
    assert OrganizationInvite.query.one().accepted_at is not None
    again = client.post(f"/api/invites/{token}/accept")
    assert again.status_code == 410
    assert OrganizationMember.query.filter_by(user_id=invitee.id).count() == 1


def test_accept_rejects_other_email(client, mails):
    owner = _user("acc_o2")
    org = _org(owner)
    token = _send_invite(client, "acc_o2", org, "someone@example.com", mails=mails)
    stranger = _user("acc_s2", plan="free")
    _login(client, stranger.username)
    resp = client.post(f"/api/invites/{token}/accept")
    assert resp.status_code == 403
    assert OrganizationMember.query.filter_by(user_id=stranger.id).count() == 0
    assert OrganizationInvite.query.one().accepted_at is None


def test_accept_requires_verified_email(client, mails):
    owner = _user("acc_o3")
    org = _org(owner)
    invitee = _user("acc_i3", plan="free", verified=False)
    token = _send_invite(client, "acc_o3", org, invitee.email, mails=mails)
    _login(client, "acc_i3")
    assert client.post(f"/api/invites/{token}/accept").status_code == 403
    assert OrganizationMember.query.filter_by(user_id=invitee.id).count() == 0


def test_accept_expired_invite(client, mails):
    owner = _user("acc_o4")
    org = _org(owner)
    invitee = _user("acc_i4", plan="free")
    token = _send_invite(client, "acc_o4", org, invitee.email, mails=mails)
    OrganizationInvite.query.update({"expires_at": datetime.utcnow() - timedelta(minutes=1)})
    db.session.commit()
    _login(client, "acc_i4")
    assert client.post(f"/api/invites/{token}/accept").status_code == 410
    assert OrganizationMember.query.filter_by(user_id=invitee.id).count() == 0


def test_accept_unknown_token_and_anonymous(client, mails):
    assert client.post("/api/invites/nope/accept").status_code in (302, 401)
    _user("acc_i5", plan="free")
    _login(client, "acc_i5")
    assert client.post("/api/invites/nope/accept").status_code == 404


def test_accept_blocked_when_org_filled_meanwhile(client, mails):
    owner = _user("acc_o6")
    org = _org(owner)
    invitee = _user("acc_i6", plan="free")
    token = _send_invite(client, "acc_o6", org, invitee.email, mails=mails)
    for i in range(9):  # bypass the API: 1 owner + 9 = 10 seats, plus the pending one
        _member(org, _user(f"acc6_m{i}", plan="free"), "viewer")
    _login(client, "acc_i6")
    resp = client.post(f"/api/invites/{token}/accept")
    assert resp.status_code == 403
    assert OrganizationInvite.query.one().accepted_at is None


def test_accept_when_already_member_keeps_role(client, mails):
    owner = _user("acc_o7")
    org = _org(owner)
    invitee = _user("acc_i7", plan="free")
    token = _send_invite(client, "acc_o7", org, invitee.email, "viewer", mails)
    _member(org, invitee, "admin")
    _login(client, "acc_i7")
    assert client.post(f"/api/invites/{token}/accept").status_code == 200
    assert OrganizationMember.query.filter_by(user_id=invitee.id).one().role == "admin"


def test_revoked_invite_cannot_be_accepted(client, mails):
    owner = _user("rev_o")
    org = _org(owner)
    invitee = _user("rev_i", plan="free")
    token = _send_invite(client, "rev_o", org, invitee.email, mails=mails)
    _login(client, "rev_o")
    invite = OrganizationInvite.query.one()
    assert client.delete(f"/api/organizations/{org.id}/invites/{invite.id}").status_code == 200
    client.post("/logout")
    _login(client, "rev_i")
    assert client.post(f"/api/invites/{token}/accept").status_code == 404


def test_revoke_requires_admin_and_matching_org(client, mails):
    owner = _user("rev_o2")
    org = _org(owner)
    other_owner = _user("rev_o3")
    other_org = _org(other_owner, "Other")
    viewer = _user("rev_v2", plan="free")
    _member(org, viewer, "viewer")
    _login(client, "rev_o2")
    _invite(client, org, "z@example.com")
    invite = OrganizationInvite.query.one()
    client.post("/logout")
    _login(client, "rev_v2")
    assert client.delete(f"/api/organizations/{org.id}/invites/{invite.id}").status_code == 403
    client.post("/logout")
    _login(client, "rev_o3")
    # an admin of another org cannot revoke through their own org id either
    assert client.delete(f"/api/organizations/{other_org.id}/invites/{invite.id}").status_code == 404
    assert client.delete(f"/api/organizations/{org.id}/invites/{invite.id}").status_code == 403
    assert OrganizationInvite.query.count() == 1


def test_invite_page_states(client, mails):
    owner = _user("pg_o")
    org = _org(owner, "Pagecorp")
    invitee = _user("pg_i", plan="free")
    token = _send_invite(client, "pg_o", org, invitee.email, mails=mails)
    anon = client.get(f"/invites/{token}").get_data(as_text=True)
    assert "Join Pagecorp" in anon and "Sign in" in anon and f"next=/invites/{token}" in anon.replace("%2F", "/")
    _login(client, "pg_i")
    page = client.get(f"/invites/{token}").get_data(as_text=True)
    assert 'id="acceptInvite"' in page
    assert "Invitation not found" in client.get("/invites/bogus").get_data(as_text=True)
    client.post(f"/api/invites/{token}/accept")
    assert "already used" in client.get(f"/invites/{token}").get_data(as_text=True)


def test_invite_page_wrong_account(client, mails):
    owner = _user("pg_o2")
    org = _org(owner)
    token = _send_invite(client, "pg_o2", org, "target@example.com", mails=mails)
    _user("pg_x", plan="free")
    _login(client, "pg_x")
    page = client.get(f"/invites/{token}").get_data(as_text=True)
    assert 'id="acceptInvite"' not in page and "target@example.com" in page


# ---- leave ------------------------------------------------------------------

def test_member_can_leave(client):
    owner = _user("lv_o")
    org = _org(owner)
    member = _user("lv_m", plan="free")
    _member(org, member, "editor")
    _login(client, "lv_m")
    assert client.post(f"/api/organizations/{org.id}/leave").status_code == 200
    assert OrganizationMember.query.filter_by(user_id=member.id).count() == 0


def test_non_member_cannot_leave(client):
    owner = _user("lv_o2")
    org = _org(owner)
    _user("lv_x", plan="free")
    _login(client, "lv_x")
    assert client.post(f"/api/organizations/{org.id}/leave").status_code == 403


def test_last_owner_cannot_leave(client):
    owner = _user("lv_o3")
    org = _org(owner)
    _member(org, _user("lv_a3", plan="free"), "admin")
    _login(client, "lv_o3")
    resp = client.post(f"/api/organizations/{org.id}/leave")
    assert resp.status_code == 409
    assert OrganizationMember.query.filter_by(user_id=owner.id).count() == 1


def test_co_owner_leaving_moves_billing_user(client):
    owner = _user("lv_o4")
    org = _org(owner)
    second = _user("lv_s4")
    _member(org, second, "owner")
    _login(client, "lv_o4")
    assert client.post(f"/api/organizations/{org.id}/leave").status_code == 200
    assert db.session.get(Organization, org.id).created_by == second.id


# ---- ownership transfer -----------------------------------------------------

def test_owner_transfers_ownership(client):
    owner = _user("tr_o")
    org = _org(owner)
    admin = _user("tr_a")
    _member(org, admin, "admin")
    _login(client, "tr_o")
    resp = client.post(f"/api/organizations/{org.id}/transfer", json={"user_id": admin.id})
    assert resp.status_code == 200
    roles = {m.user_id: m.role for m in OrganizationMember.query.filter_by(organization_id=org.id)}
    assert roles == {owner.id: "admin", admin.id: "owner"}
    assert db.session.get(Organization, org.id).created_by == admin.id
    from services.org_membership import org_billing_user
    assert org_billing_user(db.session.get(Organization, org.id)).id == admin.id
    # the former owner can now leave
    assert client.post(f"/api/organizations/{org.id}/leave").status_code == 200


def test_transfer_rules(client):
    owner = _user("tr_o2")
    org = _org(owner)
    admin = _user("tr_a2")
    viewer = _user("tr_v2", plan="free")
    outsider = _user("tr_x2")
    _member(org, admin, "admin")
    _member(org, viewer, "viewer")
    # only the owner can transfer
    _login(client, "tr_a2")
    assert client.post(f"/api/organizations/{org.id}/transfer", json={"user_id": admin.id}).status_code == 403
    client.post("/logout")
    _login(client, "tr_o2")
    url = f"/api/organizations/{org.id}/transfer"
    assert client.post(url, json={"user_id": owner.id}).status_code == 400
    assert client.post(url, json={"user_id": "x"}).status_code == 400
    assert client.post(url, json={"user_id": outsider.id}).status_code == 404
    # target whose plan cannot carry organizations
    blocked = client.post(url, json={"user_id": viewer.id})
    assert blocked.status_code == 409 and blocked.get_json()["upgrade"]["reason"] == "organizations"
    roles = {m.user_id: m.role for m in OrganizationMember.query.filter_by(organization_id=org.id)}
    assert roles[owner.id] == "owner" and db.session.get(Organization, org.id).created_by == owner.id
