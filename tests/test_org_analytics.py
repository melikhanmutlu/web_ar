"""Org-wide analytics rollup and CSV export."""
from models import ModelAnalyticsEvent, OrganizationMember, User, UserModel, db


def _org_with_model(client):
    owner = User(username="analyticsowner", email="analytics@example.com", plan="business")
    owner.set_password("password")
    db.session.add(owner)
    db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    organization_id = client.post(
        "/api/organizations", json={"name": "Metrics Co"}
    ).get_json()["organization"]["id"]
    model = UserModel(
        id="a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1",
        filename="unused.glb", display_name="Tracked Chair",
        user_id=owner.id, organization_id=organization_id, visibility="public",
    )
    db.session.add(model)
    db.session.add_all([
        ModelAnalyticsEvent(model_id=model.id, event_type="view", visitor_hash="v1" + "0" * 62),
        ModelAnalyticsEvent(model_id=model.id, event_type="view", visitor_hash="v2" + "0" * 62),
        ModelAnalyticsEvent(model_id=model.id, event_type="ar_launch", visitor_hash="v1" + "0" * 62),
    ])
    db.session.commit()
    return owner, organization_id, model


def test_org_analytics_rolls_up_across_models(client):
    _, organization_id, model = _org_with_model(client)
    response = client.get(f"/api/organizations/{organization_id}/analytics")
    assert response.status_code == 200
    body = response.get_json()
    assert body["model_count"] == 1
    assert body["totals"]["view"] == 2
    assert body["totals"]["ar_launch"] == 1
    assert body["unique_visitors"] == 2
    assert body["models"][0]["model_id"] == model.id
    assert body["models"][0]["unique_visitors"] == 2


def test_org_analytics_csv_export(client):
    _, organization_id, model = _org_with_model(client)
    response = client.get(f"/api/organizations/{organization_id}/analytics/export")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    text = response.get_data(as_text=True)
    assert "model_id,name" in text
    assert model.id in text
    assert "Tracked Chair" in text


def test_org_analytics_requires_admin_role(client):
    owner, organization_id, _ = _org_with_model(client)
    viewer = User(username="metricsviewer", email="mv@example.com")
    viewer.set_password("password")
    db.session.add(viewer)
    db.session.commit()
    db.session.add(OrganizationMember(
        organization_id=organization_id, user_id=viewer.id, role="viewer"
    ))
    db.session.commit()
    client.post("/logout")
    client.post("/login", data={"username": viewer.username, "password": "password"})
    assert client.get(f"/api/organizations/{organization_id}/analytics").status_code == 403
    assert client.get(f"/api/organizations/{organization_id}/analytics/export").status_code == 403
