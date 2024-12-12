from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    models = db.relationship('UserModel', backref='user', lazy=True)
    folders = db.relationship('Folder', backref='user', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    parent = db.relationship('Folder', remote_side=[id], backref=db.backref('subfolders', lazy=True))
    models = db.relationship('UserModel', backref='folder', lazy=True)

    def generate_unique_slug(self):
        from werkzeug.utils import secure_filename
        import uuid
        base_slug = secure_filename(self.name.lower())
        unique_id = str(uuid.uuid4())[:8]  # Using first 8 characters of UUID
        return f"{base_slug}-{unique_id}"

    @property
    def path(self):
        if self.parent:
            return f"{self.parent.path}/{self.name}"
        return self.name

    @property
    def full_path(self):
        folders = []
        current = self
        while current:
            folders.insert(0, current)
            current = current.parent
        return folders

    @property
    def model_count(self):
        return len(self.models)

    def __repr__(self):
        return f'<Folder {self.name}>'

class UserModel(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # Changed to String to support UUID
    filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(50))
    vertices = db.Column(db.Integer, nullable=True)
    faces = db.Column(db.Integer, nullable=True)
    is_watertight = db.Column(db.Boolean, nullable=True)
    bounds = db.Column(db.String(255), nullable=True)
    color = db.Column(db.String(7), nullable=True)  # Hex color code
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    
    def __repr__(self):
        return f'<UserModel {self.filename}>'

    @property
    def original_filename(self):
        return self.filename.split('/')[-1] if self.filename else 'Unknown'

    @property
    def file_size_formatted(self):
        if not self.file_size:
            return 'Unknown'
        
        size = self.file_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

    @property
    def upload_date_formatted(self):
        if not self.upload_date:
            return 'Unknown'
        return self.upload_date.strftime('%Y-%m-%d %H:%M')
