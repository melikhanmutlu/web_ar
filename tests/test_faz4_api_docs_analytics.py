"""Faz 4 (ADM-27, ADM-28): OpenAPI matches the real API; day-detail lists are
capped while counts stay exact."""

import hashlib
import uuid

from models import ApiToken, User, UserModel, db
from services.time_utils import datetime


def _token_user():
    u = User(username="faz4api", email="faz4api@test.com", plan="pro")
    u.set_password("testpassword")
    db.session.add(u)
    db.session.commit()
    plaintext = "arv_" + uuid.uuid4().hex
    db.session.add(ApiToken(user_id=u.id, name="t", token_prefix=plaintext[:12],
                            token_digest=hashlib.sha256(plaintext.encode()).hexdigest(),
                            scopes="models:read,models:write"))
    db.session.commit()
    return {"Authorization": f"Bearer {plaintext}"}


def test_openapi_lists_every_real_operation_with_errors(client):
    from app import app
    spec = client.get("/api/v1/openapi.json").get_json()
    documented = {(path, method) for path, item in spec["paths"].items()
                  for method in item if method in {"get", "post", "patch", "delete"}}
    real = set()
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/v1/") and rule.rule != "/api/v1/openapi.json" and "<path:" not in rule.rule:
            path = rule.rule[len("/api/v1"):].replace("<model_id>", "{id}").replace("<job_id>", "{id}")
            for method in rule.methods - {"HEAD", "OPTIONS"}:
                real.add((path, method.lower()))
    assert real == documented
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if method == "parameters":
                continue
            for code in ("401", "403", "429"):
                assert code in operation["responses"], (path, method, code)
    assert "requestBody" in spec["paths"]["/models/{id}"]["patch"]


def test_unknown_api_path_is_json_404_and_patch_needs_json(client):
    auth = _token_user()
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404 and resp.get_json()["error"]
    model = UserModel(id=str(uuid.uuid4()), filename="a.glb", user_id=User.query.first().id)
    db.session.add(model)
    db.session.commit()
    resp = client.patch(f"/api/v1/models/{model.id}", data="not json", headers=auth)
    assert resp.status_code == 400


def test_day_detail_caps_lists_but_not_counts(client):
    admin = User(username="faz4day", email="faz4day@test.com", is_admin=True)
    admin.set_password("testpassword")
    db.session.add(admin)
    db.session.commit()
    now = datetime.utcnow()
    for i in range(105):
        db.session.add(UserModel(id=str(uuid.uuid4()), filename=f"m{i}.glb", user_id=admin.id,
                                 upload_date=now))
    db.session.commit()
    client.post("/login", data={"username": "faz4day", "password": "testpassword"})
    from admin import _DISPLAY_TZ_OFFSET
    day = (now + _DISPLAY_TZ_OFFSET).date().isoformat()
    html = client.get(f"/admin/analytics/day/{day}").get_data(as_text=True)
    assert "showing the latest 100 of 105" in html
