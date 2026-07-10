from models import ModelAnalyticsEvent, User, UserModel, db


def _analytics_model():
    owner = User(username="analyticsowner", email="analytics@example.com")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model = UserModel(
        id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        filename="unused.glb",
        user_id=owner.id,
        visibility="unlisted",
    )
    db.session.add(model)
    db.session.commit()
    return owner, model


def test_privacy_safe_events_and_owner_summary(client):
    owner, model = _analytics_model()
    headers = {
        "Origin": "http://localhost",
        "Referer": "https://shop.example/products/chair",
        "User-Agent": "Mobile Safari iPhone",
    }
    assert client.post(
        f"/api/models/{model.id}/events",
        json={"event_type": "ar_launch", "metadata": {"source": "viewer"}},
        headers=headers,
    ).status_code == 202
    assert client.post(
        f"/api/models/{model.id}/events",
        json={"event_type": "qr_open"}, headers=headers,
    ).status_code == 202

    events = ModelAnalyticsEvent.query.filter_by(model_id=model.id).all()
    assert len(events) == 2
    assert events[0].visitor_hash == events[1].visitor_hash
    assert len(events[0].visitor_hash) == 64
    assert events[0].referrer_domain == "shop.example"
    assert events[0].device_type == "mobile"

    client.post("/login", data={"username": owner.username, "password": "password"})
    response = client.get(f"/api/models/{model.id}/analytics?days=7")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["totals"] == {"ar_launch": 1, "qr_open": 1}
    assert payload["unique_visitors"] == 1
    assert payload["referrers"][0]["domain"] == "shop.example"


def test_analytics_rejects_unknown_events_and_non_owner_summary(client):
    _, model = _analytics_model()
    assert client.post(
        f"/api/models/{model.id}/events", json={"event_type": "arbitrary"}
    ).status_code == 400
    stranger = User(username="stranger", email="stranger@example.com")
    stranger.set_password("password")
    db.session.add(stranger)
    db.session.commit()
    client.post("/login", data={"username": stranger.username, "password": "password"})
    assert client.get(f"/api/models/{model.id}/analytics").status_code == 403
