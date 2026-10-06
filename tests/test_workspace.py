"""Workspace pages (organization UI)."""

from app import db
from models import Organization, OrganizationDomain, OrganizationMember, User
from services.time_utils import datetime


def _user(username, plan="business"):
    user = User(username=username, email=f"{username}@test.com", plan=plan,
                email_verified_at=datetime.utcnow())
    user.set_password("testpassword123")
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


def test_workspace_requires_login(client):
    for url in ("/workspace", "/workspace/1"):
        resp = client.get(url)
        assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_home_lists_my_orgs_and_offers_create_on_business(client):
    owner = _user("ws_owner")
    _org(owner, "Acme")
    _login(client, "ws_owner")
    html = client.get("/workspace").get_data(as_text=True)
    assert "Acme" in html and 'id="createOrgForm"' in html
    assert 'href="/workspace"' in html  # user menu link


def test_home_free_user_sees_upgrade_hint_not_form(client):
    _user("ws_free", plan="free")
    _login(client, "ws_free")
    html = client.get("/workspace").get_data(as_text=True)
    assert 'id="createOrgForm"' not in html
    assert "upgrade_reason=organizations" in html


def test_free_invitee_member_sees_org_read_only(client):
    owner = _user("ws_o2")
    org = _org(owner, "Readonly Co")
    viewer = _user("ws_v2", plan="free")
    _member(org, viewer, "viewer")
    _login(client, "ws_v2")
    assert "Readonly Co" in client.get("/workspace").get_data(as_text=True)
    html = client.get(f"/workspace/{org.id}").get_data(as_text=True)
    for hidden in ('id="inviteForm"', 'id="domainForm"', 'id="brandingForm"', 'id="folderForm"',
                   'data-remove-member="', 'data-member-role="', 'id="transferOwner"'):
        assert hidden not in html
    assert 'id="leaveOrg"' in html and "ws_o2" in html


def test_non_member_gets_404(client):
    owner = _user("ws_o3")
    org = _org(owner)
    _user("ws_x3", plan="free")
    _login(client, "ws_x3")
    assert client.get(f"/workspace/{org.id}").status_code == 404
    assert client.get("/workspace/99999").status_code == 404


def test_editor_can_manage_folders_only(client):
    owner = _user("ws_o4")
    org = _org(owner)
    editor = _user("ws_e4", plan="free")
    _member(org, editor, "editor")
    _login(client, "ws_e4")
    html = client.get(f"/workspace/{org.id}").get_data(as_text=True)
    assert 'id="folderForm"' in html
    assert 'id="inviteForm"' not in html and 'id="domainForm"' not in html


def test_owner_sees_all_sections_and_seat_usage(client):
    owner = _user("ws_o5")
    org = _org(owner)
    _member(org, _user("ws_a5", plan="free"), "admin")
    db.session.add(OrganizationDomain(organization_id=org.id, hostname="ar.example.com",
                                      verification_token="tok123"))
    db.session.commit()
    _login(client, "ws_o5")
    client.post(f"/api/organizations/{org.id}/invites", json={"email": "p@example.com", "role": "viewer"})
    html = client.get(f"/workspace/{org.id}").get_data(as_text=True)
    for present in ('id="inviteForm"', 'id="domainForm"', 'id="brandingForm"', 'id="transferOwner"',
                    "p@example.com", "_arvision.ar.example.com", "arvision-verification=tok123",
                    "data-verify-domain"):
        assert present in html
    assert "3 of 10 seats used (1 pending invite)" in html


def test_downgraded_owner_sees_locked_domains_and_branding(client):
    owner = _user("ws_o6")
    org = _org(owner)
    owner.plan = "free"
    db.session.commit()
    _login(client, "ws_o6")
    html = client.get(f"/workspace/{org.id}").get_data(as_text=True)
    assert 'id="domainForm"' not in html and 'id="brandingForm"' not in html
    assert "upgrade_reason=custom_domains" in html and "upgrade_reason=white_label" in html


def test_org_and_member_names_are_escaped(client):
    owner = _user("ws_o7")
    org = _org(owner, "<script>alert(1)</script>")
    _login(client, "ws_o7")
    for url in ("/workspace", f"/workspace/{org.id}"):
        html = client.get(url).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
