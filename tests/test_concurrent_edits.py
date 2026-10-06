"""Concurrent edits of one model: serialized by a per-model lock, uuid-named
temp/backup files (no same-second collisions)."""

import os
import threading

import pytest
import trimesh

from app import app, db
from models import UserModel
from services.model_lock import ModelBusyError, ModelEditLock
from tests.test_viewer_page import make_two_material_model

SCALE_2 = {"transform": {"scale": 2.0, "rotation": {"x": 0, "y": 0, "z": 0}}}


def _max_extent(glb_path):
    scene = trimesh.load(glb_path, force="scene")
    return float(max(scene.bounds[1] - scene.bounds[0]))


def _save_in_thread(model_id, results, index, barrier):
    with app.test_client() as thread_client:
        barrier.wait()
        resp = thread_client.post("/save_modifications", json={
            "model_id": model_id, "modifications": SCALE_2,
        })
        results[index] = (resp.status_code, resp.get_json())


def test_two_simultaneous_saves_both_apply_and_compose(client):
    model_id, glb_path = make_two_material_model(user_id=None)
    size_orig = _max_extent(glb_path)

    results = [None, None]
    barrier = threading.Barrier(2)
    threads = [threading.Thread(target=_save_in_thread, args=(model_id, results, i, barrier))
               for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    statuses = sorted(r[0] for r in results)
    assert statuses == [200, 200], results
    # scale 2 then 2 -> 4x: neither edit was lost
    assert _max_extent(glb_path) == pytest.approx(size_orig * 4.0, rel=1e-3)
    db.session.expire_all()
    assert db.session.get(UserModel, model_id).cumulative_scale == pytest.approx(4.0)
    # no leftover temp files
    leftovers = [f for f in os.listdir(os.path.dirname(glb_path)) if f.startswith("temp_")]
    assert leftovers == []


def test_backup_and_temp_names_do_not_collide_within_one_second(client, monkeypatch):
    import time as time_module

    model_id, glb_path = make_two_material_model(user_id=None)
    monkeypatch.setattr(time_module, "time", lambda: 1_700_000_000.0)
    for _ in range(2):
        resp = client.post("/save_modifications", json={"model_id": model_id, "modifications": SCALE_2})
        assert resp.status_code == 200, resp.get_json()
    backups = [f for f in os.listdir(os.path.dirname(glb_path)) if f.startswith("model_backup_")]
    assert len(backups) == 2


def test_edit_is_refused_with_409_while_another_edit_holds_the_lock(client, monkeypatch):
    model_id, glb_path = make_two_material_model(user_id=None)

    monkeypatch.setattr(ModelEditLock.__init__, "__defaults__", (0.2,))
    before = open(glb_path, "rb").read()
    with ModelEditLock(os.path.dirname(glb_path)):
        resp = client.post("/save_modifications", json={"model_id": model_id, "modifications": SCALE_2})
        assert resp.status_code == 409
        assert resp.get_json()["success"] is False
        resp = client.post("/api/versions/%s/restore/1" % model_id)
        assert resp.status_code == 409
    assert open(glb_path, "rb").read() == before
    with pytest.raises(ModelBusyError):
        with ModelEditLock(os.path.dirname(glb_path)):
            ModelEditLock(os.path.dirname(glb_path), timeout=0.1).acquire()
