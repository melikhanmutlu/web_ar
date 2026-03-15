def test_login_page_loads(client):
    response = client.get('/login')
    assert response.status_code == 200

def test_valid_login(client, init_database):
    response = client.post('/login', data=dict(
        username='testuser',
        password='testpassword'
    ), follow_redirects=True)
    
    # We should be redirected to the index page or see successful login message
    assert response.status_code == 200
    assert response.request.path == '/'

def test_invalid_login(client, init_database):
    response = client.post('/login', data=dict(
        username='testuser',
        password='wrongpassword'
    ), follow_redirects=True)
    
    assert response.status_code == 200
    # Should stay on login page
    assert response.request.path == '/login'

def test_logout(client, init_database):
    # Log in first
    client.post('/login', data=dict(
        username='testuser',
        password='testpassword'
    ), follow_redirects=True)
    
    # Then log out
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
    # Should be redirected to index
    assert response.request.path == '/'

def test_access_protected_route_without_login(client):
    """Test that protected routes redirect to login."""
    response = client.get('/profile', follow_redirects=True)
    assert response.status_code == 200
    # Unauthenticated user should be redirected to login page for protected routes
    assert response.request.path == '/login'
