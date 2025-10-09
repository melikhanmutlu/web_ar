from app import app, db
from flask_migrate import Migrate, upgrade

migrate = Migrate(app, db)

with app.app_context():
    # Drop all tables
    db.drop_all()
    # Create all tables with the new schema
    db.create_all()
