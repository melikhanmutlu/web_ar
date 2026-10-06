"""SEC-07: personal folder routes must honor *current* org membership for org folders."""

from models import Folder, Organization, OrganizationMember, User, UserModel, db


def _user(name):
    u = User(username=name, email=f"{name}@test.com", plan="business")
    u.set_password("password")
    db.session.add(u)
    db.session.commit()
    return u


def _setup():
    alice, dave = _user("alice"), _user("dave")
    org = Organization(name="Acme", slug="acme", created_by=alice.id)
    db.session.add(org)
    db.session.commit()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=alice.id, role="owner"),
        OrganizationMember(organization_id=org.id, user_id=dave.id, role="editor"),
    ])
    parent = Folder(name="Shared", slug="shared-1", user_id=dave.id, organization_id=org.id)
    db.session.add(parent)
    db.session.commit()
    child = Folder(name="Child", slug="child-1", user_id=alice.id,
                   organization_id=org.id, parent_id=parent.id)
    db.session.add(child)
    db.session.commit()
    return org, dave, parent, child


def _login(client, name):
    client.post("/login", data={"username": name, "password": "password"})


def test_removed_member_cannot_rename_or_delete_org_folder(client):
    org, dave, parent, child = _setup()
    OrganizationMember.query.filter_by(organization_id=org.id, user_id=dave.id).delete()
    db.session.commit()
    _login(client, "dave")

    assert client.post(f"/rename_folder/{parent.id}", json={"name": "pwned"}).status_code == 403
    assert client.post(f"/delete_folder/{parent.id}").status_code == 403
    db.session.expire_all()
    assert db.session.get(Folder, parent.id).name == "Shared"
    assert db.session.get(Folder, child.id) is not None


def test_demoted_viewer_cannot_mutate_org_folder(client):
    org, dave, parent, _ = _setup()
    OrganizationMember.query.filter_by(organization_id=org.id, user_id=dave.id).update({"role": "viewer"})
    db.session.commit()
    _login(client, "dave")
    assert client.post(f"/rename_folder/{parent.id}", json={"name": "x"}).status_code == 403
    assert client.post(f"/delete_folder/{parent.id}").status_code == 403


def test_current_editor_creator_can_still_rename_and_delete(client):
    _, dave, parent, child = _setup()
    _login(client, "dave")
    assert client.post(f"/rename_folder/{parent.id}", json={"name": "Renamed"}).status_code == 200
    assert client.post(f"/delete_folder/{parent.id}").status_code == 200
    db.session.expire_all()
    assert db.session.get(Folder, parent.id) is None


def test_removed_member_cannot_move_own_model_into_org_folder(client):
    org, dave, parent, _ = _setup()
    model = UserModel(id="m-sec07", filename="a.glb", user_id=dave.id)
    db.session.add(model)
    OrganizationMember.query.filter_by(organization_id=org.id, user_id=dave.id).delete()
    db.session.commit()
    _login(client, "dave")
    r = client.post("/move_model", json={"model_id": "m-sec07", "folder_id": parent.id})
    assert r.status_code == 403
