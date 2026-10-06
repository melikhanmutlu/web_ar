"""Storage quota is a check-and-reserve under a per-user lock (T2-O2): uploads
that are still converting count against the quota, so concurrent requests can't
all pass the same stale 'used' figure."""

import io
import threading

import trimesh

import app as app_module
from blueprints import upload as upload_module
from models import ConversionJob, User, UserModel, db
from services import storage_quota, upload_pipeline


def _glb_bytes():
    return bytes(trimesh.creation.box(extents=(0.1, 0.2, 0.3)).export(file_type="glb"))


def _login(client, name):
    user = User.query.filter_by(username=name).first()
    if user is None:
        user = User(username=name, email=f"{name}@test.com")
        user.set_password("testpassword123")
        db.session.add(user)
        db.session.commit()
    client.post("/login", data={"username": name, "password": "testpassword123"})
    return user


def _tiny_quota(monkeypatch, nbytes):
    """Quota of exactly `nbytes` (MB granularity is too coarse for fixtures)."""
    monkeypatch.setattr(storage_quota, "_storage_quota_bytes", lambda user=None: nbytes)


def _upload(client, data):
    return client.post(
        "/upload_model",
        data={"file": (io.BytesIO(data), "box.glb"), "compression": "none"},
        content_type="multipart/form-data",
    )


def test_in_flight_upload_counts_against_quota(client, monkeypatch):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    data = _glb_bytes()
    _tiny_quota(monkeypatch, int(len(data) * 1.5))
    user = _login(client, "resv1")

    first = _upload(client, data)
    assert first.status_code == 202
    job = db.session.get(ConversionJob, first.get_json()["job_id"])
    assert job.reserved_bytes == len(data)
    assert storage_quota.reserved_bytes_for(user.id) == len(data)

    # The second upload only fits if the first (still pending, no UserModel yet)
    # were ignored. Skip the advisory pre-check to hit the locked reservation.
    monkeypatch.setattr(upload_module, "_check_storage_quota", lambda *a, **k: None)
    second = _upload(client, data)
    assert second.status_code == 413
    assert ConversionJob.query.filter_by(user_id=user.id).count() == 1


def test_reservation_is_released_when_job_finishes(client, monkeypatch):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    data = _glb_bytes()
    user = _login(client, "resv2")
    resp = _upload(client, data)
    job = db.session.get(ConversionJob, resp.get_json()["job_id"])
    assert storage_quota.reserved_bytes_for(user.id) == len(data)
    for status in ("failed", "dead_letter", "completed"):
        job.status = status
        db.session.commit()
        assert storage_quota.reserved_bytes_for(user.id) == 0


def test_concurrent_uploads_cannot_all_pass_the_quota(client, monkeypatch):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    # Every request passes the early advisory check (stale view of usage) ...
    monkeypatch.setattr(upload_module, "_check_storage_quota", lambda *a, **k: None)
    data = _glb_bytes()
    # ... but only two files fit.
    _tiny_quota(monkeypatch, len(data) * 2 + 10)
    user = _login(client, "resv3")
    user_id = user.id

    statuses, barrier = [], threading.Barrier(4)

    def worker():
        with app_module.app.test_client() as c:
            c.post("/login", data={"username": "resv3", "password": "testpassword123"})
            barrier.wait(timeout=20)
            statuses.append(_upload(c, data).status_code)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)

    assert sorted(statuses) == [202, 202, 413, 413], statuses
    with app_module.app.app_context():
        assert ConversionJob.query.filter_by(user_id=user_id).count() == 2


def test_batch_reserves_per_file(client, monkeypatch):
    monkeypatch.setattr(upload_pipeline, "JOB_QUEUE_ENABLED", True)
    monkeypatch.setattr(upload_module, "_check_storage_quota", lambda *a, **k: None)
    data = _glb_bytes()
    _tiny_quota(monkeypatch, len(data) + 10)
    user = _login(client, "resv4")
    resp = client.post(
        "/api/uploads/batch",
        data={"files": [(io.BytesIO(data), "a.glb"), (io.BytesIO(data), "b.glb")]},
        content_type="multipart/form-data",
    )
    body = resp.get_json()
    assert resp.status_code == 202
    assert len(body["jobs"]) == 1
    assert [e["error"] for e in body["errors"]] == ["Storage quota exceeded"]
    assert storage_quota.reserved_bytes_for(user.id) == len(data)


def test_register_glb_enforces_quota_under_lock(client, monkeypatch, tmp_path):
    monkeypatch.setattr(upload_pipeline, "_enqueue_internal_job", lambda *a, **k: None)
    data = _glb_bytes()
    glb = tmp_path / "m.glb"
    glb.write_bytes(data)
    user = _login(client, "resv5")
    first = upload_pipeline.register_glb_as_model(str(glb), user_id=user.id, source="scene",
                                                  enforce_quota=True)
    assert first.user_id == user.id
    _tiny_quota(monkeypatch, db.session.get(UserModel, first.id).file_size + 10)
    try:
        upload_pipeline.register_glb_as_model(str(glb), user_id=user.id, source="scene",
                                              enforce_quota=True)
        raise AssertionError("expected StorageQuotaExceeded")
    except upload_pipeline.StorageQuotaExceeded:
        pass
    assert UserModel.query.filter_by(user_id=user.id).count() == 1
