"""Anonymous uploads are claimed by the browser that holds their edit token
when it registers or logs in."""
from werkzeug.security import generate_password_hash

from models import User, UserModel, db

TOKEN = "claim-me-token"


def _anon(model_id, size=1000, token=TOKEN):
    m = UserModel(id=model_id, filename=f"{model_id}/m.glb", file_type="glb", file_size=size,
                  user_id=None, edit_token_hash=generate_password_hash(token), visibility="unlisted")
    db.session.add(m)
    db.session.commit()
    return m


def _hold(client, *ids, token=TOKEN):
    with client.session_transaction() as s:
        for i in ids:
            s[f"model_edit_token:{i}"] = token


def _register(client, name="newbie"):
    return client.post("/register", data=dict(username=name, email=f"{name}@test.com",
                       password="password123", confirm_password="password123"), follow_redirects=True)


def test_register_claims_models_and_flashes(client):
    _anon("anon-1")
    _anon("anon-2")
    _hold(client, "anon-1", "anon-2")
    html = _register(client).get_data(as_text=True)
    assert "2 models saved to your library" in html
    user = User.query.filter_by(username="newbie").one()
    for mid in ("anon-1", "anon-2"):
        m = db.session.get(UserModel, mid)
        assert m.user_id == user.id and m.visibility == "private" and m.edit_token_hash is None
    with client.session_transaction() as s:
        assert not [k for k in s if k.startswith("model_edit_token:")]


def test_login_claims_models(client, init_database):
    _anon("anon-l")
    _hold(client, "anon-l")
    html = client.post("/login", data=dict(username="testuser", password="testpassword"),
                       follow_redirects=True).get_data(as_text=True)
    assert "1 model saved to your library" in html
    assert db.session.get(UserModel, "anon-l").user_id == init_database.id


def test_wrong_token_or_other_users_model_not_claimed(client):
    _anon("anon-x")
    owner = User(username="owner", email="o@test.com")
    owner.set_password("password123")
    db.session.add(owner)
    db.session.commit()
    mine = _anon("anon-y")
    mine.user_id = owner.id
    db.session.commit()
    _hold(client, "anon-x", token="wrong")
    _hold(client, "anon-y")
    html = _register(client).get_data(as_text=True)
    assert "saved to your library" not in html
    assert db.session.get(UserModel, "anon-x").user_id is None
    assert db.session.get(UserModel, "anon-y").user_id == owner.id


def test_no_session_tokens_nothing_claimed(client):
    _anon("anon-n")
    assert "saved to your library" not in _register(client).get_data(as_text=True)
    assert db.session.get(UserModel, "anon-n").user_id is None


def test_model_count_limit_claims_what_fits(client, monkeypatch):
    from services import model_claim
    monkeypatch.setattr(model_claim, "plan_limit", lambda user, key: 2)
    for i in range(3):
        _anon(f"anon-c{i}")
    _hold(client, "anon-c0", "anon-c1", "anon-c2")
    html = _register(client).get_data(as_text=True)
    assert "2 models saved to your library" in html
    assert "1 anonymous model could not be added" in html
    assert UserModel.query.filter(UserModel.user_id.isnot(None)).count() == 2
    with client.session_transaction() as s:  # the leftover stays claimable
        assert len([k for k in s if k.startswith("model_edit_token:")]) == 1


def test_storage_quota_claims_what_fits(client, monkeypatch):
    from services import model_claim
    monkeypatch.setattr(model_claim, "_storage_quota_bytes", lambda user: 1500)
    _anon("anon-s1", size=1000)
    _anon("anon-s2", size=1000)
    _hold(client, "anon-s1", "anon-s2")
    html = _register(client).get_data(as_text=True)
    assert "1 model saved to your library" in html
    assert "1 anonymous model could not be added" in html
