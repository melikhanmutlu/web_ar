"""SEC-08: the scene builder creates a new model, so it must honor the same
model-count and storage guards as /upload_model."""

import os
import uuid

import trimesh

from app import app, db
from models import User, UserModel


def _make_model(user_id):
    model_id = "scn-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    with open(glb_path, "wb") as f:
        f.write(trimesh.Scene(trimesh.creation.box(extents=(0.1, 0.1, 0.1))).export(file_type="glb"))
    db.session.add(UserModel(id=model_id, filename=glb_path, file_type="glb",
                             file_size=os.path.getsize(glb_path), user_id=user_id,
                             cumulative_scale=1.0))
    db.session.commit()
    return model_id


def _setup(client, name):
    owner = User(username=name, email=f"{name}@test.com")
    owner.set_password("testpassword123")
    db.session.add(owner)
    db.session.commit()
    client.post("/login", data={"username": name, "password": "testpassword123"})
    return owner, _make_model(owner.id), _make_model(owner.id)


def _payload(m1, m2):
    return {"name": "S", "items": [{"model_id": m1}, {"model_id": m2}]}


def test_build_scene_respects_model_count_limit(client, monkeypatch):
    import app as app_module
    from services import upload_pipeline
    from blueprints import upload as upload_module
    monkeypatch.setattr(upload_pipeline, "_enqueue_internal_job", lambda *a, **k: None)
    monkeypatch.setattr(upload_module, "plan_limit",
                        lambda user, key: 2 if key == "max_models" else None)
    owner, m1, m2 = _setup(client, "scnlimit1")

    resp = client.post("/api/scenes/build", json=_payload(m1, m2))

    assert resp.status_code == 413
    assert UserModel.query.filter_by(user_id=owner.id).count() == 2


def test_build_scene_respects_storage_quota(client, monkeypatch):
    import app as app_module
    from services import upload_pipeline
    from blueprints import upload as upload_module
    monkeypatch.setattr(upload_pipeline, "_enqueue_internal_job", lambda *a, **k: None)
    monkeypatch.setattr(upload_module, "effective_storage_quota_mb", lambda user, default: 1)
    owner, m1, m2 = _setup(client, "scnquota1")
    UserModel.query.filter_by(id=m1).update({"file_size": 1024 * 1024})
    db.session.commit()

    resp = client.post("/api/scenes/build", json=_payload(m1, m2))

    assert resp.status_code == 413
    assert UserModel.query.filter_by(user_id=owner.id).count() == 2
