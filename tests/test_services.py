from pathlib import Path

import pytest
from werkzeug.security import generate_password_hash

from models import UserModel, db
from services import ModelAccessService, StorageService


def test_model_access_service_enforces_owner_and_capability(client):
    owned = UserModel(id="owned", filename="x", user_id=9)
    anonymous = UserModel(
        id="anonymous", filename="x", edit_token_hash=generate_password_hash("token")
    )
    db.session.add_all([owned, anonymous])
    db.session.commit()
    service = ModelAccessService(UserModel)

    assert not service.mutation_decision("owned", actor_id=8)[1].allowed
    assert service.mutation_decision("owned", actor_id=9)[1].allowed
    assert not service.mutation_decision("anonymous", edit_token="wrong")[1].allowed
    assert service.mutation_decision("anonymous", edit_token="token")[1].allowed


def test_storage_service_rejects_escape_and_removes_scoped_model():
    root = Path(".test-storage").resolve()
    service = StorageService(root)
    model_dir = service.ensure_model_dir("safe-id")
    (model_dir / "model.glb").write_bytes(b"glTF")

    with pytest.raises(ValueError):
        service.converted_path("..", "outside")

    service.remove_model("safe-id")
    assert not model_dir.exists()
    root.rmdir()
