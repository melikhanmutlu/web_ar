"""ADM-31: version files do not count toward a user's storage quota, and every
screen (profile, library, admin) reports the same number."""

from models import ModelVersion, User, UserModel, db
from services.storage_quota import _storage_usage_for
from tests.test_admin import login, make_model

VERSION_BYTES = 50_000_000  # would render as "47.7 MB" if it leaked in


def _user_with_versioned_model():
    user = User(username="quotauser", email="quota@test.com")
    user.set_password("quotapassword")
    db.session.add(user)
    db.session.commit()
    model = make_model(user_id=user.id, model_id="m-quota-0001")
    db.session.add(ModelVersion(
        model_id=model.id, version_number=1, filename="v1.glb",
        file_size=VERSION_BYTES, operation_type="upload",
    ))
    db.session.commit()
    return user


def test_usage_helper_ignores_versions(client):
    user = _user_with_versioned_model()
    assert _storage_usage_for(user.id) == 1234


def test_profile_and_admin_agree_with_quota(client):
    user = _user_with_versioned_model()
    admin = User(username="adminq", email="adminq@test.com", is_admin=True)
    admin.set_password("adminpassword")
    db.session.add(admin)
    db.session.commit()

    login(client, "quotauser", "quotapassword")
    profile = client.get("/profile").get_data(as_text=True)
    assert "47.7 MB" not in profile
    client.post("/logout")

    login(client, "adminq", "adminpassword")
    for url in ("/admin/users", f"/admin/users/{user.id}"):
        html = client.get(url).get_data(as_text=True)
        assert "1.2 kB" in html, url
        assert "MB" not in html.split("storage")[-1][:200] or "47.7 MB" not in html, url
    assert "47.7 MB" not in client.get("/admin/").get_data(as_text=True)
