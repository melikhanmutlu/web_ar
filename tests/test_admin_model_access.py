"""Admins must get full owner-parity on any model's viewer page (view +
edit UI), while a regular non-owner is still blocked from a private model."""

from models import User, UserModel, db
from tests.test_viewer_page import login, make_two_material_model, make_user


def make_admin(username, email):
    u = User(username=username, email=email, is_admin=True)
    u.set_password("testpassword123")
    db.session.add(u)
    db.session.commit()
    return u


def test_regular_user_cannot_view_someone_elses_private_model(client):
    owner = make_user("privowner", "privowner@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)
    model = db.session.get(UserModel, model_id)
    model.visibility = "private"
    db.session.commit()

    intruder = make_user("intruder", "intruder@test.com")
    login(client, "intruder", "testpassword123")
    resp = client.get(f"/view/{model_id}")
    assert resp.status_code == 403


def test_admin_gets_full_owner_parity_on_someone_elses_private_model(client):
    owner = make_user("privowner2", "privowner2@test.com")
    model_id, _ = make_two_material_model(user_id=owner.id)
    model = db.session.get(UserModel, model_id)
    model.visibility = "private"
    db.session.commit()

    make_admin("admintester", "admintester@test.com")
    login(client, "admintester", "testpassword123")
    resp = client.get(f"/view/{model_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Undo/Redo are only rendered when can_edit is true (blueprints/viewer.py).
    assert 'id="undoButton"' in body
    assert 'id="redoButton"' in body
