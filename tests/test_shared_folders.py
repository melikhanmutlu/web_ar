from models import Folder, OrganizationMember, User, UserModel, db


def test_team_editor_can_manage_shared_folders_and_models(client):
    owner = User(username="folderowner", email="folderowner@example.com")
    editor = User(username="foldereditor", email="foldereditor@example.com")
    owner.set_password("password"); editor.set_password("password")
    db.session.add_all([owner, editor]); db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    organization_id = client.post(
        "/api/organizations", json={"name": "Shared Assets"}
    ).get_json()["organization"]["id"]
    db.session.add(OrganizationMember(
        organization_id=organization_id, user_id=editor.id, role="editor"
    ))
    model = UserModel(
        id="ffffffff-ffff-ffff-ffff-ffffffffffff",
        filename="unused.glb", user_id=owner.id, organization_id=organization_id,
    )
    db.session.add(model); db.session.commit()
    client.get("/logout")
    client.post("/login", data={"username": editor.username, "password": "password"})

    created = client.post(
        f"/api/organizations/{organization_id}/folders", json={"name": "Launch Assets"}
    )
    assert created.status_code == 201
    folder_id = created.get_json()["folder"]["id"]
    assert client.put(
        f"/api/organizations/{organization_id}/folders/{folder_id}/models/{model.id}"
    ).status_code == 200
    assert model.folder_id == folder_id
    listed = client.get(f"/api/organizations/{organization_id}/folders").get_json()["folders"]
    assert listed[0]["model_count"] == 1
    assert client.patch(
        f"/api/organizations/{organization_id}/folders/{folder_id}", json={"name": "Ready"}
    ).status_code == 200
    assert client.delete(
        f"/api/organizations/{organization_id}/folders/{folder_id}"
    ).status_code == 200
    assert model.folder_id is None


def test_team_viewer_cannot_create_shared_folder(client):
    owner = User(username="sfowner", email="sfowner@example.com")
    viewer = User(username="sfviewer", email="sfviewer@example.com")
    owner.set_password("password"); viewer.set_password("password")
    db.session.add_all([owner, viewer]); db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    organization_id = client.post(
        "/api/organizations", json={"name": "Viewer Assets"}
    ).get_json()["organization"]["id"]
    db.session.add(OrganizationMember(
        organization_id=organization_id, user_id=viewer.id, role="viewer"
    )); db.session.commit()
    client.get("/logout")
    client.post("/login", data={"username": viewer.username, "password": "password"})
    assert client.post(
        f"/api/organizations/{organization_id}/folders", json={"name": "Denied"}
    ).status_code == 403
