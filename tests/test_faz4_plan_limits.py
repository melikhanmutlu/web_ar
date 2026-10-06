"""Faz 4 (ADM-15): plan limits that pricing advertises are enforced on the
server: batch_size, max_models for batch/ZIP, advanced AI options."""

import io
import zipfile

import ai_generator
from models import User, UserModel, db
import uuid


def _user(name, plan):
    u = User(username=name, email=f"{name}@test.com", plan=plan)
    u.set_password("testpassword")
    db.session.add(u)
    db.session.commit()
    return u


def _login(client, name):
    client.post("/login", data={"username": name, "password": "testpassword"})


def _stl():
    return b"solid t\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid t\n"


def _add_models(user, n):
    for i in range(n):
        db.session.add(UserModel(id=str(uuid.uuid4()), filename=f"m{i}.glb", user_id=user.id))
    db.session.commit()


def test_batch_over_plan_batch_size_is_rejected(client):
    _user("pl_free", "free")           # batch_size 3
    _login(client, "pl_free")
    files = [(io.BytesIO(_stl()), f"f{i}.stl") for i in range(4)]
    resp = client.post("/api/uploads/batch", data={"files": files}, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["upgrade"]["reason"] == "batch_size"


def test_batch_that_would_exceed_max_models_is_rejected(client):
    user = _user("pl_full", "free")    # max_models 10
    _add_models(user, 9)
    _login(client, "pl_full")
    files = [(io.BytesIO(_stl()), f"f{i}.stl") for i in range(2)]
    resp = client.post("/api/uploads/batch", data={"files": files}, content_type="multipart/form-data")
    assert resp.status_code == 413
    assert resp.get_json()["upgrade"]["reason"] == "model_limit"


def test_multi_model_zip_cannot_overshoot_max_models(client):
    user = _user("pl_zip", "free")
    _add_models(user, 9)
    _login(client, "pl_zip")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("a.stl", _stl())
        z.writestr("b.stl", _stl())
    buf.seek(0)
    resp = client.post("/upload_model", data={"file": (buf, "pack.zip")},
                       content_type="multipart/form-data")
    assert resp.status_code == 413
    assert UserModel.query.filter_by(user_id=user.id).count() == 9


def test_free_user_cannot_use_advanced_ai_options(client, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    user = _user("pl_ai_free", "free")
    user.ai_credit_balance = 2
    db.session.commit()
    _login(client, "pl_ai_free")
    resp = client.post("/api/generate-3d", json={
        "mode": "text", "prompt": "a vase", "options": {"topology": "quad", "moderation": True},
    })
    assert resp.status_code == 403
    assert resp.get_json()["upgrade"]["reason"] == "advanced_ai_options"
    db.session.expire_all()
    assert db.session.get(User, user.id).ai_credit_balance == 2   # nothing consumed
