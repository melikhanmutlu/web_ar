"""Model library tags: PATCH /api/models/<id>/metadata's tags field, and the
format/tag data attributes rendered on the my_models library cards."""
import pytest

from models import User, UserModel, db


@pytest.fixture
def logged_in(client):
    user = User(username="tagger", email="tagger@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "tagger", "password": "testpassword"},
                follow_redirects=True)
    return user


def test_metadata_patch_sets_and_normalizes_tags(client, logged_in):
    model = UserModel(id="tag-model", filename="m.glb", user_id=logged_in.id)
    db.session.add(model)
    db.session.commit()

    response = client.patch(
        f"/api/models/{model.id}/metadata",
        json={"tags": [" Vehicle ", "Sci-Fi!!", "vehicle", "  "]},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["tags"] == ["vehicle", "sci-fi"]
    db.session.refresh(model)
    assert model.tags == "vehicle,sci-fi"


def test_metadata_patch_clears_tags_with_empty_list(client, logged_in):
    model = UserModel(id="tag-model-2", filename="m.glb", user_id=logged_in.id, tags="old,tags")
    db.session.add(model)
    db.session.commit()

    response = client.patch(f"/api/models/{model.id}/metadata", json={"tags": []})
    assert response.status_code == 200
    assert response.get_json()["tags"] == []
    db.session.refresh(model)
    assert model.tags is None


def test_metadata_patch_rejects_non_list_tags(client, logged_in):
    model = UserModel(id="tag-model-3", filename="m.glb", user_id=logged_in.id)
    db.session.add(model)
    db.session.commit()

    response = client.patch(f"/api/models/{model.id}/metadata", json={"tags": "not-a-list"})
    assert response.status_code == 400


def test_my_models_renders_file_type_and_tags_data_attributes(client, logged_in):
    model = UserModel(
        id="tag-model-4", filename="m.glb", user_id=logged_in.id,
        file_type="fbx", tags="robot,vehicle",
    )
    db.session.add(model)
    db.session.commit()

    page = client.get("/my_models").get_data(as_text=True)
    assert 'data-file-type="fbx"' in page
    assert 'data-tags="robot,vehicle"' in page
    assert 'value="fbx"' in page  # format filter option
