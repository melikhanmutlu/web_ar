# 📦 Model Version Management System

## 🎯 Genel Bakış

Model Version Management sistemi, kullanıcıların 3D modellerinde yaptıkları tüm değişiklikleri otomatik olarak takip eder ve geçmiş versiyonlara dönme imkanı sağlar.

## 🔄 Versiyon Oluşturma

Her önemli işlem otomatik olarak yeni bir versiyon oluşturur:

### 1. **Upload** (İlk Yükleme)
```
Kullanıcı → Model Yükle → Version 1 oluşturulur
```
- **Operation Type:** `upload`
- **Details:** Original filename, file type, max dimension
- **Comment:** "Initial upload"

### 2. **Transform** (Dönüştürme)
```
Kullanıcı → Scale/Rotate uygula → Save → Version 2 oluşturulur
```
- **Operation Type:** `transform` veya `material` veya `transform+material`
- **Details:** Scale, rotation, color, metalness, roughness
- **Comment:** "Model modifications saved"

### 3. **Slice** (Kesme)
```
Kullanıcı → Slice uygula → Version 3 oluşturulur
```
- **Operation Type:** `slice`
- **Details:** Plane origin, plane normal, keep side
- **Comment:** "Sliced model (keep positive/negative side)"

### 4. **Restore** (Geri Yükleme)
```
Kullanıcı → Eski versiyona dön → Version 4 oluşturulur
```
- **Operation Type:** `restore`
- **Details:** Restored from version number
- **Comment:** "Restored from version X"

## 📊 Database Schema

### ModelVersion Tablosu

```python
class ModelVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(36), ForeignKey('user_model.id'))
    version_number = db.Column(db.Integer)  # 1, 2, 3, ...
    filename = db.Column(db.String(255))  # converted/{uuid}/version_X.glb
    file_size = db.Column(db.Integer)
    
    # Operation details
    operation_type = db.Column(db.String(50))  # upload, transform, slice, material
    operation_details = db.Column(db.JSON)  # Operation parameters
    
    # Metadata
    dimensions = db.Column(db.JSON)  # {x, y, z, max}
    vertices = db.Column(db.Integer)
    faces = db.Column(db.Integer)
    
    # Timestamps
    created_at = db.Column(db.DateTime)
    
    # Optional comment
    comment = db.Column(db.String(500))
```

## 🔌 API Endpoints

### 1. Get Version History
```http
GET /api/versions/{model_id}
```

**Response:**
```json
{
  "success": true,
  "versions": [
    {
      "id": 1,
      "version_number": 3,
      "operation_type": "slice",
      "operation_details": {
        "plane_origin": [0, 0, 0],
        "plane_normal": [1, 0, 0],
        "keep_side": "positive"
      },
      "dimensions": {"x": 10, "y": 20, "z": 15, "max": 20},
      "vertices": 5000,
      "faces": 10000,
      "file_size": 500000,
      "file_size_formatted": "488.3 KB",
      "created_at": "2025-11-02 13:45:30",
      "comment": "Sliced model (keep positive side)"
    },
    {
      "id": 2,
      "version_number": 2,
      "operation_type": "transform",
      ...
    }
  ]
}
```

### 2. Restore Version
```http
POST /api/versions/{model_id}/restore/{version_number}
```

**Response:**
```json
{
  "success": true,
  "message": "Restored to version 2"
}
```

**Not:** Restore işlemi mevcut durumu korumak için önce yeni bir versiyon oluşturur!

### 3. Delete Version
```http
DELETE /api/versions/{model_id}/delete/{version_number}
```

**Response:**
```json
{
  "success": true,
  "message": "Deleted version 2"
}
```

### 4. Download Version
```http
GET /api/versions/{model_id}/download/{version_number}
```

**Response:** GLB file download (model_v{version_number}.glb)

## 💾 Dosya Yapısı

```
converted/
└── {model_id}/
    ├── model.glb              # Current version (aktif model)
    ├── version_1.glb          # Version 1 (initial upload)
    ├── version_2.glb          # Version 2 (after transform)
    ├── version_3.glb          # Version 3 (after slice)
    └── model_backup_*.glb     # Old backup system (deprecated)
```

## 🔧 Backend Functions

### version_manager.py

```python
# Create a new version
create_version(
    model_id='uuid',
    operation_type='transform',
    operation_details={'scale': 2.0},
    comment='Scaled 2x'
)

# Get version history
versions = get_version_history('uuid')

# Restore to version
restore_version('uuid', version_number=2)

# Delete version
delete_version('uuid', version_number=3)

# Cleanup old versions (keep last 10)
cleanup_old_versions('uuid', keep_last_n=10)
```

## 📝 Migration

Database migration gerekli:

```bash
# Create migration
flask db migrate -m "Add ModelVersion table"

# Apply migration
flask db upgrade
```

**Manuel SQL (SQLite):**
```sql
CREATE TABLE model_version (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id VARCHAR(36) NOT NULL,
    version_number INTEGER NOT NULL,
    filename VARCHAR(255) NOT NULL,
    file_size INTEGER,
    operation_type VARCHAR(50) NOT NULL,
    operation_details TEXT,  -- JSON
    dimensions TEXT,  -- JSON
    vertices INTEGER,
    faces INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    comment VARCHAR(500),
    FOREIGN KEY (model_id) REFERENCES user_model(id) ON DELETE CASCADE
);

CREATE INDEX idx_model_version_model_id ON model_version(model_id);
CREATE INDEX idx_model_version_created_at ON model_version(created_at);
```

## 🎨 Frontend Integration (Gelecek)

### Version History UI

```html
<!-- Version History Panel -->
<div id="versionHistoryPanel">
    <h3>Version History</h3>
    <div id="versionList">
        <!-- Version items will be loaded here -->
    </div>
</div>
```

### JavaScript

```javascript
// Load version history
async function loadVersionHistory(modelId) {
    const response = await fetch(`/api/versions/${modelId}`);
    const data = await response.json();
    
    if (data.success) {
        displayVersions(data.versions);
    }
}

// Restore version
async function restoreVersion(modelId, versionNumber) {
    const response = await fetch(
        `/api/versions/${modelId}/restore/${versionNumber}`,
        { method: 'POST' }
    );
    
    if (response.ok) {
        window.location.reload();  // Reload to show restored model
    }
}

// Download version
function downloadVersion(modelId, versionNumber) {
    window.location.href = `/api/versions/${modelId}/download/${versionNumber}`;
}
```

## 🔒 Güvenlik

- ✅ Version dosyaları sadece model sahibi tarafından erişilebilir (auth gerekli)
- ✅ Restore işlemi mevcut durumu korur (yeni versiyon oluşturur)
- ✅ Delete işlemi hem dosyayı hem DB kaydını siler
- ✅ Cascade delete: Model silindiğinde tüm versiyonları da silinir

## 📈 Performans

### Disk Kullanımı
- Her versiyon tam bir GLB kopyası (~500KB - 5MB)
- 10 versiyon = ~5-50MB per model
- Otomatik cleanup ile eski versiyonlar silinebilir

### Öneriler
- Son 10 versiyonu tut, eskilerini sil
- Büyük modeller için compression kullan
- Cloud storage entegrasyonu (S3, etc.)

## 🚀 Gelecek Geliştirmeler

### Phase 1 (Mevcut) ✅
- [x] Backend version tracking
- [x] API endpoints
- [x] Automatic version creation
- [x] Restore functionality

### Phase 2 (Planlanan)
- [ ] Frontend UI (version history panel)
- [ ] Version comparison (before/after preview)
- [ ] Version diff visualization
- [ ] Comment editing
- [ ] Version branching

### Phase 3 (İleri Seviye)
- [ ] Incremental backups (delta storage)
- [ ] Cloud storage integration
- [ ] Collaborative versioning
- [ ] Version merge functionality

## 📖 Kullanım Örnekleri

### Örnek 1: Model Düzenleme Workflow
```
1. User uploads model.stl
   → Version 1 created (upload)

2. User applies scale 2x and rotation 90°
   → Clicks "Save Changes"
   → Version 2 created (transform)

3. User changes color to red
   → Clicks "Save Changes"
   → Version 3 created (material)

4. User applies X-axis slice
   → Clicks "Apply Slice"
   → Version 4 created (slice)

5. User realizes mistake, wants to go back
   → Opens version history
   → Clicks "Restore" on Version 2
   → Version 5 created (restore from v2)
   → Model is now at Version 2 state
```

### Örnek 2: Version Cleanup
```python
# Keep only last 5 versions
from version_manager import cleanup_old_versions

cleanup_old_versions(model_id='uuid', keep_last_n=5)
# Deletes versions older than the last 5
```

## 🐛 Troubleshooting

### Problem: Version oluşturulmuyor
```python
# Check logs
logger.info(f"Created version entry for {model_id}")
logger.error(f"Failed to create version: {error}")
```

### Problem: Restore çalışmıyor
```python
# Check if version file exists
version = ModelVersion.query.filter_by(
    model_id=model_id, 
    version_number=version_number
).first()

if not os.path.exists(version.filename):
    logger.error(f"Version file not found: {version.filename}")
```

### Problem: Disk doldu
```python
# Cleanup old versions
from version_manager import cleanup_old_versions

# For all models
models = UserModel.query.all()
for model in models:
    cleanup_old_versions(model.id, keep_last_n=5)
```

## 📞 Support

Sorular için: [GitHub Issues](https://github.com/melikhanmutlu/web_ar/issues)
