"""DB-level referential integrity: ondelete rules + SQLite PRAGMA hook.

These use raw SQL deletes on purpose — ORM delete-orphan cascades are
covered elsewhere; this proves the database itself stays consistent when
rows are removed outside the ORM (bulk jobs, psql, another service).
"""
from sqlalchemy import text
from werkzeug.security import generate_password_hash

from models import (
    ApiToken,
    CameraView,
    Folder,
    ModelAnalyticsEvent,
    ModelHotspot,
    ModelShareLink,
    ModelVersion,
    User,
    UserModel,
    db,
)


def _make_user(name):
    user = User(username=name, email=f"{name}@test.com")
    user.set_password("pw")
    db.session.add(user)
    db.session.flush()
    return user


def test_sqlite_connections_enforce_foreign_keys(client):
    assert db.session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_raw_sql_model_delete_cascades_children(client):
    owner = _make_user("cascade-owner")
    model = UserModel(id="raw-delete-model", filename="m.glb", user_id=owner.id)
    db.session.add(model)
    db.session.flush()
    db.session.add_all([
        ModelVersion(model_id=model.id, version_number=1, filename="v1.glb",
                     operation_type="upload"),
        ModelHotspot(model_id=model.id, hotspot_id="h1", title="t",
                     position_x=0, position_y=0, position_z=0),
        ModelShareLink(model_id=model.id, token_digest="digest-1"),
        ModelAnalyticsEvent(model_id=model.id, event_type="view"),
        CameraView(model_id=model.id, name="front", orbit_theta=0,
                   orbit_phi=0, orbit_radius=1),
    ])
    db.session.commit()

    db.session.execute(text("DELETE FROM user_model WHERE id = 'raw-delete-model'"))
    db.session.commit()

    assert ModelVersion.query.count() == 0
    assert ModelHotspot.query.count() == 0
    assert ModelShareLink.query.count() == 0
    assert ModelAnalyticsEvent.query.count() == 0
    assert CameraView.query.count() == 0


def test_raw_sql_user_delete_nulls_models_and_removes_owned_records(client):
    owner = _make_user("departing-user")
    model = UserModel(id="survivor-model", filename="m.glb", user_id=owner.id)
    folder = Folder(name="docs", slug="docs-abc1", user_id=owner.id)
    token = ApiToken(user_id=owner.id, name="ci",
                     token_prefix="arv_x", token_digest=generate_password_hash("t")[:64])
    db.session.add_all([model, folder, token])
    db.session.commit()

    db.session.execute(text('DELETE FROM "user" WHERE id = :uid'), {"uid": owner.id})
    db.session.commit()

    # The model survives as anonymous; folder and API token go with the user.
    assert db.session.get(UserModel, "survivor-model").user_id is None
    assert Folder.query.count() == 0
    assert ApiToken.query.count() == 0
