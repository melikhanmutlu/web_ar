"""Phase B: Meshy balance API + admin dashboard KPI card."""

import pytest

import admin as admin_module
import ai_generator
from app import db
from models import User


@pytest.fixture
def admin_user(client):
    user = User(username="balanceadmin", email="balance@test.com", is_admin=True)
    user.set_password("adminpassword")
    db.session.add(user)
    db.session.commit()
    return user


def login(client, username, password):
    return client.post("/login", data={"username": username, "password": password},
                       follow_redirects=False)


@pytest.fixture(autouse=True)
def reset_balance_cache():
    admin_module._meshy_balance_cache.update(at=0.0, value=None, error=None)
    yield
    admin_module._meshy_balance_cache.update(at=0.0, value=None, error=None)


def test_dashboard_renders_when_meshy_not_configured(client, admin_user, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: False)
    login(client, "balanceadmin", "adminpassword")
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"meshy credit balance" in resp.data


def test_dashboard_shows_balance_and_does_not_refetch_within_ttl(client, admin_user, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    calls = {"n": 0}

    def fake_get_balance():
        calls["n"] += 1
        return {"balance": 1234, "raw": {}}

    monkeypatch.setattr(ai_generator, "get_balance", fake_get_balance)
    login(client, "balanceadmin", "adminpassword")

    r1 = client.get("/admin/")
    assert b"1234" in r1.data
    r2 = client.get("/admin/")
    assert b"1234" in r2.data
    assert calls["n"] == 1  # second load served from cache, no second Meshy call


def test_dashboard_survives_meshy_outage(client, admin_user, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)

    def boom():
        raise ai_generator.MeshyError("Meshy error 500")

    monkeypatch.setattr(ai_generator, "get_balance", boom)
    login(client, "balanceadmin", "adminpassword")
    resp = client.get("/admin/")
    assert resp.status_code == 200
    assert b"\xe2\x80\x94" in resp.data or b"&mdash;" in resp.data or b"meshy credit balance" in resp.data


def test_refresh_balance_requires_admin(client):
    resp = client.post("/admin/ai-jobs/refresh-balance")
    assert resp.status_code == 302  # anonymous -> redirected to login

    user = User(username="plainuser", email="plain@test.com")
    user.set_password("plainpassword")
    db.session.add(user)
    db.session.commit()
    login(client, "plainuser", "plainpassword")
    resp = client.post("/admin/ai-jobs/refresh-balance")
    assert resp.status_code == 404  # logged in but not admin -> hidden


def test_refresh_balance_bypasses_ttl(client, admin_user, monkeypatch):
    monkeypatch.setattr(ai_generator, "is_configured", lambda: True)
    calls = {"n": 0, "value": 100}

    def fake_get_balance():
        calls["n"] += 1
        calls["value"] += 1
        return {"balance": calls["value"], "raw": {}}

    monkeypatch.setattr(ai_generator, "get_balance", fake_get_balance)
    login(client, "balanceadmin", "adminpassword")

    client.get("/admin/")  # primes the cache
    assert calls["n"] == 1

    resp = client.post("/admin/ai-jobs/refresh-balance")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["success"] is True
    assert calls["n"] == 2  # force=True bypassed the TTL
    assert body["balance"] == 102
