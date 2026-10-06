"""SEC-12: anonymous view/like counters must not be inflatable without limit."""

import os

import trimesh

from app import app, db
from models import ModelAnalyticsEvent, ModelLike, User, UserModel


def _public_model():
    owner = User(username="infl-owner", email="infl@test.com")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model_id = "infl-model-0001"
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb = os.path.join(model_dir, "model.glb")
    with open(glb, "wb") as f:
        f.write(trimesh.Scene(trimesh.creation.box()).export(file_type="glb"))
    db.session.add(UserModel(id=model_id, filename=glb, file_type="glb", user_id=owner.id,
                             visibility="public", file_size=os.path.getsize(glb)))
    db.session.commit()
    return model_id


def test_repeated_views_from_same_visitor_count_once(client):
    model_id = _public_model()
    for _ in range(25):
        assert client.get(f"/view/{model_id}").status_code == 200
    db.session.expire_all()
    assert db.session.get(UserModel, model_id).view_count == 1
    assert ModelAnalyticsEvent.query.filter_by(model_id=model_id, event_type="view").count() == 1


def test_anonymous_likes_with_fresh_cookies_are_capped_per_ip(client):
    from blueprints.engagement import ANON_LIKES_PER_IP_PER_DAY
    model_id = _public_model()
    for _ in range(ANON_LIKES_PER_IP_PER_DAY + 10):
        client.delete_cookie("session")
        client.post(f"/api/models/{model_id}/like")
    assert ModelLike.query.filter_by(model_id=model_id).count() == ANON_LIKES_PER_IP_PER_DAY
