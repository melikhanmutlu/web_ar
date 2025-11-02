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
    qr_code = db.Column(db.String(255), nullable=True)  # QR code filename
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    
    # Scale tracking
    original_dimensions = db.Column(db.JSON, nullable=True)  # Original dimensions at upload
    cumulative_scale = db.Column(db.Float, default=1.0)  # Total scale factor applied
    
    # Hotspot visibility
    hotspots_visible = db.Column(db.Boolean, default=True)  # Toggle for showing/hiding hotspots
    
    # Version tracking
    versions = db.relationship('ModelVersion', backref='model', lazy=True, cascade='all, delete-orphan', order_by='ModelVersion.created_at.desc()')
    
    # Hotspots
    hotspots = db.relationship('ModelHotspot', backref='model', lazy=True, cascade='all, delete-orphan', order_by='ModelHotspot.created_at')
    
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


class ModelHotspot(db.Model):
    """
    Stores hotspots (annotations) for 3D models
    Each hotspot has a position, title, description, and optional camera view
    """
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id'), nullable=False)
    
    # Hotspot data
    hotspot_id = db.Column(db.String(50), nullable=False)  # Frontend ID (e.g., 'hotspot-1234567890')
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    
    # Position on model (3D coordinates)
    position_x = db.Column(db.Float, nullable=False)
    position_y = db.Column(db.Float, nullable=False)
    position_z = db.Column(db.Float, nullable=False)
    
    # Normal vector (surface normal at hotspot)
    normal_x = db.Column(db.Float, nullable=True)
    normal_y = db.Column(db.Float, nullable=True)
    normal_z = db.Column(db.Float, nullable=True)
    
    # Camera view (optional)
    camera_view_id = db.Column(db.String(50), nullable=True)
    camera_orbit_theta = db.Column(db.Float, nullable=True)
    camera_orbit_phi = db.Column(db.Float, nullable=True)
    camera_orbit_radius = db.Column(db.Float, nullable=True)
    camera_target_x = db.Column(db.Float, nullable=True)
    camera_target_y = db.Column(db.Float, nullable=True)
    camera_target_z = db.Column(db.Float, nullable=True)
    camera_fov = db.Column(db.Float, nullable=True)
    
    # Metadata
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ModelHotspot {self.title} on {self.model_id}>'
    
    def to_dict(self):
        """Convert hotspot to dictionary for JSON serialization"""
        return {
            'id': self.hotspot_id,
            'title': self.title,
            'description': self.description,
            'position': {
                'x': self.position_x,
                'y': self.position_y,
                'z': self.position_z
            },
            'normal': {
                'x': self.normal_x,
                'y': self.normal_y,
                'z': self.normal_z
            } if self.normal_x is not None else None,
            'cameraViewId': self.camera_view_id,
            'cameraView': {
                'orbit': {
                    'theta': self.camera_orbit_theta,
                    'phi': self.camera_orbit_phi,
                    'radius': self.camera_orbit_radius
                },
                'target': {
                    'x': self.camera_target_x,
                    'y': self.camera_target_y,
                    'z': self.camera_target_z
                },
                'fov': self.camera_fov
            } if self.camera_view_id else None
        }


class ModelVersion(db.Model):
    """
    Tracks version history of model modifications
    Each modification (transform, slice, material) creates a new version
    """
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id'), nullable=False)
    version_number = db.Column(db.Integer, nullable=False)  # 1, 2, 3, etc.
    filename = db.Column(db.String(255), nullable=False)  # Path to version file
    file_size = db.Column(db.Integer)
    
    # What was done in this version
    operation_type = db.Column(db.String(50), nullable=False)  # 'upload', 'transform', 'slice', 'material'
    operation_details = db.Column(db.JSON, nullable=True)  # Details of the operation
    
    # Metadata
    dimensions = db.Column(db.JSON, nullable=True)  # Model dimensions at this version
    vertices = db.Column(db.Integer, nullable=True)
    faces = db.Column(db.Integer, nullable=True)
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Optional: User comment
    comment = db.Column(db.String(500), nullable=True)
    
    def __repr__(self):
        return f'<ModelVersion {self.model_id} v{self.version_number}>'
    
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
    def created_at_formatted(self):
        if not self.created_at:
            return 'Unknown'
        return self.created_at.strftime('%Y-%m-%d %H:%M:%S')
