from datetime import datetime, timedelta
from pathlib import Path

from models import ModelShareLink, User, UserModel, db


def _owner_and_model(path):
    owner = User(username="shareowner", email="share@example.com")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model = UserModel(
        id="44444444-4444-4444-4444-444444444444",
        filename=str(path),
        user_id=owner.id,
        visibility="private",
    )
    db.session.add(model)
    db.session.commit()
    return owner, model


def test_private_model_requires_owner_or_share_grant(client):
    path = Path("test-private.glb").resolve()
    path.write_bytes(b"glTF")
    owner, model = _owner_and_model(path)
    assert client.get(f"/view/{model.id}").status_code == 403

    client.post("/login", data={"username": owner.username, "password": "password"})
    # Authorization passed; the synthetic GLB may redirect during parsing.
    assert client.get(f"/view/{model.id}").status_code != 403
    path.unlink(missing_ok=True)


def test_password_share_link_grants_private_view(client):
    path = Path("test-shared.glb").resolve()
    path.write_bytes(b"glTF")
    owner, model = _owner_and_model(path)
    client.post("/login", data={"username": owner.username, "password": "password"})
    response = client.post(
        f"/api/models/{model.id}/share-links",
        json={"permission": "view", "password": "open-sesame", "expires_in_hours": 2},
    )
    assert response.status_code == 201
    url = response.get_json()["url"]
    client.get("/logout")

    path_only = "/" + url.split("/", 3)[-1]
    assert client.get(path_only).status_code == 401
    opened = client.post(path_only, data={"password": "open-sesame"})
    assert opened.status_code == 302
    assert client.get(opened.headers["Location"]).status_code != 403
    path.unlink(missing_ok=True)


def test_expired_share_link_is_rejected(client):
    path = Path("test-expired.glb").resolve()
    path.write_bytes(b"glTF")
    _, model = _owner_and_model(path)
    link = ModelShareLink(
        model_id=model.id,
        token_digest="0" * 64,
        permission="view",
        expires_at=datetime.utcnow() - timedelta(seconds=1),
    )
    db.session.add(link)
    db.session.commit()
    assert client.get("/s/anything").status_code == 404
    path.unlink(missing_ok=True)
