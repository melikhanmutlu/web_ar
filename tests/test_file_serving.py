"""Security tests for blueprints/model_files.py: /converted_files/<id>/<file>,
/thumbnail/<id>, /converted/<path> and the viewer thumbnail upload (OPS-21).

Covers path traversal (literal, percent-encoded, absolute, encoded slashes),
the published-asset allow-list, private-model access (owner / org member /
stranger / valid, revoked and expired share links) and Cache-Control scoping.
"""

import base64
import hashlib
import io
import uuid
from datetime import datetime, timedelta

import pytest

from app import app, db
from models import (
    ModelShareLink,
    Organization,
    OrganizationMember,
    User,
    UserModel,
)

SECRET = b"TOP-SECRET-OUTSIDE-MODEL-DIR"
GLB = b"glTF-published-bytes"


def _login(client, username):
    return client.post("/login", data={"username": username, "password": "pw"})


def _user(name):
    user = User(username=name, email=f"{name}@test.com")
    user.set_password("pw")
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def env(client, tmp_path, monkeypatch):
    conv = tmp_path / "converted"
    conv.mkdir()
    monkeypatch.setitem(app.config, "CONVERTED_FOLDER", str(conv))
    owner, stranger, member = _user("owner"), _user("stranger"), _user("orgmember")
    org = Organization(name="Acme", slug="acme", created_by=owner.id)
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=member.id,
                                      role="viewer"))
    db.session.commit()
    # Things that must never leak: a file beside the converted tree, and one at
    # the converted root.
    (tmp_path / "secret.txt").write_bytes(SECRET)
    (conv / "secret.txt").write_bytes(SECRET)
    return type("Env", (), dict(conv=conv, owner=owner, stranger=stranger,
                                member=member, org=org))


def _model(env, visibility="private", organization=False, deleted=False, files=True):
    mid = str(uuid.uuid4())
    d = env.conv / mid
    if files:
        d.mkdir()
        (d / "model.glb").write_bytes(GLB)
        (d / "model.usdz").write_bytes(b"usdz-bytes")
        (d / "model_lod1.glb").write_bytes(b"lod-bytes")
        (d / "thumbnail.png").write_bytes(_png())
        for internal in (".edit.lock", "model_backup_1700000000.glb",
                         "modified_1700000000.glb", "temp_work.glb", "meta.json"):
            (d / internal).write_bytes(b"INTERNAL")
    model = UserModel(
        id=mid, filename=str(d / "model.glb"), file_size=len(GLB), file_type="glb",
        user_id=env.owner.id, visibility=visibility,
        organization_id=env.org.id if organization else None,
        deleted_at=datetime.utcnow() if deleted else None,
    )
    db.session.add(model)
    db.session.commit()
    return model


def _png():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (10, 20, 30)).save(buf, "PNG")
    return buf.getvalue()


def _share_link(model, token="share-secret", **kwargs):
    link = ModelShareLink(model_id=model.id,
                          token_digest=hashlib.sha256(token.encode()).hexdigest(),
                          permission="view", **kwargs)
    db.session.add(link)
    db.session.commit()
    return link


# --------------------------------------------------------------------------
# Allow-list
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,body", [
    ("model.glb", GLB), ("model_lod1.glb", b"lod-bytes"), ("model.usdz", b"usdz-bytes"),
])
def test_published_assets_are_served_for_public_model(client, env, name, body):
    model = _model(env, visibility="public")
    resp = client.get(f"/converted_files/{model.id}/{name}")
    assert resp.status_code == 200
    assert resp.data == body


@pytest.mark.parametrize("name", [
    ".edit.lock", "model_backup_1700000000.glb", "modified_1700000000.glb",
    "temp_work.glb", "meta.json", "thumbnail.png", "secret.txt", "model.glb.bak",
    "MODEL.GLB", "model.glb.", "model_lod.glb",
])
def test_unpublished_files_are_never_served(client, env, name):
    model = _model(env, visibility="public")
    resp = client.get(f"/converted_files/{model.id}/{name}")
    assert resp.status_code == 404
    assert b"INTERNAL" not in resp.data and SECRET not in resp.data


def test_unpublished_files_not_served_even_to_owner(client, env):
    model = _model(env, visibility="private")
    _login(client, "owner")
    for name in (".edit.lock", "model_backup_1700000000.glb", "meta.json"):
        assert client.get(f"/converted_files/{model.id}/{name}").status_code == 404


def test_missing_file_in_existing_model_is_404(client, env):
    model = _model(env, visibility="public")
    (env.conv / model.id / "model.glb").unlink()
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 404


# --------------------------------------------------------------------------
# Path traversal
# --------------------------------------------------------------------------

TRAVERSAL_FILENAMES = [
    "../secret.txt",
    "..%2fsecret.txt",
    "%2e%2e/secret.txt",
    "%2e%2e%2fsecret.txt",
    "..%5csecret.txt",
    "%252e%252e/secret.txt",
    "/etc/passwd",
    "%2fetc%2fpasswd",
    "model.glb/../../secret.txt",
    "....//secret.txt",
    "model.glb%00.usdz",
]


@pytest.mark.parametrize("filename", TRAVERSAL_FILENAMES)
def test_traversal_in_filename_never_leaks(client, env, filename):
    model = _model(env, visibility="public")
    resp = client.get(f"/converted_files/{model.id}/{filename}")
    assert resp.status_code in (301, 308, 400, 404)
    assert SECRET not in resp.data and b"root:" not in resp.data


@pytest.mark.parametrize("unique_id", [
    "..", "%2e%2e", "../..", "%2e%2e%2f", "/etc", "%2fetc", "not-a-uuid",
    "{id}/../{id}", "{id}%2f..%2f{id}",
])
def test_traversal_in_unique_id_is_rejected(client, env, unique_id):
    model = _model(env, visibility="public")
    uid = unique_id.format(id=model.id)
    resp = client.get(f"/converted_files/{uid}/model.glb")
    assert resp.status_code in (301, 308, 400, 404)
    assert resp.data != GLB or uid == model.id


def test_uppercase_uuid_does_not_bypass_to_other_directories(client, env):
    model = _model(env, visibility="public")
    # Only canonical lowercase UUIDs are accepted.
    assert client.get(f"/converted_files/{model.id.upper()}/model.glb").status_code == 404


def test_other_models_files_not_reachable_through_traversal(client, env):
    mine, other = _model(env, visibility="public"), _model(env, visibility="private")
    for filename in (f"../{other.id}/model.glb", f"..%2f{other.id}%2fmodel.glb"):
        resp = client.get(f"/converted_files/{mine.id}/{filename}")
        assert resp.status_code in (301, 308, 400, 404)
        assert GLB not in resp.data


@pytest.mark.parametrize("path", [
    "../secret.txt", "%2e%2e/secret.txt", "/etc/passwd", "..%2fsecret.txt",
    "{conv}/secret.txt", "does/not/exist.glb",
])
def test_converted_path_route_rejects_traversal(client, env, path):
    _model(env, visibility="public")
    resp = client.get("/converted/" + path.format(conv=env.conv))
    assert resp.status_code in (301, 308, 400, 404)
    assert SECRET not in resp.data


# --------------------------------------------------------------------------
# Access control
# --------------------------------------------------------------------------

def test_private_model_owner_ok_stranger_and_anonymous_denied(client, env):
    model = _model(env, visibility="private")
    url = f"/converted_files/{model.id}/model.glb"
    assert client.get(url).status_code == 404
    _login(client, "stranger")
    assert client.get(url).status_code == 404
    client.post("/logout")
    _login(client, "owner")
    assert client.get(url).data == GLB


def test_private_org_model_visible_to_org_member_only(client, env):
    model = _model(env, visibility="private", organization=True)
    url = f"/converted_files/{model.id}/model.glb"
    _login(client, "stranger")
    assert client.get(url).status_code == 404
    client.post("/logout")
    _login(client, "orgmember")
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("visibility", ["public", "unlisted"])
def test_non_private_models_are_viewable_anonymously(client, env, visibility):
    model = _model(env, visibility=visibility)
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 200


def test_trashed_and_unknown_models_are_404_even_for_owner(client, env):
    trashed = _model(env, visibility="public", deleted=True)
    _login(client, "owner")
    assert client.get(f"/converted_files/{trashed.id}/model.glb").status_code == 404
    assert client.get(f"/converted_files/{uuid.uuid4()}/model.glb").status_code == 404
    assert client.get(f"/thumbnail/{uuid.uuid4()}").status_code == 404


def test_owner_sees_thumbnails_of_their_trashed_models(client, env):
    """Library Trash must show what will be restored (UIA-26)."""
    trashed = _model(env, visibility="public", deleted=True)
    _login(client, "owner")
    resp = client.get(f"/thumbnail/{trashed.id}")
    assert resp.status_code == 200
    assert resp.mimetype == "image/png"
    assert resp.cache_control.public is not True  # never in shared caches


def test_trashed_thumbnail_is_not_served_to_anyone_else(client, env):
    trashed = _model(env, visibility="public", deleted=True)
    assert client.get(f"/thumbnail/{trashed.id}").status_code == 404  # anonymous
    _login(client, "stranger")
    assert client.get(f"/thumbnail/{trashed.id}").status_code == 404
    assert client.get(f"/converted_files/{trashed.id}/thumbnail.png").status_code == 404


def test_trashed_thumbnail_is_never_generated_on_the_fly(client, env):
    trashed = _model(env, deleted=True)
    (env.conv / trashed.id / "thumbnail.png").unlink()
    _login(client, "owner")
    assert client.get(f"/thumbnail/{trashed.id}").status_code == 404
    assert not (env.conv / trashed.id / "thumbnail.png").exists()


def test_valid_share_link_unlocks_private_files_and_thumbnail(client, env):
    model = _model(env, visibility="private")
    _share_link(model, "good-token")
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 404
    assert client.get("/s/good-token").status_code == 302
    assert client.get(f"/converted_files/{model.id}/model.glb").data == GLB
    assert client.get(f"/thumbnail/{model.id}").status_code == 200
    # ...but a share link never exposes internal working files.
    assert client.get(f"/converted_files/{model.id}/model_backup_1700000000.glb"
                      ).status_code == 404


def test_revoking_share_link_cuts_off_existing_session(client, env):
    model = _model(env, visibility="private")
    link = _share_link(model, "revocable")
    client.get("/s/revocable")
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 200
    link.revoked_at = datetime.utcnow()
    db.session.commit()
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 404
    assert client.get(f"/thumbnail/{model.id}").status_code == 404


def test_expiring_share_link_cuts_off_existing_session(client, env):
    model = _model(env, visibility="private")
    link = _share_link(model, "expiring", expires_at=datetime.utcnow() + timedelta(hours=1))
    client.get("/s/expiring")
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 200
    link.expires_at = datetime.utcnow() - timedelta(seconds=1)
    db.session.commit()
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 404


def test_expired_or_revoked_link_cannot_be_opened(client, env):
    model = _model(env, visibility="private")
    _share_link(model, "dead-1", expires_at=datetime.utcnow() - timedelta(seconds=1))
    _share_link(model, "dead-2", revoked_at=datetime.utcnow())
    for token in ("dead-1", "dead-2"):
        assert client.get(f"/s/{token}").status_code == 410  # branded "link expired/revoked" page
    assert client.get(f"/converted_files/{model.id}/model.glb").status_code == 404


def test_share_grant_for_one_model_does_not_open_another(client, env):
    shared, other = _model(env, visibility="private"), _model(env, visibility="private")
    _share_link(shared, "only-shared")
    client.get("/s/only-shared")
    assert client.get(f"/converted_files/{shared.id}/model.glb").status_code == 200
    assert client.get(f"/converted_files/{other.id}/model.glb").status_code == 404


# --------------------------------------------------------------------------
# Thumbnails
# --------------------------------------------------------------------------

def test_thumbnail_access_matches_model_visibility(client, env):
    model = _model(env, visibility="private")
    assert client.get(f"/thumbnail/{model.id}").status_code == 404
    _login(client, "stranger")
    assert client.get(f"/thumbnail/{model.id}").status_code == 404
    client.post("/logout")
    _login(client, "owner")
    resp = client.get(f"/thumbnail/{model.id}")
    assert resp.status_code == 200 and resp.data == _png()


def test_thumbnail_id_is_not_a_path(client, env):
    _model(env, visibility="public")
    for uid in ("..", "%2e%2e", "..%2fsecret.txt", "x/../../secret.txt"):
        resp = client.get(f"/thumbnail/{uid}")
        assert resp.status_code in (301, 308, 400, 404)
        assert SECRET not in resp.data


def _upload(client, model_id, raw, prefix="data:image/png;base64,"):
    return client.post(f"/api/thumbnail/{model_id}",
                       json={"image": prefix + base64.b64encode(raw).decode()})


def test_thumbnail_upload_only_by_owner(client, env):
    model = _model(env, visibility="public")
    new_png = _png() + b""  # same bytes; assert state through disk write below
    assert _upload(client, model.id, new_png).status_code in (302, 401)
    _login(client, "stranger")
    assert _upload(client, model.id, new_png).status_code == 403
    client.post("/logout")
    _login(client, "orgmember")
    assert _upload(client, model.id, new_png).status_code == 403
    client.post("/logout")
    _login(client, "owner")
    (env.conv / model.id / "thumbnail.png").write_bytes(b"old")
    resp = _upload(client, model.id, new_png)
    assert resp.status_code == 200
    assert (env.conv / model.id / "thumbnail.png").read_bytes() == new_png


def test_thumbnail_upload_rejects_non_png_and_garbage(client, env):
    model = _model(env, visibility="public")
    from PIL import Image
    jpeg = io.BytesIO()
    Image.new("RGB", (4, 4)).save(jpeg, "JPEG")
    _login(client, "owner")
    before = (env.conv / model.id / "thumbnail.png").read_bytes()
    assert _upload(client, model.id, jpeg.getvalue()).status_code == 400
    assert _upload(client, model.id, b"<svg onload=alert(1)>").status_code == 400
    assert client.post(f"/api/thumbnail/{model.id}", json={"image": "!!notbase64!!"}
                       ).status_code == 400
    assert client.post(f"/api/thumbnail/{model.id}", json={}).status_code == 400
    assert (env.conv / model.id / "thumbnail.png").read_bytes() == before


def test_thumbnail_upload_rejects_oversize(client, env):
    model = _model(env, visibility="public")
    _login(client, "owner")
    assert _upload(client, model.id, _png() + b"\0" * (5 * 1024 * 1024 + 1)
                   ).status_code == 413


# --------------------------------------------------------------------------
# /converted/<path>
# --------------------------------------------------------------------------

def test_converted_path_route_honours_visibility(client, env):
    model = _model(env, visibility="private")
    url = f"/converted/{model.id}/model.glb"
    assert client.get(url).status_code == 404
    _login(client, "stranger")
    assert client.get(url).status_code == 404
    client.post("/logout")
    _login(client, "owner")
    assert client.get(url).data == GLB


def test_converted_path_route_hides_trashed_models(client, env):
    model = _model(env, visibility="public", deleted=True)
    assert client.get(f"/converted/{model.id}/model.glb").status_code == 404


# --------------------------------------------------------------------------
# Cache-Control
# --------------------------------------------------------------------------

def test_public_model_is_publicly_cacheable(client, env):
    model = _model(env, visibility="public")
    for url in (f"/converted_files/{model.id}/model.glb", f"/thumbnail/{model.id}"):
        cc = client.get(url).headers["Cache-Control"]
        assert "public" in cc and "private" not in cc and "max-age=86400" in cc


@pytest.mark.parametrize("visibility", ["unlisted", "private"])
def test_non_public_models_are_never_shared_cacheable(client, env, visibility):
    model = _model(env, visibility=visibility)
    _login(client, "owner")
    for url in (f"/converted_files/{model.id}/model.glb", f"/thumbnail/{model.id}"):
        cc = client.get(url).headers["Cache-Control"]
        assert "private" in cc and "public" not in cc
