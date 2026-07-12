"""Regression tests for the full-codebase review round.

Each test pins a concrete bug found during the review so it can't regress:
- webhook SSRF guard (private/loopback URLs rejected at create + delivery)
- GLB texture embedding keeps the buffer 4-byte aligned (UV accessor valid)
- a textured BLEND material isn't silently flattened to OPAQUE at opacity 1.0
- a rigged model can be hard-deleted (RigAnimationJob FK no longer blocks it)
- chunked upload enforces the declared total_size (quota/disk bypass closed)
- update-model-color regenerates the USDZ (iOS Quick Look stays in sync)
"""
import base64
import io
import os
import struct
import uuid
from datetime import datetime, timedelta

import numpy as np
import pytest
import trimesh
from pygltflib import GLTF2

import app as app_module
from app import app, db
from models import RigAnimationJob, User, UserModel, WebhookSubscription
from services.webhooks import dispatch_webhook_event, is_safe_webhook_url
import services.webhooks as webhooks_service


# ── Webhook SSRF guard ────────────────────────────────────────────────────
def test_is_safe_webhook_url_rejects_private_and_loopback(monkeypatch):
    def fake_getaddrinfo(host, *a, **k):
        mapping = {
            "internal.local": "10.0.0.5",
            "metadata": "169.254.169.254",
            "localhost": "127.0.0.1",
        }
        return [(2, 1, 6, "", (mapping[host], 443))]

    monkeypatch.setattr("services.webhooks.socket.getaddrinfo", fake_getaddrinfo)
    assert is_safe_webhook_url("https://internal.local/hook") is False
    assert is_safe_webhook_url("https://metadata/latest") is False
    assert is_safe_webhook_url("https://localhost/hook") is False
    # non-https always rejected regardless of host
    assert is_safe_webhook_url("http://example.com/hook") is False


def test_is_safe_webhook_url_allows_public(monkeypatch):
    monkeypatch.setattr(
        "services.webhooks.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert is_safe_webhook_url("https://example.com/hook") is True


def test_dispatch_pins_dns_against_rebinding(client, monkeypatch):
    """DNS-rebinding guard: the safety check and the real request must use
    the SAME resolved address, or a low-TTL/stateful DNS record could return
    a public IP for the check and a private one moments later for the actual
    connection -- defeating the guard despite it re-checking "at delivery
    time". Simulates this by having the (unpinned) resolver return a
    different address on each call, then asserting the real request -- which
    itself calls socket.getaddrinfo, like urllib3 would -- observes the
    pinned (first, validated-public) address, not the rebound one."""
    user = User(username="pinner", email="pinner@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    subscription = WebhookSubscription(
        user_id=user.id, url="https://rebinder.example/hook", secret="s",
        event_types="conversion.completed",
    )
    db.session.add(subscription)
    db.session.commit()

    call_count = {"n": 0}

    def rebinding_getaddrinfo(host, port, *a, **k):
        call_count["n"] += 1
        addr = "93.184.216.34" if call_count["n"] == 1 else "127.0.0.1"
        return [(2, 1, 6, "", (addr, port))]

    monkeypatch.setattr(webhooks_service.socket, "getaddrinfo", rebinding_getaddrinfo)

    observed = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        # Simulate what urllib3 does internally: resolve the host to connect.
        import socket as socket_module
        infos = socket_module.getaddrinfo(webhooks_service.urlsplit(url).hostname, 443)
        observed["ip"] = infos[0][4][0]

        class FakeResponse:
            status_code = 200
        return FakeResponse()

    monkeypatch.setattr(webhooks_service.requests, "post", fake_post)

    dispatch_webhook_event("conversion.completed", user.id, {"model_id": "x"})

    # Without pinning this would be "127.0.0.1" (the second, rebound call).
    assert observed["ip"] == "93.184.216.34"


def test_create_webhook_rejects_private_url(client, monkeypatch):
    user = User(username="ssrf", email="ssrf@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "ssrf", "password": "testpassword"})
    monkeypatch.setattr(
        "services.webhooks.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("192.168.1.10", 443))],
    )
    resp = client.post("/api/webhooks", json={
        "url": "https://sneaky.example/hook",
        "event_types": ["conversion.completed"],
    })
    assert resp.status_code == 400


# ── GLB texture embedding alignment ───────────────────────────────────────
def _png_bytes_of_length_not_multiple_of_4():
    """A tiny valid PNG; retry sizes until length % 4 != 0 so we exercise the
    padding path (the accessor after it would otherwise be misaligned)."""
    from PIL import Image

    for dim in (3, 5, 7, 9, 11, 13):
        buf = io.BytesIO()
        Image.new("RGB", (dim, dim), (200, 100, 50)).save(buf, format="PNG")
        data = buf.getvalue()
        if len(data) % 4 != 0:
            return data
    return buf.getvalue()


def test_texture_embedding_keeps_buffer_view_offsets_aligned():
    from glb_modifier import apply_texture_modifications

    # icosphere has no TEXCOORD_0, so _ensure_texcoord0 will append a FLOAT
    # accessor right after the embedded image — the exact misalignment case.
    mesh = trimesh.creation.icosphere(subdivisions=2)
    gltf = GLTF2().load_from_bytes(mesh.export(file_type="glb"))

    png = _png_bytes_of_length_not_multiple_of_4()
    assert len(png) % 4 != 0  # precondition: unaligned image length
    b64 = base64.b64encode(png).decode()

    result = apply_texture_modifications(gltf, b64)

    # Every accessor-backed bufferView must start on a 4-byte boundary.
    for acc in result.accessors:
        bv = result.bufferViews[acc.bufferView]
        assert (bv.byteOffset or 0) % 4 == 0, f"accessor bufferView misaligned: {bv.byteOffset}"

    # And the GLB must round-trip / reload cleanly.
    out = io.BytesIO()
    result.save_to_bytes  # attribute exists
    reloaded = GLTF2().load_from_bytes(b"".join(result.save_to_bytes()))
    assert reloaded is not None


# ── BLEND preservation for textured materials ─────────────────────────────
def test_textured_blend_material_not_flattened_to_opaque_at_full_opacity():
    from glb_modifier import modify_glb

    model_id = "blend-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    src = os.path.join(model_dir, "model.glb")
    dst = os.path.join(model_dir, "out.glb")

    # Build a GLB with a textured material authored as BLEND.
    mesh = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    mesh.visual = trimesh.visual.TextureVisuals(
        material=trimesh.visual.material.PBRMaterial(
            name="glass", baseColorFactor=[1.0, 1.0, 1.0, 1.0])
    )
    gltf = GLTF2().load_from_bytes(mesh.export(file_type="glb"))
    # Embed a texture + mark the material BLEND.
    from glb_modifier import apply_texture_modifications
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, format="PNG")
    gltf = apply_texture_modifications(gltf, base64.b64encode(buf.getvalue()).decode())
    gltf.materials[0].alphaMode = "BLEND"
    with open(src, "wb") as f:
        f.write(b"".join(gltf.save_to_bytes()))

    # A color edit with the default opacity (1.0) must NOT downgrade BLEND.
    ok = modify_glb(src, dst, {"material": {"color": "#112233", "opacity": 1.0, "tint_textures": True}})
    assert ok
    out = GLTF2().load(dst)
    assert out.materials[0].alphaMode == "BLEND"


# ── RigAnimationJob no longer blocks hard-delete ──────────────────────────
def test_rigged_model_can_be_hard_deleted(client, monkeypatch):
    monkeypatch.setattr(app_module, "refresh_usdz_after_edit", lambda *a, **k: None)
    from model_cleanup import purge_model_completely

    model_id = "rig-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(os.path.join(model_dir, "model.glb"))
    model = UserModel(id=model_id, filename=os.path.join(model_dir, "model.glb"),
                      file_type="glb", file_size=100, user_id=None, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()

    job = RigAnimationJob(id=uuid.uuid4().hex, model_id=model_id, status="completed",
                          height_meters=0.1)
    db.session.add(job)
    db.session.commit()

    # Would raise IntegrityError before the fix (FK with no cascade).
    purge_model_completely(db.session, model)
    db.session.commit()

    assert db.session.get(UserModel, model_id) is None
    assert RigAnimationJob.query.filter_by(model_id=model_id).count() == 0


# ── Chunked upload enforces the declared total size ───────────────────────
def test_chunked_upload_rejects_bytes_exceeding_declared_total(client):
    init = client.post("/api/uploads/chunked/init", json={
        "filename": "big.stl", "total_size": 4, "total_chunks": 1,
    })
    assert init.status_code == 201, init.get_json()
    upload_id = init.get_json()["upload_id"]

    # Declared total_size=4 but we PUT far more — must be rejected 413.
    resp = client.put(
        f"/api/uploads/chunked/{upload_id}/chunks/0",
        data=b"x" * 4096,
        content_type="application/octet-stream",
    )
    assert resp.status_code == 413, resp.get_json()


def test_chunked_upload_size_check_serialized_under_concurrency(client):
    """Without the per-session fcntl lock, concurrent PUTs each compute
    "bytes so far" before any other has finished writing, so more than the
    declared total_size could land on disk before the final check at
    /complete catches it. Declare a total_size that only fits 3 of 6
    chunks, fire all 6 concurrently, and assert exactly 3 succeed -- a
    race would let more than 3 (potentially all 6) through."""
    import concurrent.futures

    from app import app as flask_app

    chunk_size = 1000
    total_chunks = 6
    fits = 3
    init = client.post("/api/uploads/chunked/init", json={
        "filename": "race.stl", "total_size": chunk_size * fits, "total_chunks": total_chunks,
    })
    assert init.status_code == 201, init.get_json()
    upload_id = init.get_json()["upload_id"]

    def put_chunk(index):
        with flask_app.test_client() as c:
            resp = c.put(
                f"/api/uploads/chunked/{upload_id}/chunks/{index}",
                data=b"x" * chunk_size,
                content_type="application/octet-stream",
            )
            return resp.status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=total_chunks) as pool:
        statuses = list(pool.map(put_chunk, range(total_chunks)))

    accepted = statuses.count(200)
    rejected = statuses.count(413)
    assert accepted == fits, f"expected exactly {fits} accepted, got {accepted} (statuses={statuses})"
    assert rejected == total_chunks - fits


# ── update-model-color regenerates USDZ ───────────────────────────────────
def test_update_model_color_refreshes_usdz(client, monkeypatch):
    user = User(username="colorer", email="colorer@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    client.post("/login", data={"username": "colorer", "password": "testpassword"})

    model_id = "col-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    glb_path = os.path.join(model_dir, "model.glb")
    trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(glb_path)
    model = UserModel(id=model_id, filename=glb_path, file_type="glb",
                      file_size=100, user_id=user.id, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()

    calls = []
    monkeypatch.setattr(app_module, "refresh_usdz_after_edit",
                        lambda mid, path, *a, **k: calls.append((mid, path)))

    resp = client.post("/api/update-model-color", json={"model_id": model_id, "color": "#3355ff"})
    assert resp.status_code == 200, resp.get_json()
    assert len(calls) == 1 and calls[0][0] == model_id


# ── Orphaned AI/rig job stage recovery ────────────────────────────────────
def _backdate(job, minutes):
    """Force job.updated_at into the past, bypassing the onupdate=utcnow
    default, so the orphan-stage grace-period check in worker.py treats it
    as stale. A raw UPDATE avoids the ORM re-applying onupdate on commit."""
    from models import db as _db
    _db.session.execute(
        type(job).__table__.update()
        .where(type(job).id == job.id)
        .values(updated_at=datetime.utcnow() - timedelta(minutes=minutes))
    )
    _db.session.commit()
    _db.session.refresh(job)


def test_unstick_orphaned_ai_stage_rolls_back_refining_and_finalizing(client):
    from models import AIGenerationJob
    import worker
    from worker import _unstick_orphaned_ai_stage

    user = User(username="aiorphan", email="aiorphan@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    grace = worker.AI_ORPHAN_STAGE_GRACE_MINUTES + 1

    # "refining" is only ever a transitional claim from "preview" -- if the
    # process dies right after the claim commits, no `if job.stage ==`
    # branch in _advance_ai_job matches "refining", so the job would spin at
    # the same progress forever without this recovery.
    refining = AIGenerationJob(id=uuid.uuid4().hex, user_id=user.id, kind="text", stage="refining")
    db.session.add(refining)
    db.session.commit()
    _backdate(refining, grace)
    _unstick_orphaned_ai_stage(refining)
    assert refining.stage == "preview"

    # "finalizing" is ambiguous -- claimed from either "image" or "refine" --
    # and must be disambiguated via job.kind.
    finalizing_image = AIGenerationJob(id=uuid.uuid4().hex, user_id=user.id, kind="image", stage="finalizing")
    finalizing_text = AIGenerationJob(id=uuid.uuid4().hex, user_id=user.id, kind="text", stage="finalizing")
    db.session.add_all([finalizing_image, finalizing_text])
    db.session.commit()
    _backdate(finalizing_image, grace)
    _backdate(finalizing_text, grace)
    _unstick_orphaned_ai_stage(finalizing_image)
    _unstick_orphaned_ai_stage(finalizing_text)
    assert finalizing_image.stage == "image"
    assert finalizing_text.stage == "refine"

    # A resting stage (one _advance_ai_job actually handles) must be left alone.
    resting = AIGenerationJob(id=uuid.uuid4().hex, user_id=user.id, kind="text", stage="preview")
    db.session.add(resting)
    db.session.commit()
    _backdate(resting, grace)
    _unstick_orphaned_ai_stage(resting)
    assert resting.stage == "preview"


def test_unstick_orphaned_ai_stage_leaves_recently_active_finalize_alone(client):
    """A slow-but-alive _finalize_ai_job (large GLB download, no intermediate
    commit) can look identical to a truly-orphaned claim by DB state alone --
    both show status='generating', stage='finalizing'. The only thing that
    tells them apart is recency: a rollback must not fire for a job whose
    updated_at is still within the grace period, or it would race a real
    finalize and let a second concurrent trigger re-claim and double-process
    the same job."""
    from models import AIGenerationJob
    from worker import _unstick_orphaned_ai_stage

    user = User(username="aiactive", email="aiactive@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()

    job = AIGenerationJob(id=uuid.uuid4().hex, user_id=user.id, kind="text", stage="finalizing")
    db.session.add(job)
    db.session.commit()  # updated_at defaults to "now" -- well within the grace period

    _unstick_orphaned_ai_stage(job)
    assert job.stage == "finalizing", "a recently-active claim must not be rolled back"


def test_unstick_orphaned_rig_stage_rolls_back_finalizing(client):
    import worker
    from models import RigAnimationJob
    from worker import _unstick_orphaned_rig_stage

    model_id = "rigorphan-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(os.path.join(model_dir, "model.glb"))
    model = UserModel(id=model_id, filename=os.path.join(model_dir, "model.glb"),
                      file_type="glb", file_size=100, user_id=None, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()

    job = RigAnimationJob(id=uuid.uuid4().hex, model_id=model_id, status="generating",
                          stage="finalizing", height_meters=0.1)
    db.session.add(job)
    db.session.commit()
    _backdate(job, worker.AI_ORPHAN_STAGE_GRACE_MINUTES + 1)
    _unstick_orphaned_rig_stage(job)
    assert job.stage == "animating"


# ── Upload pipeline retry idempotency ─────────────────────────────────────
def test_run_upload_pipeline_short_circuits_when_model_already_exists(client, monkeypatch):
    """If a prior attempt already committed the UserModel row (e.g. the job
    was retried after a later step crashed), re-running the whole pipeline
    must return the existing model id instead of redoing the conversion and
    crashing on the duplicate primary key."""
    from app import _run_upload_pipeline

    model_id = "dup-" + uuid.uuid4().hex[:8]
    model_dir = os.path.join(app.config["CONVERTED_FOLDER"], model_id)
    os.makedirs(model_dir, exist_ok=True)
    trimesh.creation.box(extents=(0.1, 0.1, 0.1)).export(os.path.join(model_dir, "model.glb"))
    model = UserModel(id=model_id, filename=os.path.join(model_dir, "model.glb"),
                      file_type="glb", file_size=100, user_id=None, cumulative_scale=1.0)
    db.session.add(model)
    db.session.commit()

    def boom(*a, **k):
        raise AssertionError("conversion_service.convert should not run for an already-completed model_id")
    monkeypatch.setattr(app_module.conversion_service, "convert", boom)

    result = _run_upload_pipeline({
        "unique_id": model_id,
        "original_filename": "whatever.stl",
        "temp_file_path": "/does/not/matter",  # never checked: short-circuits first
        "file_extension": "stl",
    })
    assert result == model_id


# ── Thumbnail invalidation after geometry-mutating edits ─────────────────
def test_save_modifications_invalidates_stale_thumbnail(client, monkeypatch):
    from tests.test_viewer_page import make_two_material_model

    monkeypatch.setattr(app_module, "refresh_usdz_after_edit", lambda *a, **k: None)
    model_id, glb_path = make_two_material_model(user_id=None)
    thumbnail_path = os.path.join(os.path.dirname(glb_path), "thumbnail.png")
    with open(thumbnail_path, "wb") as f:
        f.write(b"stale-thumbnail-bytes")

    enqueued = []
    monkeypatch.setattr(app_module, "_enqueue_internal_job",
                        lambda job_type, mid, payload: enqueued.append((job_type, mid, payload)))

    resp = client.post("/save_modifications", json={
        "model_id": model_id,
        "modifications": {"material": {"opacity": 0.5}},
    })
    assert resp.get_json()["success"] is True, resp.get_json()

    assert not os.path.exists(thumbnail_path), "stale thumbnail should have been removed"
    assert enqueued and enqueued[0][0] == "thumbnail" and enqueued[0][1] == model_id


def test_mesh_vertex_face_counts_skips_faceless_geometry():
    """A Scene can contain a POINTS-mode primitive, loaded by trimesh as a
    PointCloud -- it has .vertices but no .faces attribute at all. The
    original hasattr(g, "vertices") filter let it through and then crashed on
    g.faces; it must be skipped instead (both call sites already wrap this in
    a broad except, so the crash degraded to a silent no-op rather than a
    500, but the counts should still work correctly for the normal case)."""
    from blueprints.model_editing import _mesh_vertex_face_counts

    box = trimesh.creation.box(extents=(0.1, 0.1, 0.1))
    cloud = trimesh.PointCloud(vertices=np.random.rand(10, 3))
    assert hasattr(cloud, "vertices") and not hasattr(cloud, "faces")

    scene = trimesh.Scene()
    scene.add_geometry(box, node_name="box")
    scene.add_geometry(cloud, node_name="cloud")

    vertices, faces = _mesh_vertex_face_counts(scene)
    assert vertices == len(box.vertices)
    assert faces == len(box.faces)

    # A bare PointCloud (not wrapped in a Scene) also has no .faces.
    assert _mesh_vertex_face_counts(cloud) == (None, None)
