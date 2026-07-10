import io
from pathlib import Path

import app as app_module
from models import ConversionJob, Folder, User, UserModel, db

def test_upload_without_login_creates_trackable_job(client, monkeypatch):
    monkeypatch.setattr(app_module, "JOB_QUEUE_ENABLED", True)
    data = {
        'file': (io.BytesIO(b"dummy stl content"), 'test.stl')
    }
    response = client.post('/upload_model', data=data, content_type='multipart/form-data', follow_redirects=True)

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status_token"]
    assert payload["edit_token"]
    assert db.session.get(ConversionJob, payload["job_id"]) is not None
    app_module.shutil.rmtree(
        Path(app_module.app.config["TEMP_FOLDER"]) / payload["job_id"],
        ignore_errors=True,
    )


def test_owner_can_download_model(client, init_database):
    client.post('/login', data={'username': 'testuser', 'password': 'testpassword'})
    model_id = '77777777-7777-7777-7777-777777777777'
    model_dir = Path(app_module.app.config['CONVERTED_FOLDER']) / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / 'model.glb'
    path.write_bytes(b'glTF')
    db.session.add(UserModel(
        id=model_id, filename=str(path.resolve()), user_id=init_database.id,
        display_name='test-model',
    ))
    db.session.commit()

    response = client.get(f'/download/{model_id}')
    assert response.status_code == 200
    assert response.data == b'glTF'
    app_module.shutil.rmtree(model_dir, ignore_errors=True)


def test_personal_folder_rejects_another_users_parent(client, init_database):
    other = User(username="other-folder-user", email="other-folder@example.com")
    other.set_password("password")
    db.session.add(other)
    db.session.flush()
    foreign_parent = Folder(
        name="Private", slug="private-parent", user_id=other.id,
    )
    db.session.add(foreign_parent)
    db.session.commit()
    client.post('/login', data={'username': 'testuser', 'password': 'testpassword'})
    response = client.post(
        '/create_folder',
        data={'folder_name': 'Injected child', 'parent_id': foreign_parent.id},
    )
    assert response.status_code == 302
    assert Folder.query.filter_by(name='Injected child').first() is None

def test_upload_invalid_file_extension(client, init_database):
    # Log in first
    client.post('/login', data=dict(
        username='testuser',
        password='testpassword'
    ), follow_redirects=True)
    
    data = {
        'file': (io.BytesIO(b"dummy text content"), 'test.txt')
    }
    response = client.post('/upload_model', data=data, content_type='multipart/form-data', follow_redirects=True)
    
    # Validation should reject non-supported extensions with 400
    assert response.status_code == 400
    assert b"Unsupported file format" in response.data or b"error" in response.data

def test_delete_folder_without_auth(client):
    response = client.post('/delete_folder/1', follow_redirects=True)
    assert response.request.path == '/login'

def test_delete_model_without_auth(client):
    """Test that deleting a model without auth fails or returns 404 since it's an API route."""
    response = client.post('/delete_model/1')
    assert response.status_code in (302, 401, 404)


def test_legacy_upload_is_gone(client):
    response = client.post('/upload')
    assert response.status_code == 410
    assert b"Legacy upload endpoint removed" in response.data
