import hashlib
from datetime import datetime, timedelta
from pathlib import Path

from models import ModelShareLink, User, UserModel, db


def _owner_and_model(path):
    owner = User(username="shareowner", email="share@example.com", plan="business")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model = UserModel(
        id="55555555-5555-5555-5555-555555555555",
        filename=str(path), user_id=owner.id, visibility="private",
    )
    db.session.add(model)
    db.session.commit()
    return owner, model


def _login(client, owner):
    client.post("/login", data={"username": owner.username, "password": "password"})


def test_list_share_links_owner_only_and_hides_secrets(client):
    path = Path("test-list-links.glb").resolve()
    path.write_bytes(b"glTF")
    owner, model = _owner_and_model(path)
    url = f"/api/models/{model.id}/share-links"
    assert client.get(url).status_code in (302, 401)  # login required
    _login(client, owner)
    created = client.post(url, json={"permission": "edit", "password": "pw-secret", "expires_in_hours": 5}).get_json()
    revoked = client.post(url, json={"permission": "view"}).get_json()
    client.delete(f"{url}/{revoked['id']}")

    listing = client.get(url)
    assert listing.status_code == 200
    data = listing.get_json()
    assert [l["id"] for l in data["links"]] == [created["id"]]
    link = data["links"][0]
    assert link["permission"] == "edit" and link["has_password"] is True
    assert link["expires_at"] and link["created_at"]
    assert "url" not in link and "pw-secret" not in listing.get_data(as_text=True)
    assert data["password_allowed"] is True

    other = User(username="intruder", email="i@example.com")
    other.set_password("password")
    db.session.add(other)
    db.session.commit()
    client.post("/logout")
    _login(client, other)
    assert client.get(url).status_code == 403
    path.unlink(missing_ok=True)


def test_wrong_share_password_rerenders_form_with_error(client):
    path = Path("test-wrong-pw.glb").resolve()
    path.write_bytes(b"glTF")
    owner, model = _owner_and_model(path)
    model.display_name = "My <b>Chair</b>"
    db.session.commit()
    _login(client, owner)
    url = client.post(
        f"/api/models/{model.id}/share-links", json={"password": "right-one"}
    ).get_json()["url"]
    client.post("/logout")
    path_only = "/" + url.split("/", 3)[-1]

    wrong = client.post(path_only, data={"password": "nope"})
    html = wrong.get_data(as_text=True)
    assert wrong.status_code == 403
    assert 'aria-invalid="true"' in html and "Incorrect password" in html
    assert '<label for="sharePassword"' in html
    assert "<form" in html
    assert "My &lt;b&gt;Chair&lt;/b&gt;" in html and "shareowner" in html
    # JSON clients keep the machine-readable error.
    assert client.post(path_only, json={"password": "nope"}).get_json()["error"] == "Invalid password"
    path.unlink(missing_ok=True)


def test_revoked_and_expired_links_render_branded_pages(client):
    path = Path("test-unavail.glb").resolve()
    path.write_bytes(b"glTF")
    _, model = _owner_and_model(path)
    for token, kwargs in (
        ("revoked-tok", {"revoked_at": datetime.utcnow()}),
        ("expired-tok", {"expires_at": datetime.utcnow() - timedelta(hours=1)}),
    ):
        db.session.add(ModelShareLink(
            model_id=model.id, token_digest=hashlib.sha256(token.encode()).hexdigest(),
            permission="view", **kwargs))
    db.session.commit()
    revoked = client.get("/s/revoked-tok")
    assert revoked.status_code == 410 and "Link revoked" in revoked.get_data(as_text=True)
    expired = client.get("/s/expired-tok")
    assert expired.status_code == 410 and "Link expired" in expired.get_data(as_text=True)
    missing = client.get("/s/never-existed")
    assert missing.status_code == 404 and "Link not found" in missing.get_data(as_text=True)
    path.unlink(missing_ok=True)
