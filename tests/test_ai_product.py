import ai_generator

from models import AIGenerationJob, PromptPreset, User, db


def _login_ai_user(client):
    user = User(username="aiuser", email="aiuser@example.com")
    user.set_password("password")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": user.username, "password": "password"})
    return user


def test_prompt_preset_crud_and_generation_history(client):
    user = _login_ai_user(client)
    listed = client.get("/api/ai/presets")
    assert listed.status_code == 200
    assert any(item["id"] == "system:ecommerce" for item in listed.get_json()["presets"])

    created = client.post("/api/ai/presets", json={
        "name": "Museum prop",
        "category": "heritage",
        "prompt_template": "{prompt}, museum-quality reconstruction",
    })
    assert created.status_code == 201
    preset_id = created.get_json()["id"]
    assert db.session.get(PromptPreset, preset_id).user_id == user.id
    assert client.patch(
        f"/api/ai/presets/{preset_id}", json={"name": "Archive prop"}
    ).status_code == 200

    db.session.add(AIGenerationJob(
        id="history-job", user_id=user.id, kind="text", prompt="chair", status="ready"
    ))
    db.session.commit()
    history = client.get("/api/ai/generations").get_json()["generations"]
    assert history[0]["job_id"] == "history-job"
    assert history[0]["prompt"] == "chair"
    assert client.delete(f"/api/ai/presets/{preset_id}").status_code == 200


def test_generation_variant_applies_preset_and_parent(client, monkeypatch):
    user = _login_ai_user(client)
    parent = AIGenerationJob(
        id="parent-job", user_id=user.id, kind="text", prompt="wooden chair",
        status="ready",
    )
    db.session.add(parent)
    db.session.commit()
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    captured = {}
    monkeypatch.setattr(
        ai_generator,
        "start_text_to_3d",
        lambda prompt, **kw: captured.setdefault("prompt", prompt) or "task-id",
    )
    response = client.post("/api/generate-3d", json={
        "mode": "text",
        "parent_job_id": parent.id,
        "preset_id": "system:ecommerce",
    })
    assert response.status_code == 200
    job = db.session.get(AIGenerationJob, response.get_json()["job_id"])
    assert job.parent_job_id == parent.id
    assert "studio-ready" in job.prompt
    assert "wooden chair" in captured["prompt"]
