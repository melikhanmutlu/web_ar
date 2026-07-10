from models import OrganizationMember, User, UserModel, db


def _user(username, email):
    user = User(username=username, email=email)
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    return user


def test_organization_rbac_allows_editor_model_mutation(client):
    owner = _user("orgowner", "orgowner@example.com")
    editor = _user("orgeditor", "orgeditor@example.com")
    model = UserModel(
        id="88888888-8888-8888-8888-888888888888",
        filename="unused.glb",
        user_id=owner.id,
        visibility="private",
    )
    db.session.add(model)
    db.session.commit()

    client.post("/login", data={"username": owner.username, "password": "password"})
    created = client.post("/api/organizations", json={"name": "Design Team"})
    assert created.status_code == 201
    organization_id = created.get_json()["organization"]["id"]
    invited = client.post(
        f"/api/organizations/{organization_id}/members",
        json={"email": editor.email, "role": "editor"},
    )
    assert invited.status_code == 201
    assigned = client.patch(
        f"/api/models/{model.id}/organization",
        json={"organization_id": organization_id},
    )
    assert assigned.status_code == 200
    client.get("/logout")

    client.post("/login", data={"username": editor.username, "password": "password"})
    changed = client.patch(
        f"/api/models/{model.id}/hotspots/visibility", json={"visible": False}
    )
    assert changed.status_code == 200
    assert model.hotspots_visible is False


def test_viewer_cannot_mutate_team_model(client):
    owner = _user("viewerowner", "viewerowner@example.com")
    viewer = _user("orgviewer", "orgviewer@example.com")
    client.post("/login", data={"username": owner.username, "password": "password"})
    organization_id = client.post(
        "/api/organizations", json={"name": "Read Only Team"}
    ).get_json()["organization"]["id"]
    client.post(
        f"/api/organizations/{organization_id}/members",
        json={"email": viewer.email, "role": "viewer"},
    )
    model = UserModel(
        id="99999999-9999-9999-9999-999999999999",
        filename="unused.glb",
        user_id=owner.id,
        organization_id=organization_id,
    )
    db.session.add(model)
    db.session.commit()
    client.get("/logout")
    client.post("/login", data={"username": viewer.username, "password": "password"})

    response = client.patch(
        f"/api/models/{model.id}/hotspots/visibility", json={"visible": False}
    )
    assert response.status_code == 403


def test_only_owner_or_admin_can_manage_members(client):
    owner = _user("adminowner", "adminowner@example.com")
    editor = _user("membereditor", "membereditor@example.com")
    target = _user("membertarget", "membertarget@example.com")
    client.post("/login", data={"username": owner.username, "password": "password"})
    organization_id = client.post(
        "/api/organizations", json={"name": "RBAC Team"}
    ).get_json()["organization"]["id"]
    db.session.add(OrganizationMember(
        organization_id=organization_id, user_id=editor.id, role="editor"
    ))
    db.session.commit()
    client.get("/logout")
    client.post("/login", data={"username": editor.username, "password": "password"})
    response = client.post(
        f"/api/organizations/{organization_id}/members",
        json={"email": target.email, "role": "viewer"},
    )
    assert response.status_code == 403
