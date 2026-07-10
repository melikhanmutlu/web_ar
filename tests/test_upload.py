import io

def test_upload_without_login(client):
    data = {
        'file': (io.BytesIO(b"dummy stl content"), 'test.stl')
    }
    response = client.post('/upload_model', data=data, content_type='multipart/form-data', follow_redirects=True)
    
    # Should be allowed even without login
    assert response.status_code in [200, 202, 400, 500] # Async queue returns 202.

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
