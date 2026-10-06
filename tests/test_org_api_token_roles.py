"""Org-scoped API tokens follow the creator's current role, and never reach
further than the session UI does."""

import hashlib
import uuid

from models import ApiToken, Organization, OrganizationMember, User, UserModel, db


def _user(name):
    u = User(username=name, email=f"{name}@test.com", plan="business")
    u.set_password("testpassword")
    db.session.add(u)
    db.session.commit()
    return u


def _setup():
    owner, admin = _user("orgowner"), _user("orgadmin")
    org = Organization(name="Acme", slug="acme", created_by=owner.id)
    db.session.add(org)
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"),
        OrganizationMember(organization_id=org.id, user_id=admin.id, role="admin"),
    ])
    owners_model = UserModel(id=str(uuid.uuid4()), filename="a.glb", user_id=owner.id,
                             organization_id=org.id, visibility="private")
    admins_model = UserModel(id=str(uuid.uuid4()), filename="b.glb", user_id=admin.id,
                             organization_id=org.id, visibility="private")
    db.session.add_all([owners_model, admins_model])
    plaintext = "arv_" + uuid.uuid4().hex
    db.session.add(ApiToken(user_id=admin.id, organization_id=org.id, name="t",
                            token_prefix=plaintext[:12],
                            token_digest=hashlib.sha256(plaintext.encode()).hexdigest(),
                            scopes="models:read,models:write"))
    db.session.commit()
    return org, admin, owners_model, admins_model, {"Authorization": f"Bearer {plaintext}"}


def test_demoted_creator_loses_org_token(client):
    org, admin, owners_model, _, auth = _setup()
    assert client.get("/api/v1/models", headers=auth).status_code == 200

    OrganizationMember.query.filter_by(organization_id=org.id, user_id=admin.id).update({"role": "viewer"})
    db.session.commit()

    assert client.get("/api/v1/models", headers=auth).status_code == 401
    assert client.delete(f"/api/v1/models/{owners_model.id}", headers=auth).status_code == 401


def test_org_token_cannot_publish_or_delete_someone_elses_model(client):
    _, _, owners_model, _, auth = _setup()

    patch = client.patch(f"/api/v1/models/{owners_model.id}", json={"visibility": "public"}, headers=auth)
    delete = client.delete(f"/api/v1/models/{owners_model.id}", headers=auth)

    assert patch.status_code == 403
    assert delete.status_code == 403
    db.session.expire_all()
    model = db.session.get(UserModel, owners_model.id)
    assert model.visibility == "private" and model.deleted_at is None


def test_org_token_can_still_rename_org_models_and_manage_own(client):
    _, _, owners_model, admins_model, auth = _setup()

    rename = client.patch(f"/api/v1/models/{owners_model.id}", json={"name": "Renamed"}, headers=auth)
    publish_own = client.patch(f"/api/v1/models/{admins_model.id}", json={"visibility": "public"}, headers=auth)

    assert rename.status_code == 200
    assert publish_own.status_code == 200
