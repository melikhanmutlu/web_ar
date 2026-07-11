"""Hotspot discussion thread (Faz 3: "Hotspot yorum/tartışma akışı")."""

import uuid

from app import app, db
from models import HotspotComment, ModelHotspot, User, UserModel


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password})


def make_user(username, email):
    u = User(username=username, email=email)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def make_model_with_hotspot(user_id=None):
    model_id = "test-" + uuid.uuid4().hex[:8]
    model = UserModel(id=model_id, filename=f"{model_id}.glb",
                      file_type="glb", file_size=1000, user_id=user_id)
    db.session.add(model)
    db.session.commit()

    hotspot = ModelHotspot(
        model_id=model_id, hotspot_id="hs-1", title="Point 1",
        position_x=0, position_y=0, position_z=0,
    )
    db.session.add(hotspot)
    db.session.commit()
    return model_id, hotspot.id


def test_comments_endpoint_requires_login_to_post(client):
    model_id, _ = make_model_with_hotspot(user_id=None)
    resp = client.post(f"/api/models/{model_id}/hotspots/hs-1/comments", json={"body": "hi"})
    assert resp.status_code in (302, 401)


def test_authenticated_viewer_can_post_and_list_comments(client):
    owner = make_user("owner", "owner@test.com")
    commenter = make_user("commenter", "commenter@test.com")
    model_id, _ = make_model_with_hotspot(user_id=owner.id)

    login(client, "commenter", "testpassword123")
    resp = client.post(f"/api/models/{model_id}/hotspots/hs-1/comments", json={"body": "Nice detail here"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["success"] is True
    assert body["comment"]["body"] == "Nice detail here"
    assert body["comment"]["author"] == "commenter"

    listing = client.get(f"/api/models/{model_id}/hotspots/hs-1/comments").get_json()
    assert listing["success"] is True
    assert len(listing["comments"]) == 1


def test_empty_comment_rejected(client):
    owner = make_user("owner2", "owner2@test.com")
    model_id, _ = make_model_with_hotspot(user_id=owner.id)
    login(client, "owner2", "testpassword123")
    resp = client.post(f"/api/models/{model_id}/hotspots/hs-1/comments", json={"body": "   "})
    assert resp.status_code == 400


def test_comment_author_can_delete_own_comment(client):
    owner = make_user("owner3", "owner3@test.com")
    commenter = make_user("commenter3", "commenter3@test.com")
    model_id, _ = make_model_with_hotspot(user_id=owner.id)

    login(client, "commenter3", "testpassword123")
    created = client.post(f"/api/models/{model_id}/hotspots/hs-1/comments", json={"body": "test"}).get_json()
    comment_id = created["comment"]["id"]

    resp = client.delete(f"/api/models/{model_id}/hotspots/hs-1/comments/{comment_id}")
    assert resp.status_code == 200
    assert HotspotComment.query.count() == 0


def test_non_author_non_owner_cannot_delete_comment(client):
    owner = make_user("owner4", "owner4@test.com")
    commenter = make_user("commenter4", "commenter4@test.com")
    other = make_user("other4", "other4@test.com")
    model_id, _ = make_model_with_hotspot(user_id=owner.id)

    login(client, "commenter4", "testpassword123")
    created = client.post(f"/api/models/{model_id}/hotspots/hs-1/comments", json={"body": "test"}).get_json()
    comment_id = created["comment"]["id"]
    client.post("/logout")

    login(client, "other4", "testpassword123")
    resp = client.delete(f"/api/models/{model_id}/hotspots/hs-1/comments/{comment_id}")
    assert resp.status_code == 403
    assert HotspotComment.query.count() == 1


def test_model_owner_can_delete_any_comment_on_their_model(client):
    owner = make_user("owner5", "owner5@test.com")
    commenter = make_user("commenter5", "commenter5@test.com")
    model_id, _ = make_model_with_hotspot(user_id=owner.id)

    login(client, "commenter5", "testpassword123")
    created = client.post(f"/api/models/{model_id}/hotspots/hs-1/comments", json={"body": "test"}).get_json()
    comment_id = created["comment"]["id"]
    client.post("/logout")

    login(client, "owner5", "testpassword123")
    resp = client.delete(f"/api/models/{model_id}/hotspots/hs-1/comments/{comment_id}")
    assert resp.status_code == 200
    assert HotspotComment.query.count() == 0


def test_comments_cascade_delete_with_hotspot(client):
    owner = make_user("owner6", "owner6@test.com")
    model_id, hotspot_pk = make_model_with_hotspot(user_id=owner.id)
    login(client, "owner6", "testpassword123")
    client.post(f"/api/models/{model_id}/hotspots/hs-1/comments", json={"body": "test"})
    assert HotspotComment.query.count() == 1

    client.delete(f"/api/models/{model_id}/hotspots/hs-1")
    assert HotspotComment.query.count() == 0
