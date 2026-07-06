"""Phase A: quick-win Meshy generation parameters (negative_prompt, seed,
topology, target_polycount, symmetry_mode, moderation, texture_prompt,
texture_image_url, pose_mode, origin_at, remove_lighting).

ai_generator's HTTP layer (_post) is monkeypatched throughout -- no real
Meshy calls.
"""

import pytest

import ai_generator
import config
from models import AIGenerationJob, User, db

TINY_PNG_URI = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="


@pytest.fixture
def logged_in(client):
    user = User(username="aiopts", email="aiopts@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "aiopts", "password": "testpassword"},
                follow_redirects=True)
    return user


@pytest.fixture
def meshy_configured(monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)


# --------------------------------------------------------------------------- #
#  ai_generator: payload construction
# --------------------------------------------------------------------------- #

def test_start_text_to_3d_wires_all_optional_params(monkeypatch):
    captured = {}

    def fake_post(url, payload):
        captured["payload"] = payload
        return {"result": "task-1"}

    monkeypatch.setattr(ai_generator, "_post", fake_post)
    ai_generator.start_text_to_3d(
        "a vase", negative_prompt="blurry", seed=42, topology="quad",
        target_polycount=20000, symmetry_mode="on", moderation=False)

    p = captured["payload"]
    assert p["negative_prompt"] == "blurry"
    assert p["seed"] == 42
    assert p["topology"] == "quad"
    assert p["target_polycount"] == 20000
    assert p["symmetry_mode"] == "on"
    assert p["moderation"] is False


def test_start_text_to_3d_omits_unset_params(monkeypatch):
    """No optional kwargs passed -> payload identical to pre-Phase-A shape."""
    captured = {}
    monkeypatch.setattr(ai_generator, "_post",
                        lambda url, payload: captured.update(payload) or {"result": "task-1"})
    ai_generator.start_text_to_3d("a vase")
    for key in ("negative_prompt", "seed", "topology", "target_polycount",
                "symmetry_mode", "moderation"):
        assert key not in captured


def test_start_text_to_3d_drops_invalid_enum_values(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai_generator, "_post",
                        lambda url, payload: captured.update(payload) or {"result": "task-1"})
    ai_generator.start_text_to_3d("a vase", topology="hexagon", symmetry_mode="sideways",
                                   target_polycount=99999999)
    assert "topology" not in captured
    assert "symmetry_mode" not in captured
    assert "target_polycount" not in captured


def test_start_refine_texture_prompt_and_image_are_mutually_exclusive(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai_generator, "_post",
                        lambda url, payload: captured.update(payload) or {"result": "refine-1"})
    ai_generator.start_refine("prev-1", texture_prompt="brushed steel",
                              texture_image_url=TINY_PNG_URI)
    assert captured["texture_prompt"] == "brushed steel"
    assert "texture_image_url" not in captured


def test_start_refine_rejects_raw_url_for_texture_image(monkeypatch):
    monkeypatch.setattr(ai_generator, "_post", lambda url, payload: {"result": "refine-1"})
    with pytest.raises(ai_generator.MeshyError):
        ai_generator.start_refine("prev-1", texture_image_url="https://evil.example/tex.png")


def test_remove_lighting_gated_by_ai_model(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai_generator, "_post",
                        lambda url, payload: captured.update(payload) or {"result": "task-1"})

    monkeypatch.setattr(config, "MESHY_AI_MODEL", "meshy-5")
    ai_generator.start_image_to_3d(TINY_PNG_URI, remove_lighting=True)
    assert "remove_lighting" not in captured

    captured.clear()
    monkeypatch.setattr(config, "MESHY_AI_MODEL", "meshy-6")
    ai_generator.start_image_to_3d(TINY_PNG_URI, remove_lighting=True)
    assert captured["remove_lighting"] is True


def test_image_to_3d_pose_and_origin(monkeypatch):
    captured = {}
    monkeypatch.setattr(ai_generator, "_post",
                        lambda url, payload: captured.update(payload) or {"result": "task-1"})
    ai_generator.start_image_to_3d(TINY_PNG_URI, pose_mode="a-pose", origin_at="center")
    assert captured["pose_mode"] == "a-pose"
    assert captured["origin_at"] == "center"


# --------------------------------------------------------------------------- #
#  app.py: whitelist parsing + end-to-end wiring
# --------------------------------------------------------------------------- #

def test_generate_3d_passes_whitelisted_options_only(client, logged_in, meshy_configured, monkeypatch):
    captured = {}

    def fake_start_text_to_3d(prompt, **kwargs):
        captured.update(kwargs)
        return "prev-1"

    monkeypatch.setattr(ai_generator, "start_text_to_3d", fake_start_text_to_3d)
    resp = client.post("/api/generate-3d", json={
        "mode": "text",
        "prompt": "a vase",
        "options": {
            "negative_prompt": "blurry", "seed": 7, "topology": "quad",
            "target_polycount": 15000, "symmetry_mode": "on", "moderation": True,
            "__proto__": "ignored", "arbitrary_field": "should not pass through",
        },
    })
    assert resp.status_code == 200, resp.get_json()
    assert captured["negative_prompt"] == "blurry"
    assert captured["seed"] == 7
    assert captured["topology"] == "quad"
    assert captured["target_polycount"] == 15000
    assert captured["symmetry_mode"] == "on"
    assert captured["moderation"] is True
    assert "arbitrary_field" not in captured
    assert "__proto__" not in captured

    job = db.session.get(AIGenerationJob, resp.get_json()["job_id"])
    assert job.options["negative_prompt"] == "blurry"


def test_generate_3d_texture_image_stashed_to_temp_file(client, logged_in, meshy_configured, monkeypatch, tmp_path):
    from flask import current_app
    monkeypatch.setitem(current_app.config, "TEMP_FOLDER", str(tmp_path))
    monkeypatch.setattr(ai_generator, "start_text_to_3d", lambda prompt, **kw: "prev-1")

    resp = client.post("/api/generate-3d", json={
        "mode": "text",
        "prompt": "a vase",
        "options": {"texture_image_url": TINY_PNG_URI},
    })
    assert resp.status_code == 200, resp.get_json()
    job = db.session.get(AIGenerationJob, resp.get_json()["job_id"])
    assert job.texture_ref is not None
    with open(job.texture_ref) as f:
        assert f.read() == TINY_PNG_URI


def test_refine_stage_uses_stashed_texture_reference(client, logged_in, meshy_configured, monkeypatch, tmp_path):
    from flask import current_app
    monkeypatch.setitem(current_app.config, "TEMP_FOLDER", str(tmp_path))

    import uuid
    job = AIGenerationJob(id=str(uuid.uuid4()), user_id=logged_in.id, kind="text",
                          prompt="vase", stage="preview", meshy_preview_id="prev-1",
                          status="generating", progress=49,
                          options={"texture_prompt": None, "moderation": True})
    from app import _stash_texture_reference
    job.texture_ref = _stash_texture_reference(job.id, TINY_PNG_URI)
    db.session.add(job)
    db.session.commit()

    captured = {}

    def fake_get_task(kind, task_id):
        return {"status": "SUCCEEDED", "progress": 100, "model_urls": {},
                "thumbnail_url": None, "task_error": None}

    def fake_start_refine(preview_id, **kwargs):
        captured.update(kwargs)
        return "refine-1"

    monkeypatch.setattr(ai_generator, "get_task", fake_get_task)
    monkeypatch.setattr(ai_generator, "start_refine", fake_start_refine)

    resp = client.get(f"/api/generate-3d/{job.id}/status")
    assert resp.status_code == 200, resp.get_json()
    assert captured["texture_image_url"] == TINY_PNG_URI

    db.session.refresh(job)
    assert job.texture_ref is None  # cleaned up once refine has started
