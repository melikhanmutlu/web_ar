"""Faz 4 (ADM-07/09/17/21): plan features are enforced at use time, org
features follow the org owner's plan, and deleting an org creator keeps the
org governed."""

import hashlib
import uuid
from datetime import timedelta
from unittest import mock

from models import (
    ApiToken, Organization, OrganizationDomain, OrganizationMember, User,
    WebhookSubscription, db,
)
from services.time_utils import datetime


def _user(name, plan="business", is_admin=False):
    u = User(username=name, email=f"{name}@test.com", plan=plan, is_admin=is_admin)
    u.set_password("testpassword")
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, name):
    client.post("/login", data={"username": name, "password": "testpassword"})


def _token(user):
    plaintext = "arv_" + uuid.uuid4().hex
    db.session.add(ApiToken(user_id=user.id, name="t", token_prefix=plaintext[:12],
                            token_digest=hashlib.sha256(plaintext.encode()).hexdigest(),
                            scopes="models:read"))
    db.session.commit()
    return {"Authorization": f"Bearer {plaintext}"}


# ---- ADM-07 ---------------------------------------------------------------

def test_api_token_stops_working_when_plan_expires(client):
    user = _user("adm07a")
    auth = _token(user)
    assert client.get("/api/v1/models", headers=auth).status_code == 200

    user.plan_expires_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()
    resp = client.get("/api/v1/models", headers=auth)
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["reason"] == "api_access"


def test_locked_developer_page_still_lists_and_revokes_tokens(client):
    user = _user("adm07b", plan="free")
    _token(user)
    _login(client, "adm07b")
    html = client.get("/settings/developer").get_data(as_text=True)
    assert 'id="tokenList"' in html
    token_id = ApiToken.query.filter_by(user_id=user.id).first().id
    assert client.get("/api/tokens").get_json()["tokens"][0]["id"] == token_id
    assert client.delete(f"/api/tokens/{token_id}").status_code == 200


def test_webhook_not_delivered_after_downgrade(client):
    from services.webhooks import dispatch_webhook_event
    user = _user("adm07c")
    db.session.add(WebhookSubscription(user_id=user.id, url="https://example.com/h",
                                       secret="s", event_types="conversion.completed"))
    db.session.commit()
    with mock.patch("services.webhooks._resolve_safe_ips", return_value=["93.184.216.34"]), \
            mock.patch("services.webhooks.requests.post") as post:
        post.return_value.status_code = 200
        dispatch_webhook_event("conversion.completed", user.id, {})
        assert post.call_count == 1
        user.plan = "free"
        db.session.commit()
        dispatch_webhook_event("conversion.completed", user.id, {})
        assert post.call_count == 1


# ---- ADM-17 ---------------------------------------------------------------

def _org(owner, members=()):
    org = Organization(name="Acme", slug=f"acme-{owner.id}", created_by=owner.id)
    db.session.add(org)
    db.session.commit()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"))
    for user, role in members:
        db.session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role))
    db.session.commit()
    return org


def test_custom_domain_uses_org_owners_plan_not_actors(client):
    owner = _user("adm17owner", plan="free")
    admin = _user("adm17admin", plan="business")
    org = _org(owner, [(admin, "admin")])
    _login(client, "adm17admin")
    resp = client.post(f"/api/organizations/{org.id}/domains", json={"hostname": "ar.example.com"})
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["reason"] == "custom_domains"
    resp = client.patch(f"/api/organizations/{org.id}/branding", json={"hide_powered_by": True})
    assert resp.status_code == 403


def test_custom_domain_gallery_and_branding_stop_after_owner_downgrade(client):
    owner = _user("adm17o2", plan="business")
    org = _org(owner)
    org.branding = {"hide_powered_by": True}
    db.session.add(OrganizationDomain(organization_id=org.id, hostname="ar.acme.test",
                                      verification_token="x", verified_at=datetime.utcnow()))
    db.session.commit()
    host = {"Host": "ar.acme.test"}
    assert b"Acme" in client.get("/", headers=host).data
    from services.org_branding import resolved_org_branding
    assert resolved_org_branding(org)["hide_powered_by"] is True

    owner.plan = "free"
    db.session.commit()
    assert b"Acme" not in client.get("/", headers=host).data
    assert resolved_org_branding(org)["hide_powered_by"] is False


# ---- ADM-09 / ADM-21 -------------------------------------------------------

def test_deleting_org_creator_promotes_oldest_admin(client):
    from admin import _delete_user_and_content
    owner = _user("adm09owner")
    editor = _user("adm09editor", plan="free")
    admin_a = _user("adm09admin", plan="free")
    org = _org(owner, [(editor, "editor"), (admin_a, "admin")])
    org_id = org.id
    _delete_user_and_content(owner)
    db.session.commit()
    db.session.expire_all()
    org = db.session.get(Organization, org_id)
    roles = {m.user_id: m.role for m in OrganizationMember.query.filter_by(organization_id=org_id)}
    assert roles == {editor.id: "editor", admin_a.id: "owner"}
    assert org.created_by == admin_a.id


def test_deleting_org_creator_promotes_oldest_member_when_no_admin(client):
    from admin import _delete_user_and_content
    owner = _user("adm09o2")
    first = _user("adm09first", plan="free")
    second = _user("adm09second", plan="free")
    org = _org(owner, [(first, "viewer"), (second, "editor")])
    org_id = org.id
    _delete_user_and_content(owner)
    db.session.commit()
    roles = {m.user_id: m.role for m in OrganizationMember.query.filter_by(organization_id=org_id)}
    assert roles[first.id] == "owner"
    assert roles[second.id] == "editor"


def test_deleting_sole_member_deletes_org_and_domains(client):
    from admin import _delete_user_and_content
    owner = _user("adm09o3")
    org = _org(owner)
    org_id = org.id
    db.session.add(OrganizationDomain(organization_id=org_id, hostname="ar.solo.test",
                                      verification_token="x"))
    db.session.commit()
    _delete_user_and_content(owner)
    db.session.commit()
    assert db.session.get(Organization, org_id) is None
    assert OrganizationDomain.query.filter_by(hostname="ar.solo.test").count() == 0


def test_seat_message_does_not_say_upgrade_the_plan_to_everyone(client):
    owner = _user("adm09o4", plan="free")
    admin = _user("adm09a4", plan="free")
    org = _org(owner, [(admin, "admin")])
    invitee = _user("adm09i4", plan="free")
    _login(client, "adm09a4")
    resp = client.post(f"/api/organizations/{org.id}/members",
                       json={"email": invitee.email, "role": "viewer"})
    assert resp.status_code == 403
    assert "owner" in resp.get_json()["error"]


def test_org_folder_non_numeric_parent_is_400(client):
    owner = _user("adm21o")
    org = _org(owner)
    _login(client, "adm21o")
    resp = client.post(f"/api/organizations/{org.id}/folders", json={"name": "F", "parent_id": "abc"})
    assert resp.status_code == 400
