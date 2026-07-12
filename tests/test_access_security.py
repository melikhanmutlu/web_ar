from pathlib import Path
from werkzeug.security import generate_password_hash

from app import check_model_mutation_allowed
from models import ConversionJob, UserModel, db


def test_trashed_model_is_hidden_from_embed_vr_and_assets(client):
    model_id = "11111111-1111-1111-1111-111111111111"
    path = Path("test-trashed-model.glb").resolve()
    path.write_bytes(b"glTF")
    model = UserModel(id=model_id, filename=str(path), deleted_at=db.func.now())
    db.session.add(model)
    db.session.commit()

    assert client.get(f"/embed/{model_id}").status_code == 404
    assert client.get(f"/vr/{model_id}").status_code in (302, 404)
    assert client.get(f"/converted_files/{model_id}/model.glb").status_code == 404
    path.unlink(missing_ok=True)


def test_anonymous_mutation_requires_capability_token(client):
    model_id = "22222222-2222-2222-2222-222222222222"
    model = UserModel(
        id=model_id,
        filename="unused.glb",
        edit_token_hash=generate_password_hash("secret-capability"),
    )
    db.session.add(model)
    db.session.commit()

    with client.application.test_request_context("/"):
        assert check_model_mutation_allowed(model_id)[1] == 403
    with client.application.test_request_context(
        "/", headers={"X-Model-Edit-Token": "secret-capability"}
    ):
        assert check_model_mutation_allowed(model_id) is None


def test_conversion_status_requires_token(client):
    job = ConversionJob(
        id="33333333-3333-3333-3333-333333333333",
        status="pending",
        status_token_hash=generate_password_hash("status-secret"),
    )
    db.session.add(job)
    db.session.commit()

    assert client.get(f"/api/upload-jobs/{job.id}").status_code == 403
    response = client.get(
        f"/api/upload-jobs/{job.id}",
        headers={"X-Job-Status-Token": "status-secret"},
    )
    assert response.status_code == 200


def test_unregistered_model_cannot_use_mutation_endpoints(client):
    missing = "55555555-5555-5555-5555-555555555555"
    response = client.post(
        "/slice_model",
        json={
            "model_id": missing,
            "planes": [{"plane_origin": [0, 0, 0], "plane_normal": [1, 0, 0]}],
        },
    )
    assert response.status_code == 404


def test_legacy_raw_file_and_conversion_endpoints_are_gone(client):
    assert client.post("/convert", json={"modelId": "anything"}).status_code == 410
    assert client.get("/temp/anything").status_code == 410
    assert client.get("/qr/anything").status_code == 410


def test_thumbnail_requires_live_database_model(client):
    missing = "66666666-6666-6666-6666-666666666666"
    assert client.get(f"/thumbnail/{missing}").status_code == 404


def test_cross_site_browser_writes_are_rejected(client):
    response = client.post(
        "/upload_model",
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
    assert response.get_json()["error"] == "Cross-site request rejected"


def test_security_headers_and_post_only_logout(client):
    response = client.get("/")
    policy = response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'self'" in policy
    assert "connect-src 'self' https: blob:" in policy
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Permissions-Policy"]
    assert client.get("/logout").status_code == 405


def test_embed_frame_policy_matches_optional_allowlist(client):
    model_id = "88888888-8888-8888-8888-888888888888"
    path = Path("test-embed-policy.glb").resolve()
    path.write_bytes(b"glTF")
    model = UserModel(id=model_id, filename=str(path), visibility="unlisted")
    db.session.add(model)
    db.session.commit()
    assert "frame-ancestors *" in client.get(f"/embed/{model_id}").headers[
        "Content-Security-Policy"
    ]
    model.embed_allowed_domains = "shop.example"
    db.session.commit()
    policy = client.get(f"/embed/{model_id}").headers["Content-Security-Policy"]
    assert "frame-ancestors 'self' https://shop.example" in policy
    path.unlink(missing_ok=True)
