from models import ModelAnalyticsEvent, User, UserModel, db
from services.onboarding import checklist_state


def test_qr_shown_event_is_recorded_but_does_not_count_as_ar_launch(client):
    """UIA-13: the desktop "AR not supported" modal reports qr_shown, which must
    neither be rejected nor complete the onboarding "open it in AR" step."""
    owner = User(username="qrshownowner", email="qrshown@example.com")
    owner.set_password("password")
    db.session.add(owner)
    db.session.flush()
    model = UserModel(
        id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        filename="unused.glb",
        user_id=owner.id,
        visibility="unlisted",
    )
    db.session.add(model)
    db.session.commit()

    response = client.post(
        f"/api/models/{model.id}/events",
        json={"event_type": "qr_shown", "metadata": {"reason": "unsupported"}},
    )
    assert response.status_code == 202
    stored = ModelAnalyticsEvent.query.filter_by(model_id=model.id).one()
    assert stored.event_type == "qr_shown"
    steps = {s["key"]: s["done"] for s in checklist_state(owner.id)}
    assert steps["ar"] is False
