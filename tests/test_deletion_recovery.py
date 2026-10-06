"""Authorization matrix + on-disk effects for the destructive/recovery
endpoints in blueprints/models_crud.py (OPS-21): delete_model (trash + permanent
purge), delete_all_models, restore_model, move_model, move_selected_models,
delete_folder, rename_folder.

For every endpoint: owner succeeds, another user / an org member who is not the
owner get 403/404, anonymous is bounced to login, and in every denied case
nothing (DB row, files, folder) changes.
"""

import uuid
from datetime import datetime

import pytest

from app import app, db
from models import (
    Folder,
    ModelLike,
    ModelSave,
    Organization,
    OrganizationMember,
    User,
    UserModel,
)
from services.storage_quota import _storage_usage_for


def _login(client, username, password="pw"):
    return client.post("/login", data={"username": username, "password": password})


def _user(name):
    user = User(username=name, email=f"{name}@test.com")
    user.set_password("pw")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """Point storage at a throwaway tree so purge assertions hit real files."""
    roots = {}
    for key, name in (("CONVERTED_FOLDER", "converted"),
                      ("UPLOAD_FOLDER", "uploads"),
                      ("QR_FOLDER", "qr")):
        path = tmp_path / name
        path.mkdir()
        monkeypatch.setitem(app.config, key, str(path))
        roots[key] = path
    return roots


@pytest.fixture
def world(client, dirs):
    """owner, stranger, org editor (member of owner's org)."""
    owner, stranger, member = _user("owner"), _user("stranger"), _user("orgmember")
    org = Organization(name="Acme", slug="acme", created_by=owner.id)
    db.session.add(org)
    db.session.flush()
    db.session.add_all([
        OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner"),
        OrganizationMember(organization_id=org.id, user_id=member.id, role="editor"),
    ])
    db.session.commit()
    return type("World", (), dict(owner=owner, stranger=stranger, member=member,
                                  org=org, dirs=dirs))


class _Made:
    """A created model plus the on-disk paths we assert on."""

    def __init__(self, model, conv, upl, qr):
        self.id = model.id
        self.conv, self.upl, self.qr = conv, upl, qr


def _make_model(world, owner=None, size=1000, trashed=False, organization=False,
                with_files=True, folder_id=None):
    owner = owner or world.owner
    mid = str(uuid.uuid4())
    qr_name = f"{mid}.png"
    conv = world.dirs["CONVERTED_FOLDER"] / mid
    upl = world.dirs["UPLOAD_FOLDER"] / mid
    qr = world.dirs["QR_FOLDER"] / qr_name
    if with_files:
        conv.mkdir()
        (conv / "model.glb").write_bytes(b"glTF")
        (conv / "thumbnail.png").write_bytes(b"png")
        upl.mkdir()
        (upl / "original.stl").write_bytes(b"solid")
        qr.write_bytes(b"qr")
    model = UserModel(
        id=mid, filename=str(conv / "model.glb"), file_size=size, file_type="glb",
        user_id=owner.id, qr_code=qr_name, folder_id=folder_id,
        organization_id=world.org.id if organization else None,
        deleted_at=datetime.utcnow() if trashed else None,
    )
    db.session.add(model)
    db.session.commit()
    return _Made(model, conv, upl, qr)


def _files_present(made):
    return (made.conv.exists(), made.upl.exists(), made.qr.exists())


def _exists(model_id):
    db.session.expire_all()
    return db.session.get(UserModel, model_id) is not None


def _folder(user, name="Folder", parent_id=None):
    folder = Folder(name=name, slug=f"{name.lower()}-{uuid.uuid4().hex[:6]}",
                    user_id=user.id, parent_id=parent_id)
    db.session.add(folder)
    db.session.commit()
    return folder


def _folder_of(model_id):
    db.session.expire_all()
    return db.session.get(UserModel, model_id).folder_id


ALL = (True, True, True)
NONE = (False, False, False)


# --------------------------------------------------------------------------
# delete_model
# --------------------------------------------------------------------------

def test_delete_model_default_is_soft_delete_and_keeps_files(client, world):
    model = _make_model(world)
    _login(client, "owner")
    resp = client.post(f"/delete_model/{model.id}")
    assert resp.status_code == 200 and resp.get_json()["trashed"] is True
    db.session.expire_all()
    assert db.session.get(UserModel, model.id).deleted_at is not None
    assert _files_present(model) == ALL
    # Trashed models still count toward storage (they are still on disk).
    assert _storage_usage_for(world.owner.id) == 1000


def test_delete_model_permanent_removes_files_row_and_quota(client, world):
    model = _make_model(world, size=1000)
    keep = _make_model(world, size=250)
    db.session.add_all([ModelLike(model_id=model.id, user_id=world.stranger.id),
                        ModelSave(model_id=model.id, user_id=world.stranger.id)])
    db.session.commit()
    assert _storage_usage_for(world.owner.id) == 1250

    _login(client, "owner")
    resp = client.post(f"/delete_model/{model.id}", json={"permanent": True})
    assert resp.status_code == 200

    assert not _exists(model.id)
    assert _files_present(model) == NONE
    assert ModelLike.query.filter_by(model_id=model.id).count() == 0
    assert ModelSave.query.filter_by(model_id=model.id).count() == 0
    # The other model is untouched and quota reflects only it.
    assert _exists(keep.id) and _files_present(keep) == ALL
    assert _storage_usage_for(world.owner.id) == 250


def test_delete_model_already_in_trash_is_purged_without_flag(client, world):
    model = _make_model(world, trashed=True)
    _login(client, "owner")
    assert client.post(f"/delete_model/{model.id}").status_code == 200
    assert not _exists(model.id)
    assert _files_present(model) == NONE


def test_delete_model_purge_tolerates_missing_files(client, world):
    model = _make_model(world, with_files=False)
    _login(client, "owner")
    resp = client.post(f"/delete_model/{model.id}", json={"permanent": True})
    assert resp.status_code == 200
    assert not _exists(model.id)


def test_delete_model_unknown_id_is_404(client, world):
    _login(client, "owner")
    assert client.post(f"/delete_model/{uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize("actor", ["stranger", "orgmember"])
@pytest.mark.parametrize("payload", [None, {"permanent": True}])
def test_delete_model_non_owner_denied_and_nothing_changes(client, world, actor, payload):
    # Org membership (even editor) does not confer delete rights.
    model = _make_model(world, trashed=True, organization=True)
    _login(client, actor)
    resp = client.post(f"/delete_model/{model.id}", json=payload)
    assert resp.status_code in (403, 404)
    assert _exists(model.id)
    assert _files_present(model) == ALL
    assert _storage_usage_for(world.owner.id) == 1000


def test_delete_model_anonymous_redirected_and_nothing_changes(client, world):
    model = _make_model(world, trashed=True)
    resp = client.post(f"/delete_model/{model.id}", json={"permanent": True})
    assert resp.status_code in (302, 401)
    assert _exists(model.id)
    assert _files_present(model) == ALL


# --------------------------------------------------------------------------
# delete_all_models (permanent purge of EVERYTHING the caller owns)
# --------------------------------------------------------------------------

def test_delete_all_models_purges_only_callers_models(client, world):
    mine = [_make_model(world, size=100), _make_model(world, size=200, trashed=True)]
    theirs = _make_model(world, owner=world.stranger, size=999)
    _login(client, "owner")
    resp = client.post("/delete_all_models")
    assert resp.status_code == 200
    for model in mine:
        assert not _exists(model.id)
        assert _files_present(model) == NONE
    assert _exists(theirs.id) and _files_present(theirs) == ALL
    assert _storage_usage_for(world.owner.id) == 0
    assert _storage_usage_for(world.stranger.id) == 999


def test_delete_all_models_anonymous_changes_nothing(client, world):
    model = _make_model(world)
    resp = client.post("/delete_all_models")
    assert resp.status_code in (302, 401)
    assert _exists(model.id) and _files_present(model) == ALL


def test_delete_selected_models_skips_foreign_ids(client, world):
    mine = _make_model(world)
    theirs = _make_model(world, owner=world.stranger)
    _login(client, "owner")
    client.post("/delete_selected_models", json={"model_ids": [mine.id, theirs.id]})
    assert not _exists(mine.id)
    assert _exists(theirs.id) and _files_present(theirs) == ALL


# --------------------------------------------------------------------------
# restore_model
# --------------------------------------------------------------------------

def test_restore_model_owner_brings_model_back_from_trash(client, world):
    model = _make_model(world, trashed=True)
    _login(client, "owner")
    resp = client.post(f"/restore_model/{model.id}")
    assert resp.status_code == 200 and resp.get_json()["success"] is True
    db.session.expire_all()
    assert db.session.get(UserModel, model.id).deleted_at is None
    assert _files_present(model) == ALL


def test_restore_model_resets_folder_deleted_while_in_trash(client, world):
    folder = _folder(world.owner)
    model = _make_model(world, trashed=True, folder_id=folder.id)
    _login(client, "owner")
    assert client.post(f"/delete_folder/{folder.id}").status_code == 200
    assert client.post(f"/restore_model/{model.id}").status_code == 200
    db.session.expire_all()
    restored = db.session.get(UserModel, model.id)
    assert restored.deleted_at is None and restored.folder_id is None


def test_restore_model_not_in_trash_is_noop(client, world):
    model = _make_model(world)
    _login(client, "owner")
    resp = client.post(f"/restore_model/{model.id}")
    assert resp.status_code == 200
    assert "not in trash" in resp.get_json()["message"]


def test_restore_model_unknown_id_404(client, world):
    _login(client, "owner")
    assert client.post(f"/restore_model/{uuid.uuid4()}").status_code == 404


@pytest.mark.parametrize("actor", ["stranger", "orgmember"])
def test_restore_model_non_owner_denied_and_stays_trashed(client, world, actor):
    model = _make_model(world, trashed=True, organization=True)
    _login(client, actor)
    assert client.post(f"/restore_model/{model.id}").status_code in (403, 404)
    db.session.expire_all()
    assert db.session.get(UserModel, model.id).deleted_at is not None


def test_restore_model_anonymous_denied(client, world):
    model = _make_model(world, trashed=True)
    assert client.post(f"/restore_model/{model.id}").status_code in (302, 401)
    db.session.expire_all()
    assert db.session.get(UserModel, model.id).deleted_at is not None


def test_trash_then_restore_then_purge_roundtrip(client, world):
    model = _make_model(world, size=500)
    _login(client, "owner")
    client.post(f"/delete_model/{model.id}")
    client.post(f"/restore_model/{model.id}")
    db.session.expire_all()
    assert db.session.get(UserModel, model.id).deleted_at is None
    client.post(f"/delete_model/{model.id}")
    client.post(f"/delete_model/{model.id}")  # second delete on a trashed model purges
    assert not _exists(model.id)
    assert _files_present(model) == NONE
    assert _storage_usage_for(world.owner.id) == 0


# --------------------------------------------------------------------------
# move_model / move_selected_models
# --------------------------------------------------------------------------

def test_move_model_owner_moves_into_and_out_of_folder(client, world):
    folder = _folder(world.owner)
    model = _make_model(world)
    _login(client, "owner")
    assert client.post("/move_model", json={"model_id": model.id,
                                            "folder_id": str(folder.id)}).status_code == 200
    assert _folder_of(model.id) == folder.id
    assert client.post("/move_model", json={"model_id": model.id,
                                            "folder_id": None}).status_code == 200
    assert _folder_of(model.id) is None


@pytest.mark.parametrize("actor", ["stranger", "orgmember"])
def test_move_model_non_owner_denied(client, world, actor):
    folder = _folder(world.owner)
    model = _make_model(world, organization=True)
    _login(client, actor)
    resp = client.post("/move_model", json={"model_id": model.id, "folder_id": folder.id})
    assert resp.status_code in (403, 404)
    assert _folder_of(model.id) is None


def test_move_model_into_someone_elses_folder_denied(client, world):
    foreign = _folder(world.stranger)
    model = _make_model(world)
    _login(client, "owner")
    resp = client.post("/move_model", json={"model_id": model.id, "folder_id": foreign.id})
    assert resp.status_code in (403, 404)
    assert _folder_of(model.id) is None


def test_move_model_validation_and_anonymous(client, world):
    model = _make_model(world)
    assert client.post("/move_model", json={"model_id": model.id}).status_code in (302, 401)
    _login(client, "owner")
    assert client.post("/move_model", json={"folder_id": 1}).status_code == 400
    assert client.post("/move_model", json={"model_id": str(uuid.uuid4())}).status_code == 404


def test_move_selected_models_owner_moves_all(client, world):
    folder = _folder(world.owner)
    models = [_make_model(world), _make_model(world)]
    _login(client, "owner")
    resp = client.post("/move_selected_models",
                       json={"model_ids": [m.id for m in models], "folder_id": folder.id})
    assert resp.status_code == 200
    assert all(_folder_of(m.id) == folder.id for m in models)


def test_move_selected_models_with_foreign_id_rejected_atomically(client, world):
    folder = _folder(world.owner)
    mine = _make_model(world)
    theirs = _make_model(world, owner=world.stranger)
    _login(client, "owner")
    resp = client.post("/move_selected_models",
                       json={"model_ids": [mine.id, theirs.id], "folder_id": folder.id})
    assert resp.status_code == 403
    assert _folder_of(mine.id) is None and _folder_of(theirs.id) is None


def test_move_selected_models_foreign_folder_and_anonymous(client, world):
    foreign = _folder(world.stranger)
    mine = _make_model(world)
    assert client.post("/move_selected_models",
                       json={"model_ids": [mine.id], "folder_id": foreign.id}
                       ).status_code in (302, 401)
    _login(client, "owner")
    resp = client.post("/move_selected_models",
                       json={"model_ids": [mine.id], "folder_id": foreign.id})
    assert resp.status_code in (403, 404)
    assert _folder_of(mine.id) is None
    assert client.post("/move_selected_models", json={"model_ids": []}).status_code == 400


# --------------------------------------------------------------------------
# delete_folder / rename_folder
# --------------------------------------------------------------------------

def test_delete_folder_recursive_orphans_models_but_keeps_them(client, world):
    parent = _folder(world.owner, "Parent")
    child = _folder(world.owner, "Child", parent_id=parent.id)
    model = _make_model(world, folder_id=child.id)
    _login(client, "owner")
    assert client.post(f"/delete_folder/{parent.id}").status_code == 200
    db.session.expire_all()
    assert Folder.query.count() == 0
    assert _exists(model.id) and _folder_of(model.id) is None
    assert _files_present(model) == ALL


@pytest.mark.parametrize("actor", ["stranger", "orgmember"])
def test_delete_folder_non_owner_denied(client, world, actor):
    folder = _folder(world.owner)
    model = _make_model(world, folder_id=folder.id)
    _login(client, actor)
    assert client.post(f"/delete_folder/{folder.id}").status_code in (403, 404)
    assert db.session.get(Folder, folder.id) is not None
    assert _folder_of(model.id) == folder.id


def test_delete_folder_unknown_and_anonymous(client, world):
    folder = _folder(world.owner)
    assert client.post(f"/delete_folder/{folder.id}").status_code in (302, 401)
    assert db.session.get(Folder, folder.id) is not None
    _login(client, "owner")
    assert client.post("/delete_folder/99999").status_code == 404


def test_rename_folder_owner_trims_and_truncates(client, world):
    folder = _folder(world.owner)
    _login(client, "owner")
    resp = client.post(f"/rename_folder/{folder.id}", json={"name": "  Renamed  "})
    assert resp.status_code == 200 and resp.get_json()["name"] == "Renamed"
    resp = client.post(f"/rename_folder/{folder.id}", json={"name": "x" * 300})
    assert len(resp.get_json()["name"]) == 100


def test_rename_folder_validation_and_duplicate(client, world):
    first = _folder(world.owner, "First")
    _folder(world.owner, "Second")
    _login(client, "owner")
    assert client.post(f"/rename_folder/{first.id}", json={"name": "   "}).status_code == 400
    assert client.post(f"/rename_folder/{first.id}", json={"name": "Second"}).status_code == 409
    assert db.session.get(Folder, first.id).name == "First"


@pytest.mark.parametrize("actor", ["stranger", "orgmember"])
def test_rename_folder_non_owner_denied(client, world, actor):
    folder = _folder(world.owner, "Original")
    _login(client, actor)
    assert client.post(f"/rename_folder/{folder.id}",
                       json={"name": "Hacked"}).status_code in (403, 404)
    db.session.expire_all()
    assert db.session.get(Folder, folder.id).name == "Original"


def test_rename_folder_anonymous_denied(client, world):
    folder = _folder(world.owner, "Original")
    assert client.post(f"/rename_folder/{folder.id}",
                       json={"name": "Hacked"}).status_code in (302, 401)
    assert db.session.get(Folder, folder.id).name == "Original"
