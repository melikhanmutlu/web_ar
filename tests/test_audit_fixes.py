"""Regression tests for the audit-round fixes (K1, Y1, Y3, Y4, O4, D-L4)."""

from auth import _safe_next
from converters.glb_quality import _find_texture
from models import ApiToken, Organization, User, UserModel, db


# --- K1: converter external-texture path traversal --------------------------

def test_find_texture_ignores_absolute_and_traversal(tmp_path):
    (tmp_path / "tex.png").write_bytes(b"x")
    # A legitimate basename inside the search dir still resolves.
    assert _find_texture("tex.png", [str(tmp_path)]) is not None
    # Absolute and ../ references must never escape the search dir.
    assert _find_texture("/etc/passwd", [str(tmp_path)]) is None
    assert _find_texture("../../../../etc/passwd", [str(tmp_path)]) is None
    assert _find_texture("..\\..\\windows\\system32", [str(tmp_path)]) is None


# --- O4: login `next` open-redirect ----------------------------------------

def test_safe_next_blocks_open_redirect():
    assert _safe_next("/my_models") == "/my_models"
    assert _safe_next("/") == "/"
    assert _safe_next("//evil.com") is None       # protocol-relative
    assert _safe_next("/\\evil.com") is None       # backslash -> browser //
    assert _safe_next("https://evil.com") is None
    assert _safe_next("evil.com") is None          # no leading slash
    assert _safe_next("") is None
    assert _safe_next(None) is None


# --- Y3: deleting a user who created an org no longer fails on FK RESTRICT ---

def test_delete_user_who_created_org_nulls_created_by(client):
    u = User(username="orgcreator", email="oc@example.com")
    u.set_password("password123")
    db.session.add(u)
    db.session.commit()
    org = Organization(name="Acme", slug="acme-org", created_by=u.id)
    db.session.add(org)
    db.session.commit()
    org_id = org.id

    db.session.delete(u)
    db.session.commit()  # previously raised IntegrityError (FK RESTRICT)

    db.session.expire_all()
    assert db.session.get(Organization, org_id).created_by is None


# --- Y1: API token dies with its owner's active status ----------------------

def test_api_token_rejected_when_owner_deactivated(client):
    owner = User(username="apiowner3", email="a3@example.com", plan="pro")
    owner.set_password("password")
    db.session.add(owner)
    db.session.commit()
    client.post("/login", data={"username": owner.username, "password": "password"})
    created = client.post(
        "/api/tokens",
        json={"name": "t", "scopes": ["models:read"], "expires_in_days": 30},
    )
    plaintext = created.get_json()["token"]
    hdr = {"Authorization": f"Bearer {plaintext}"}
    assert client.get("/api/v1/models", headers=hdr).status_code == 200

    owner = db.session.get(User, owner.id)
    owner.is_active_flag = False
    db.session.commit()
    assert client.get("/api/v1/models", headers=hdr).status_code == 401
