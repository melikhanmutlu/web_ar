import os

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from services.time_utils import datetime
from datetime import timedelta
import sqlalchemy as sa

db = SQLAlchemy()

# SQLite ships with foreign key enforcement disabled per connection; without
# this the ondelete rules below are silently ignored (Postgres enforces them
# natively). Registered on the Engine class so app, worker and tests all get it.
import sqlite3
from sqlalchemy import event as _sa_event
from sqlalchemy.engine import Engine as _SAEngine


@_sa_event.listens_for(_SAEngine, "connect")
def _sqlite_enforce_foreign_keys(dbapi_connection, connection_record):
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

class User(UserMixin, db.Model):
    LOCKOUT_THRESHOLD = 5
    LOCKOUT_MINUTES = 15

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_admin = db.Column(db.Boolean, nullable=False, default=False, server_default=sa.false())
    # Plan/billing foundation (Faz 5): which tier's limits apply to this
    # user's storage quota and monthly AI limit (services/plans.py). Payment
    # processing itself is out of scope -- an admin sets this directly for
    # now, so the schema and enforcement hooks are ready for a real billing
    # provider to drive it later without another migration.
    plan = db.Column(db.String(20), nullable=False, default="free", server_default="free")
    # Prepaid overage credits (1 credit = 1 AI generation) consumed only after
    # the plan's monthly AI quota is used up. An admin tops this up for now
    # (services/credits.py::grant_ai_credits); a payment provider will call the
    # same seam later. No expiry -- purchased credits don't reset monthly.
    ai_credit_balance = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    # Column stays named is_active in the DB; the attribute is renamed so the
    # is_active property below can satisfy Flask-Login's interface.
    is_active_flag = db.Column('is_active', db.Boolean, nullable=False, default=True, server_default=sa.true())
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    locked_until = db.Column(db.DateTime, nullable=True)
    models = db.relationship('UserModel', backref='user', lazy=True, passive_deletes=True)
    folders = db.relationship('Folder', backref='user', lazy=True, passive_deletes=True)
    organization_memberships = db.relationship('OrganizationMember', backref='user', lazy=True, cascade='all, delete-orphan', passive_deletes=True)

    @property
    def is_active(self):
        # Flask-Login: login_user() refuses inactive users automatically.
        return bool(self.is_active_flag)

    @property
    def is_locked(self):
        return self.locked_until is not None and self.locked_until > datetime.utcnow()

    def register_failed_login(self):
        """Brute-force guard: lock the account for LOCKOUT_MINUTES after
        LOCKOUT_THRESHOLD consecutive failed password attempts."""
        self.failed_login_attempts = (self.failed_login_attempts or 0) + 1
        if self.failed_login_attempts >= self.LOCKOUT_THRESHOLD:
            self.locked_until = datetime.utcnow() + timedelta(minutes=self.LOCKOUT_MINUTES)

    def register_successful_login(self):
        self.failed_login_attempts = 0
        self.locked_until = None

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'

class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # Slug uniqueness is scoped, not global: two users (or two orgs) may pick
    # the same folder name. NULL organization_id/parent_id values are distinct
    # under SQL UNIQUE semantics, so the random suffix appended at creation
    # time remains the practical collision guard.
    slug = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id', ondelete='SET NULL'), nullable=True, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('folder.id', ondelete='CASCADE'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'organization_id', 'parent_id', 'slug',
                            name='uq_folder_scope_slug'),
    )

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

class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    members = db.relationship('OrganizationMember', backref='organization', lazy=True, cascade='all, delete-orphan', passive_deletes=True)
    models = db.relationship('UserModel', backref='organization', lazy=True)


class OrganizationMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    role = db.Column(db.String(20), nullable=False, default='viewer')
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('organization_id', 'user_id', name='uq_org_member'),)


class OrganizationDomain(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id', ondelete='CASCADE'), nullable=False, index=True)
    hostname = db.Column(db.String(255), unique=True, nullable=False, index=True)
    verification_token = db.Column(db.String(80), nullable=False)
    verified_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    organization = db.relationship('Organization', backref=db.backref('domains', lazy=True, cascade='all, delete-orphan', passive_deletes=True))


class ApiToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id', ondelete='CASCADE'), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    token_prefix = db.Column(db.String(16), nullable=False, index=True)
    token_digest = db.Column(db.String(64), unique=True, nullable=False, index=True)
    scopes = db.Column(db.String(500), nullable=False, default='models:read')
    expires_at = db.Column(db.DateTime, nullable=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    @property
    def is_active(self):
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > datetime.utcnow()
        )

    def has_scope(self, scope):
        return scope in set((self.scopes or '').split(','))


class WebhookSubscription(db.Model):
    """A user-owned HTTPS endpoint notified on conversion/AI generation
    completion events. Delivery is best-effort (fire-and-forget, no retry
    queue) -- see services/webhooks.py."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    url = db.Column(db.String(500), nullable=False)
    secret = db.Column(db.String(64), nullable=False)
    event_types = db.Column(db.String(300), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_triggered_at = db.Column(db.DateTime, nullable=True)
    last_status_code = db.Column(db.Integer, nullable=True)

    def subscribes_to(self, event_type):
        return event_type in set((self.event_types or '').split(','))

    def to_dict(self):
        return {
            "id": self.id, "url": self.url,
            "event_types": (self.event_types or '').split(','),
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
            "last_triggered_at": self.last_triggered_at.isoformat() if self.last_triggered_at else None,
            "last_status_code": self.last_status_code,
        }


class UserModel(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # Changed to String to support UUID
    filename = db.Column(db.String(255), nullable=False)
    usdz_filename = db.Column(db.String(255), nullable=True)  # Path to USDZ file for iOS AR
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(50))
    vertices = db.Column(db.Integer, nullable=True)
    faces = db.Column(db.Integer, nullable=True)
    is_watertight = db.Column(db.Boolean, nullable=True)
    bounds = db.Column(db.String(255), nullable=True)
    color = db.Column(db.String(7), nullable=True)  # Hex color code
    qr_code = db.Column(db.String(255), nullable=True)  # QR code filename
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id', ondelete='SET NULL'), nullable=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id', ondelete='SET NULL'), nullable=True, index=True)
    
    # Scale tracking
    original_dimensions = db.Column(db.JSON, nullable=True)  # Original dimensions at upload
    # Total scale applied through VIEWER edits since conversion (display-only,
    # shown as "Total Scale" in the transform panel). Deliberately excludes
    # upload-time normalization (unit conversion, max_dimension) — those are
    # part of producing the converted model, not a user edit on it.
    cumulative_scale = db.Column(db.Float, default=1.0)
    
    # Hotspot visibility
    hotspots_visible = db.Column(db.Boolean, default=True)  # Toggle for showing/hiding hotspots

    # User-editable display name (separate from file path)
    display_name = db.Column(db.String(255), nullable=True)

    # Comma-joined lowercase tags for the my-models search/filter UI.
    tags = db.Column(db.String(500), nullable=True)

    # Soft delete: set when moved to trash, files stay on disk until purge
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)
    edit_token_hash = db.Column(db.String(255), nullable=True)
    visibility = db.Column(db.String(20), nullable=False, default="unlisted", index=True)
    embed_allowed_domains = db.Column(db.Text, nullable=True)
    validation_report = db.Column(db.JSON, nullable=True)
    seo_metadata = db.Column(db.JSON, nullable=True)
    viewer_settings = db.Column(db.JSON, nullable=True)

    # Social / engagement fields
    description = db.Column(db.Text, nullable=True)
    view_count = db.Column(db.Integer, default=0)
    download_count = db.Column(db.Integer, default=0)
    share_count = db.Column(db.Integer, default=0)

    # How this model was created: None/'' for a plain upload, or
    # 'ai-text'/'ai-image' etc. for AI-generated ones (see
    # register_glb_as_model's `source` param). description already carries
    # this as free text ("AI generated (...)"); this column makes it
    # queryable for a badge/filter without string-parsing description.
    source = db.Column(db.String(30), nullable=True)

    # The user's original uploaded filename (e.g. "robot.stl"), distinct from
    # `filename` which is the on-disk storage path (always "<uuid>/model.glb").
    # Nullable so older rows fall back to the pre-existing (buggy) behaviour.
    source_filename = db.Column(db.String(255), nullable=True)
    
    # Version tracking
    versions = db.relationship('ModelVersion', backref='model', lazy=True, cascade='all, delete-orphan', passive_deletes=True, order_by='ModelVersion.created_at.desc()')
    
    # Hotspots
    hotspots = db.relationship('ModelHotspot', backref='model', lazy=True, cascade='all, delete-orphan', passive_deletes=True, order_by='ModelHotspot.created_at')
    share_links = db.relationship('ModelShareLink', backref='model', lazy=True, cascade='all, delete-orphan', passive_deletes=True)
    analytics_events = db.relationship('ModelAnalyticsEvent', backref='model', lazy=True, cascade='all, delete-orphan', passive_deletes=True)
    lods = db.relationship('ModelLOD', backref='model', lazy=True, cascade='all, delete-orphan', passive_deletes=True)
    derived_assets = db.relationship('ModelDerivedAsset', backref='model', lazy=True, cascade='all, delete-orphan', passive_deletes=True)
    
    def __repr__(self):
        return f'<UserModel {self.filename}>'

    @property
    def original_filename(self):
        if self.source_filename:
            return self.source_filename
        return self.filename.split('/')[-1] if self.filename else 'Unknown'

    # `filename`/`usdz_filename` store ABSOLUTE paths captured at creation
    # time. The storage root can move between deploys (Railway volume mount
    # attached/renamed, STORAGE_ROOT introduced), which strands every old row
    # pointing at a path that no longer exists even though the file is still
    # sitting at <current CONVERTED_FOLDER>/<id>/. Readers must resolve
    # through these properties, which prefer the live layout and only fall
    # back to the stored path.
    def _live_converted_path(self, basename):
        try:
            from flask import current_app
            root = current_app.config['CONVERTED_FOLDER']
        except Exception:
            from config import CONVERTED_FOLDER as root
        return os.path.join(root, self.id, basename)

    @property
    def glb_path(self):
        live = self._live_converted_path('model.glb')
        if os.path.exists(live):
            return live
        return self.filename

    @property
    def usdz_path(self):
        live = self._live_converted_path('model.usdz')
        if os.path.exists(live):
            return live
        return self.usdz_filename

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


class ModelShareLink(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False, index=True)
    token_digest = db.Column(db.String(64), unique=True, nullable=False, index=True)
    permission = db.Column(db.String(10), nullable=False, default='view')
    password_hash = db.Column(db.String(255), nullable=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def is_active(self):
        return self.revoked_at is None and (
            self.expires_at is None or self.expires_at > datetime.utcnow()
        )


class ModelAnalyticsEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False, index=True)
    event_type = db.Column(db.String(30), nullable=False, index=True)
    visitor_hash = db.Column(db.String(64), nullable=True, index=True)
    referrer_domain = db.Column(db.String(255), nullable=True)
    device_type = db.Column(db.String(20), nullable=True)
    event_metadata = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class ModelHotspot(db.Model):
    """
    Stores hotspots (annotations) for 3D models
    Each hotspot has a position, title, description, and optional camera view
    """
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False)
    
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
    __table_args__ = (
        db.UniqueConstraint('model_id', 'hotspot_id', name='uq_model_hotspot_external_id'),
    )
    
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


class HotspotComment(db.Model):
    """A discussion reply on a hotspot -- lets viewers/collaborators leave
    feedback pinned to a specific spot on the model, separate from the
    hotspot's own title/description (which only its creator/an editor can set).
    """
    id = db.Column(db.Integer, primary_key=True)
    hotspot_id = db.Column(db.Integer, db.ForeignKey('model_hotspot.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    hotspot = db.relationship('ModelHotspot', backref=db.backref(
        'comments', cascade='all, delete-orphan', passive_deletes=True,
        order_by='HotspotComment.created_at'))
    user = db.relationship('User')

    def to_dict(self):
        return {
            'id': self.id,
            'body': self.body,
            'createdAt': self.created_at.isoformat() if self.created_at else None,
            'author': self.user.username if self.user else 'Unknown',
            'userId': self.user_id,
        }


class ModelVersion(db.Model):
    """
    Tracks version history of model modifications
    Each modification (transform, slice, material) creates a new version
    """
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False)
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
    __table_args__ = (
        db.UniqueConstraint('model_id', 'version_number', name='uq_model_version_number'),
    )
    
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


class ModelLOD(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False, index=True)
    level = db.Column(db.Integer, nullable=False)
    ratio = db.Column(db.Float, nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('model_id', 'level', name='uq_model_lod_level'),)

    def to_dict(self):
        return {
            'level': self.level,
            'ratio': self.ratio,
            'filename': self.filename,
            'file_size': self.file_size,
        }


class ModelDerivedAsset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    asset_metadata = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    __table_args__ = (db.UniqueConstraint('model_id', 'kind', name='uq_model_derived_kind'),)


class CameraView(db.Model):
    """Saved camera views for 3D models"""
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    orbit_theta = db.Column(db.Float, nullable=False)
    orbit_phi = db.Column(db.Float, nullable=False)
    orbit_radius = db.Column(db.Float, nullable=False)
    target_x = db.Column(db.Float, default=0.0)
    target_y = db.Column(db.Float, default=0.0)
    target_z = db.Column(db.Float, default=0.0)
    fov = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    model = db.relationship('UserModel', backref=db.backref('camera_views', lazy=True, cascade='all, delete-orphan', passive_deletes=True, order_by='CameraView.created_at'))

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'orbit': {'theta': self.orbit_theta, 'phi': self.orbit_phi, 'radius': self.orbit_radius},
            'target': {'x': self.target_x, 'y': self.target_y, 'z': self.target_z},
            'fov': self.fov
        }


class ModelMeasurement(db.Model):
    """A saved distance measurement between two points on a 3D model."""
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False, index=True)
    label = db.Column(db.String(120), nullable=True)
    # Both endpoints in model space (metres).
    ax = db.Column(db.Float, nullable=False)
    ay = db.Column(db.Float, nullable=False)
    az = db.Column(db.Float, nullable=False)
    bx = db.Column(db.Float, nullable=False)
    by = db.Column(db.Float, nullable=False)
    bz = db.Column(db.Float, nullable=False)
    distance_cm = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    model = db.relationship('UserModel', backref=db.backref('measurements', lazy=True, cascade='all, delete-orphan', passive_deletes=True, order_by='ModelMeasurement.created_at'))

    def to_dict(self):
        return {
            'id': self.id,
            'label': self.label,
            'a': {'x': self.ax, 'y': self.ay, 'z': self.az},
            'b': {'x': self.bx, 'y': self.by, 'z': self.bz},
            'distance_cm': self.distance_cm,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ModelLike(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    session_id = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('model_id', 'user_id', name='uq_model_like_user'),
        db.UniqueConstraint('model_id', 'session_id', name='uq_model_like_session'),
    )

    model = db.relationship('UserModel', backref=db.backref('likes', lazy=True, cascade='all, delete-orphan', passive_deletes=True))


class ModelSave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), db.ForeignKey('user_model.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('model_id', 'user_id', name='uq_model_save_user'),
    )

    model = db.relationship('UserModel', backref=db.backref('saves', lazy=True, cascade='all, delete-orphan', passive_deletes=True))


class AIGenerationJob(db.Model):
    """Tracks an AI text/image -> 3D generation (Meshy) so the frontend can poll
    status without a long-lived server thread (gunicorn multi-worker safe)."""
    id = db.Column(db.String(36), primary_key=True)  # our job UUID
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    kind = db.Column(db.String(10), nullable=False)        # 'text' | 'image'
    prompt = db.Column(db.Text, nullable=True)
    parent_job_id = db.Column(db.String(36), db.ForeignKey('ai_generation_job.id', ondelete='SET NULL'), nullable=True, index=True)
    preset_id = db.Column(db.Integer, db.ForeignKey('prompt_preset.id', ondelete='SET NULL'), nullable=True)

    # Meshy task ids (text is two-stage: preview -> refine)
    meshy_preview_id = db.Column(db.String(80), nullable=True)
    meshy_refine_id = db.Column(db.String(80), nullable=True)
    meshy_image_id = db.Column(db.String(80), nullable=True)
    stage = db.Column(db.String(20), nullable=True)        # 'preview' | 'refine' | 'image'

    status = db.Column(db.String(20), default='generating')  # generating | ready | failed
    progress = db.Column(db.Integer, default=0)
    model_id = db.Column(db.String(36), nullable=True)     # UserModel.id once ready
    error = db.Column(db.Text, nullable=True)

    # Advanced generation options chosen at request time (negative_prompt,
    # seed, topology, target_polycount, symmetry_mode, moderation,
    # texture_prompt, pose_mode, origin_at, remove_lighting). Kept as a
    # single JSON blob (mirrors ConversionJob.payload) since refine is a
    # second async call made later by the status-poll route, not at
    # request time, so these need to survive between the two.
    options = db.Column(db.JSON, nullable=True)
    # Temp-file path to a user-supplied refine-stage texture reference image,
    # if any (never stored inline as base64 -- see TEMP_FOLDER convention).
    texture_ref = db.Column(db.String(255), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'job_id': self.id,
            'kind': self.kind,
            'status': self.status,
            'stage': self.stage,
            'progress': self.progress,
            'model_id': self.model_id,
            'error': self.error,
            'prompt': self.prompt,
            'parent_job_id': self.parent_job_id,
            'preset_id': self.preset_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class PromptPreset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    prompt_template = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(60), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class MaterialPreset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    organization_id = db.Column(db.Integer, db.ForeignKey('organization.id', ondelete='SET NULL'), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    color = db.Column(db.String(7), nullable=False, default='#ffffff')
    metalness = db.Column(db.Float, nullable=False, default=0.0)
    roughness = db.Column(db.Float, nullable=False, default=0.5)
    opacity = db.Column(db.Float, nullable=False, default=1.0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class SiteSetting(db.Model):
    """Admin-editable runtime settings (key/value). Values are stored as
    strings; typed access goes through site_settings.py, which falls back to
    the env-derived config defaults when a key is absent."""
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<SiteSetting {self.key}>'


class AdminAuditLog(db.Model):
    """Records every mutating action taken through the admin panel: who
    (actor_id), what (action, a short dotted string like 'user.delete'),
    on what (target_type/target_id), and any extra context (detail)."""
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    action = db.Column(db.String(64), nullable=False, index=True)
    target_type = db.Column(db.String(32), nullable=True)
    target_id = db.Column(db.String(64), nullable=True)
    detail = db.Column(db.JSON, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    actor = db.relationship('User')

    def __repr__(self):
        return f'<AdminAuditLog {self.action} by {self.actor_id}>'


class ConversionJob(db.Model):
    """DB-backed conversion job queue (academic_ar pattern).

    The upload request stages files + creates a row; worker.py polls and runs
    the conversion pipeline out of the request cycle. When JOB_QUEUE is off
    the same row is processed inline in the request (status flows the same),
    so the frontend polling contract is identical in both modes.
    """
    id = db.Column(db.String(36), primary_key=True)  # job UUID == future model id
    job_type = db.Column(db.String(20), nullable=False, default='upload')
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    # pending | processing | completed | failed | dead_letter

    payload = db.Column(db.JSON, nullable=True)      # staged paths + options
    model_id = db.Column(db.String(36), nullable=True)  # UserModel.id when done
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    error = db.Column(db.Text, nullable=True)
    status_token_hash = db.Column(db.String(255), nullable=True)

    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=2)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    next_attempt_at = db.Column(db.DateTime, nullable=True, index=True)
    last_heartbeat_at = db.Column(db.DateTime, nullable=True)
    events = db.relationship('ConversionJobEvent', backref='job', lazy=True,
                             cascade='all, delete-orphan', passive_deletes=True,
                             order_by='ConversionJobEvent.created_at')

    def to_dict(self):
        return {
            'job_id': self.id,
            'job_type': self.job_type,
            'status': self.status,
            'model_id': self.model_id,
            'error': self.error,
            'attempts': self.attempts,
            'next_attempt_at': self.next_attempt_at.isoformat() if self.next_attempt_at else None,
        }


class WorkerHeartbeat(db.Model):
    worker_id = db.Column(db.String(120), primary_key=True)
    hostname = db.Column(db.String(255), nullable=True)
    process_id = db.Column(db.Integer, nullable=True)
    current_job_id = db.Column(db.String(36), nullable=True)
    started_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class ConversionJobEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.String(36), db.ForeignKey('conversion_job.id', ondelete='CASCADE'), nullable=False, index=True)
    level = db.Column(db.String(10), nullable=False, default='info')
    event = db.Column(db.String(60), nullable=False)
    message = db.Column(db.Text, nullable=True)
    attempt = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    def to_dict(self):
        return {
            'level': self.level,
            'event': self.event,
            'message': self.message,
            'attempt': self.attempt,
            'created_at': self.created_at.isoformat(),
        }
