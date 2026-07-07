"""Admin panel coverage for RigAnimationJob: the /admin/rig-jobs list,
mark-failed/delete actions, CSV export, dashboard KPIs, and the
search/filter additions to the jobs/ai-jobs/rig-jobs list pages."""

import uuid

import pytest

from app import app, db
from models import AIGenerationJob, ConversionJob, RigAnimationJob, User, UserModel


@pytest.fixture
def admin_user(client):
    user = User(username="rigadmin", email="rigadmin@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def owner(client):
    user = User(username="rigowner2", email="rigowner2@test.com")
    user.set_password("testpassword")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=False)


def make_model(user_id=None, model_id=None):
    model_id = model_id or str(uuid.uuid4())
    model = UserModel(id=model_id, filename=f"{model_id}/model.glb", file_size=10,
                      file_type="glb", user_id=user_id)
    db.session.add(model)
    db.session.commit()
    return model


def make_rig_job(user_id, model_id, status="generating", stage="rigging"):
    job = RigAnimationJob(id=str(uuid.uuid4()), model_id=model_id, user_id=user_id,
                          height_meters=1.7, animation_action_ids=[0, 1],
                          meshy_rig_id="rig-1", stage=stage, status=status, progress=30)
    db.session.add(job)
    db.session.commit()
    return job


# --------------------------------------------------------------------------- #
#  List page + filters
# --------------------------------------------------------------------------- #

def test_rig_jobs_page_lists_and_filters_by_status(client, admin_user, owner):
    model = make_model(user_id=owner.id)
    ready = make_rig_job(owner.id, model.id, status="ready", stage="animating")
    failed = make_rig_job(owner.id, model.id, status="failed", stage="rigging")

    login(client, "rigadmin", "adminpassword")
    resp = client.get("/admin/rig-jobs")
    assert resp.status_code == 200
    assert ready.id[:8].encode() in resp.data
    assert failed.id[:8].encode() in resp.data

    resp = client.get("/admin/rig-jobs?status=failed")
    assert failed.id[:8].encode() in resp.data
    assert ready.id[:8].encode() not in resp.data


def test_rig_jobs_search_by_id(client, admin_user, owner):
    model = make_model(user_id=owner.id)
    job = make_rig_job(owner.id, model.id)
    other = make_rig_job(owner.id, model.id)

    login(client, "rigadmin", "adminpassword")
    resp = client.get(f"/admin/rig-jobs?q={job.id}")
    assert job.id[:8].encode() in resp.data
    assert other.id[:8].encode() not in resp.data


def test_rig_jobs_model_link_and_result_link(client, admin_user, owner):
    model = make_model(user_id=owner.id)
    job = make_rig_job(owner.id, model.id, status="ready")
    job.result_model_id = str(uuid.uuid4())
    db.session.commit()

    login(client, "rigadmin", "adminpassword")
    resp = client.get("/admin/rig-jobs")
    assert f"/admin/models/{model.id}".encode() in resp.data


# --------------------------------------------------------------------------- #
#  Mark-failed / delete
# --------------------------------------------------------------------------- #

def test_mark_rig_job_failed(client, admin_user, owner):
    model = make_model(user_id=owner.id)
    job = make_rig_job(owner.id, model.id)
    login(client, "rigadmin", "adminpassword")

    resp = client.post(f"/admin/rig-jobs/{job.id}/mark-failed")
    assert resp.status_code == 200
    db.session.refresh(job)
    assert job.status == "failed"

    # already-finished jobs can't be re-marked
    resp = client.post(f"/admin/rig-jobs/{job.id}/mark-failed")
    assert resp.status_code == 400


def test_delete_rig_job(client, admin_user, owner):
    model = make_model(user_id=owner.id)
    job = make_rig_job(owner.id, model.id)
    login(client, "rigadmin", "adminpassword")

    resp = client.post(f"/admin/rig-jobs/{job.id}/delete")
    assert resp.status_code == 200
    assert db.session.get(RigAnimationJob, job.id) is None


# --------------------------------------------------------------------------- #
#  CSV export
# --------------------------------------------------------------------------- #

def test_export_rig_jobs_csv(client, admin_user, owner):
    model = make_model(user_id=owner.id)
    make_rig_job(owner.id, model.id)
    login(client, "rigadmin", "adminpassword")

    resp = client.get("/admin/rig-jobs/export.csv")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "animation_count" in body
    assert "1.7" in body


def test_export_models_csv_includes_source(client, admin_user, owner):
    model = UserModel(id=str(uuid.uuid4()), filename="x/model.glb", file_size=10,
                      file_type="glb", user_id=owner.id, source="ai-text")
    db.session.add(model)
    db.session.commit()
    login(client, "rigadmin", "adminpassword")

    resp = client.get("/admin/models/export.csv")
    body = resp.data.decode()
    assert "source" in body.splitlines()[0]
    assert "ai-text" in body


def test_export_ai_jobs_csv_includes_options(client, admin_user, owner):
    job = AIGenerationJob(id=str(uuid.uuid4()), user_id=owner.id, kind="text",
                          prompt="a vase", stage="preview", status="generating",
                          options={"seed": 42})
    db.session.add(job)
    db.session.commit()
    login(client, "rigadmin", "adminpassword")

    resp = client.get("/admin/ai-jobs/export.csv")
    body = resp.data.decode()
    assert "options" in body.splitlines()[0]
    assert "42" in body


# --------------------------------------------------------------------------- #
#  Dashboard KPIs + stale detection
# --------------------------------------------------------------------------- #

def test_dashboard_shows_rig_kpis_and_stale_warning(client, admin_user, owner):
    from datetime import datetime, timedelta

    model = make_model(user_id=owner.id)
    make_rig_job(owner.id, model.id, status="ready")
    make_rig_job(owner.id, model.id, status="failed")
    stale = make_rig_job(owner.id, model.id, status="generating")
    RigAnimationJob.query.filter_by(id=stale.id).update(
        {"updated_at": datetime.utcnow() - timedelta(hours=1)}
    )
    db.session.commit()

    login(client, "rigadmin", "adminpassword")
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"rig &amp; animate models" in resp.data
    assert b"stale rig jobs" in resp.data


# --------------------------------------------------------------------------- #
#  Model detail shows rig jobs
# --------------------------------------------------------------------------- #

def test_model_detail_lists_rig_jobs(client, admin_user, owner):
    model = make_model(user_id=owner.id)
    make_rig_job(owner.id, model.id)
    login(client, "rigadmin", "adminpassword")

    resp = client.get(f"/admin/models/{model.id}")
    assert resp.status_code == 200
    assert b"rig &amp; animate jobs" in resp.data
    assert b"1.7m" in resp.data


# --------------------------------------------------------------------------- #
#  ai-jobs / jobs search + user filter
# --------------------------------------------------------------------------- #

def test_ai_jobs_filter_by_user(client, admin_user, owner):
    other = User(username="rigother2", email="rigother2@test.com")
    other.set_password("x")
    db.session.add(other)
    db.session.commit()

    mine = AIGenerationJob(id=str(uuid.uuid4()), user_id=owner.id, kind="text",
                           prompt="mine", stage="preview", status="generating")
    theirs = AIGenerationJob(id=str(uuid.uuid4()), user_id=other.id, kind="text",
                             prompt="theirs", stage="preview", status="generating")
    db.session.add_all([mine, theirs])
    db.session.commit()

    login(client, "rigadmin", "adminpassword")
    resp = client.get(f"/admin/ai-jobs?user={owner.id}")
    assert b"mine" in resp.data
    assert b"theirs" not in resp.data


def test_ai_jobs_search_by_prompt(client, admin_user, owner):
    job = AIGenerationJob(id=str(uuid.uuid4()), user_id=owner.id, kind="text",
                          prompt="a very specific unicorn", stage="preview",
                          status="generating")
    other = AIGenerationJob(id=str(uuid.uuid4()), user_id=owner.id, kind="text",
                            prompt="a boring box", stage="preview", status="generating")
    db.session.add_all([job, other])
    db.session.commit()

    login(client, "rigadmin", "adminpassword")
    resp = client.get("/admin/ai-jobs?q=unicorn")
    assert b"unicorn" in resp.data
    assert b"boring box" not in resp.data


def test_jobs_search_by_id(client, admin_user, owner):
    job = ConversionJob(id=str(uuid.uuid4()), status="pending", user_id=owner.id)
    other = ConversionJob(id=str(uuid.uuid4()), status="pending", user_id=owner.id)
    db.session.add_all([job, other])
    db.session.commit()

    login(client, "rigadmin", "adminpassword")
    resp = client.get(f"/admin/jobs?q={job.id}")
    assert job.id[:8].encode() in resp.data
    assert other.id[:8].encode() not in resp.data


def test_user_detail_links_to_ai_jobs(client, admin_user, owner):
    login(client, "rigadmin", "adminpassword")
    resp = client.get(f"/admin/users/{owner.id}")
    assert f"/admin/ai-jobs?user={owner.id}".encode() in resp.data


# --------------------------------------------------------------------------- #
#  Audit log target links
# --------------------------------------------------------------------------- #

def test_audit_log_links_ai_job_and_rig_job_targets(client, admin_user, owner):
    from models import AdminAuditLog

    ai_job_id = str(uuid.uuid4())
    rig_job_id = str(uuid.uuid4())
    db.session.add_all([
        AdminAuditLog(actor_id=admin_user.id, action="ai_job.mark_failed",
                      target_type="ai_job", target_id=ai_job_id),
        AdminAuditLog(actor_id=admin_user.id, action="rig_job.mark_failed",
                      target_type="rig_job", target_id=rig_job_id),
    ])
    db.session.commit()

    login(client, "rigadmin", "adminpassword")
    resp = client.get("/admin/audit-log")
    assert f"/admin/ai-jobs?q={ai_job_id}".encode() in resp.data
    assert f"/admin/rig-jobs?q={rig_job_id}".encode() in resp.data
