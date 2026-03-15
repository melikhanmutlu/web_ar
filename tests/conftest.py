import pytest
from app import app, db
from models import User, Folder

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:' # Use in-memory DB for tests
    app.config['WTF_CSRF_ENABLED'] = False
    
    with app.test_client() as client:
        with app.app_context():
            db.drop_all()
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()

@pytest.fixture
def init_database():
    user = User(username='testuser', email='test@test.com')
    user.set_password('testpassword')
    db.session.add(user)
    db.session.commit()
    return user
