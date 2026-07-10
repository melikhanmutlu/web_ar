from datetime import datetime

import requests

from models import OrganizationDomain, User, UserModel, db


def _organization(client):
    owner = User(username="domainowner", email="domain@example.com")
    owner.set_password("password")
    db.session.add(owner)
    db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    response = client.post("/api/organizations", json={"name": "Acme Models"})
    return owner, response.get_json()["organization"]["id"]


def test_custom_domain_dns_verification_and_lifecycle(client, monkeypatch):
    _, organization_id = _organization(client)
    created = client.post(
        f"/api/organizations/{organization_id}/domains",
        json={"hostname": "models.example.com"},
    )
    assert created.status_code == 201
    domain_id = created.get_json()["id"]
    record = created.get_json()["dns_record"]

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self): return {"Answer": [{"data": f'"{record["value"]}"'}]}

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse())
    verified = client.post(
        f"/api/organizations/{organization_id}/domains/{domain_id}/verify"
    )
    assert verified.status_code == 200
    assert db.session.get(OrganizationDomain, domain_id).verified_at is not None
    listed = client.get(f"/api/organizations/{organization_id}/domains").get_json()["domains"]
    assert listed[0]["verified"] is True
    assert client.delete(
        f"/api/organizations/{organization_id}/domains/{domain_id}"
    ).status_code == 200


def test_verified_custom_host_serves_branded_public_portfolio(client):
    owner, organization_id = _organization(client)
    domain = OrganizationDomain(
        organization_id=organization_id,
        hostname="showroom.example.com",
        verification_token="verified",
        verified_at=datetime.utcnow(),
    )
    model = UserModel(
        id="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
        filename="unused.glb", user_id=owner.id,
        organization_id=organization_id, visibility="public",
        display_name="Showroom Chair",
        viewer_settings={"branding": {"name": "Acme XR"}},
    )
    db.session.add_all([domain, model])
    db.session.commit()
    response = client.get("/", headers={"Host": "showroom.example.com"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Acme XR" in html
    assert "Showroom Chair" in html


def test_custom_domain_rejects_local_or_invalid_hosts(client):
    _, organization_id = _organization(client)
    for hostname in ("localhost", "javascript:alert(1)", "127.0.0.1"):
        assert client.post(
            f"/api/organizations/{organization_id}/domains", json={"hostname": hostname}
        ).status_code == 400
