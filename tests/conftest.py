import pytest
from app import app, db, limiter
from models import User, Folder

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:' # Use in-memory DB for tests
    app.config['WTF_CSRF_ENABLED'] = False
    # Flask-Limiter's storage is a process-wide singleton, so hits accumulate
    # across every test in the session, not just within one test. Its
    # `enabled` flag is latched from app.config only once, at the init_app()
    # call that already happened at import time — setting the config key
    # here has no effect, so the instance attribute must be flipped directly.
    # Without this, repeated /login calls across the suite eventually trip
    # the real rate limit and 429 unrelated tests. Tests that specifically
    # cover rate-limit/lockout behavior flip this back on for their own body.
    limiter.enabled = False

    with app.test_client() as client:
        with app.app_context():
            db.drop_all()
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()
    limiter.enabled = True

@pytest.fixture
def init_database():
    user = User(username='testuser', email='test@test.com')
    user.set_password('testpassword')
    db.session.add(user)
    db.session.commit()
    return user
