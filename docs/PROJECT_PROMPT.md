# ARVision - 3D Model Converter & AR Viewer - Full Stack Application Prompt

## 🎯 Project Overview

Create a modern, full-stack web application called **ARVision** that converts 3D models to web and AR-ready formats (GLB/GLTF). The application should have a beautiful, minimalist UI with dark/light mode support, user authentication, and comprehensive 3D model management features.

---

## 🏗️ Technology Stack

### Backend
- **Framework:** Flask (Python 3.8+)
- **Database:** SQLAlchemy with SQLite
- **Authentication:** Flask-Login
- **File Handling:** Werkzeug
- **3D Processing:** Trimesh, PyGLTFlib
- **External Tools:** 
  - FBX2glTF (for FBX conversion)
  - obj2gltf (Node.js package for OBJ conversion)

### Frontend
- **CSS Framework:** Tailwind CSS 3.x
- **Fonts:** Google Fonts (Poppins, Inter)
- **Icons:** SVG icons (inline)
- **3D Viewer:** model-viewer (Google)
- **JavaScript:** Vanilla JS (no frameworks)

### File Structure
```
web_ar-main/
├── app.py                 # Main Flask application
├── models.py              # Database models
├── auth.py                # Authentication blueprint
├── config.py              # Configuration
├── requirements.txt       # Python dependencies
├── migrate_db.py          # Database migration script
├── start.bat              # Quick start script (Windows)
├── templates/
│   ├── base.html         # Base template with navbar
│   ├── index.html        # Homepage with upload
│   ├── my_models.html    # Model management page
│   ├── view.html         # 3D model viewer
│   ├── login.html        # Login page
│   └── register.html     # Registration page
├── static/
│   ├── css/
│   │   └── style.css     # Custom styles
│   ├── js/
│   │   └── main.js       # Main JavaScript
│   └── favicon.ico
├── converters/
│   ├── __init__.py
│   ├── base_converter.py # Base converter class
│   ├── obj_converter.py  # OBJ to GLB converter
│   ├── fbx_converter.py  # FBX to GLB converter
│   └── stl_converter.py  # STL to GLB converter
├── uploads/              # Temporary upload directory
├── converted/            # Converted model storage
├── temp/                 # Temporary processing files
└── instance/
    └── app.db           # SQLite database
```

---

## 📊 Database Schema

### User Table
```python
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    models = db.relationship('UserModel', backref='owner', lazy=True)
    folders = db.relationship('Folder', backref='owner', lazy=True)
```

### UserModel Table
```python
class UserModel(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID
    filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_type = db.Column(db.String(50))
    vertices = db.Column(db.Integer, nullable=True)
    faces = db.Column(db.Integer, nullable=True)
    is_watertight = db.Column(db.Boolean, nullable=True)
    bounds = db.Column(db.String(255), nullable=True)  # JSON string
    color = db.Column(db.String(7), nullable=True)  # Hex color
    qr_code = db.Column(db.String(255), nullable=True)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
```

### Folder Table
```python
class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    models = db.relationship('UserModel', backref='folder', lazy=True)
```

---

## 🎨 UI/UX Design Specifications

### Color Palette

**Light Mode:**
- Background: `#f9fafb` (gray-50)
- Cards: `#ffffff` (white)
- Text Primary: `#111827` (gray-900)
- Text Secondary: `#6b7280` (gray-500)
- Border: `#e5e7eb` (gray-200) with 50% opacity
- Accent: `#06b6d4` (cyan-500)

**Dark Mode:**
- Background: `#0a0e1a` (custom dark blue)
- Cards: `#1a1f2e` to `#151923` (gradient)
- Text Primary: `#ffffff` (white)
- Text Secondary: `#9ca3af` (gray-400)
- Border: `#374151` (gray-700) with 30% opacity
- Accent: `#22d3ee` (cyan-400)

### Abstract Background Pattern
- Fixed position, z-index: -1
- 5 radial gradients (cyan, purple, blue, pink, light cyan)
- Light mode opacity: 0.15
- Dark mode opacity: 0.12
- Smooth 20s animation

### Typography
- **Primary Font:** Poppins (headings, bold elements)
- **Secondary Font:** Inter (body text)
- **Logo:** "arvision" - 4xl, bold, hover opacity 80%

### Layout
- **Max Width:** 1280px (max-w-7xl) for content
- **Navbar:** Fixed, backdrop blur, 80% opacity
- **Spacing:** Consistent padding (px-4, py-12)
- **Responsive:** Mobile-first design

---

## 🔧 Core Features & Functionality

### 1. Homepage (index.html)

**Upload Section:**
- Drag & drop area with hover effects
- File input (hidden, triggered by click)
- Supported formats: FBX, OBJ, GLB, GLTF, STL (max 100MB)
- Icon: Upload cloud (SVG, cyan color, 24x24)
- Text: "Drag & drop your 3D models here" (text-2xl)
- Subtext: "or click to browse" (text-gray-500)
- Format info: "Supported formats: FBX, OBJ, GLB, GLTF, STL (max. 100MB)"

**Optional MTL/Texture Upload:**
- Shown only for OBJ files
- Multiple texture file support (.jpg, .jpeg, .png, .tga, .bmp)

**Options Section:**
Two toggle cards with minimal design:

1. **Limit Model Size:**
   - Toggle switch (cyan when active)
   - Input field (10-100 cm range, default 50)
   - Unit display: "cm"
   - Positioned to the right of label

2. **Apply Color:**
   - Toggle switch (cyan when active)
   - Color picker input
   - Hex input field (pattern: #RRGGBB)
   - Positioned to the right of label

**Submit Button:**
- Full width gradient (cyan-500 to blue-600)
- Text: "Upload and Convert"
- Upload icon on the left
- Disabled state until file selected
- Hover effects: scale 1.02, shadow increase

**Features Section:**
4 cards in grid (1 col mobile, 2 tablet, 4 desktop):

1. **Multiple Formats** (Cyan icon)
   - Icon: Upload cloud
   - Description: "Support for FBX, OBJ, STL, and GLTF with textures and materials"

2. **AR Ready** (Red icon)
   - Icon: Eye
   - Description: "View your models in AR on iPhone and Android devices"

3. **Fast Conversion** (Green icon)
   - Icon: Lightning bolt
   - Description: "Quick and efficient conversion process"

4. **Save History** (Orange icon)
   - Icon: Download
   - Description: "Registered users can access their conversion history"

**Card Styling:**
- No background (transparent)
- Border: 1px, gray-200/50 (light), gray-700/30 (dark)
- Shadow: sm, hover: lg
- Hover: scale 1.05, border color changes to accent
- Icon container: 16x16, rounded-full, colored background (20% opacity)

---

### 2. My Models Page (my_models.html)

**Header Section:**
- Title: "My Models" (text-4xl, bold)
- Buttons:
  - "New Folder" (cyan gradient)
  - "Upload Model" (cyan gradient)

**Search & Filter:**
- Search input with icon
- Sort dropdown (Newest First, Oldest First, Name A-Z, Name Z-A)

**Breadcrumb Navigation:**
- Shows current folder path
- Clickable to navigate back

**Folders Section:**
- Title: "Folders" (text-2xl, bold)
- Grid: 1-4 columns (responsive)
- Folder cards:
  - Light: bg-gray-100
  - Dark: gradient (gray-800)
  - Folder icon (cyan)
  - Folder name
  - Delete button (top-right)
  - Drag & drop target for models
  - Hover: scale 1.05, border cyan

**Models Section:**
- Title: "Models" (text-2xl, bold)
- "Delete Selected" button (hidden until selection)
- Grid: 1-4 columns (responsive)
- Model cards:
  - Light: bg-white
  - Dark: bg-gray-800
  - Checkbox (top-left) for multi-select
  - Selection overlay (blue, opacity 0-20%)
  - Model filename (truncated)
  - Upload date
  - File size
  - Action buttons:
    - View (eye icon)
    - Move to folder (arrows icon)
    - Delete (trash icon, red)
  - Draggable to folders

**Modals:**

1. **Create Folder Modal:**
   - Input: Folder name
   - Buttons: Cancel, Create

2. **Upload Model Modal:**
   - File input
   - Folder selection dropdown
   - Options: Limit size, Apply color
   - Progress bar during upload
   - Buttons: Cancel, Upload

3. **Move to Folder Modal:**
   - Folder selection dropdown
   - Buttons: Cancel, Move

---

### 3. 3D Viewer Page (view.html)

**Model Viewer:**
- Google's model-viewer component
- Full viewport height
- Controls:
  - Auto-rotate
  - Camera controls (orbit, zoom, pan)
  - AR button (iOS/Android)
- Loading spinner
- Error handling

**Model Info Panel:**
- Model name
- Dimensions (X, Y, Z, Max)
- File size
- Upload date
- Vertices/Faces count
- Watertight status

**Action Buttons:**
- Download GLB
- View in AR (QR code for mobile)
- Share link
- Delete model

**QR Code:**
- Generated for AR viewing
- Displayed in modal
- Downloadable

---

### 4. Authentication Pages

**Login Page (login.html):**
- Centered card design
- Fields:
  - Username/Email
  - Password
  - Remember me checkbox
- Submit button (cyan gradient)
- Link to register page
- Error messages (red background)

**Register Page (register.html):**
- Centered card design
- Fields:
  - Username
  - Email
  - Password
  - Confirm Password
- Submit button (cyan gradient)
- Link to login page
- Validation:
  - Username: 3-80 chars, unique
  - Email: valid format, unique
  - Password: min 6 chars
  - Passwords must match

---

## 🔄 3D Conversion Logic

### Base Converter Class (base_converter.py)

**Features:**
- Status tracking (PENDING, CONVERTING, COMPLETED, ERROR)
- Logging system
- Error handling
- Progress updates
- Cleanup on failure

**Methods:**
- `convert(input_path, output_path, **options)` - Abstract method
- `update_status(status)` - Update conversion status
- `log_operation(message)` - Log conversion steps
- `handle_error(error_message)` - Error handling
- `cleanup()` - Clean up temporary files

### OBJ Converter (obj_converter.py)

**Process:**
1. Validate input file
2. Check for MTL file
3. Copy textures to temp directory
4. Run obj2gltf command:
   ```bash
   npx obj2gltf -i input.obj -o output.glb --checkTransparency --binary
   ```
5. Post-process:
   - Apply color if requested (remove textures, apply solid color)
   - Scale to max dimension if requested
6. Export final GLB

**Options:**
- `color` (hex string): Apply solid color
- `max_dimension` (float): Maximum dimension in meters

### FBX Converter (fbx_converter.py)

**Process:**
1. Validate input file
2. Try to read dimensions with pyassimp (optional)
3. Run FBX2glTF command:
   ```bash
   FBX2glTF.exe -i input.fbx -o output.glb --binary
   ```
   - Use `stdin=subprocess.DEVNULL` to prevent hanging
4. Post-process with Trimesh:
   - Load GLB
   - Apply scaling if requested
   - Apply color if requested
   - Concatenate scene to single mesh
   - Export final GLB

**Options:**
- `color` (hex string): Apply solid color
- `max_dimension` (float): Maximum dimension in meters

### STL Converter (stl_converter.py)

**Process:**
1. Load STL with Trimesh
2. Apply color if requested
3. Scale to max dimension if requested
4. Export as GLB

**Options:**
- `color` (hex string): Apply solid color
- `max_dimension` (float): Maximum dimension in meters

---

## 🛣️ API Routes

### Public Routes

**GET /**
- Homepage with upload form
- Flash messages display
- File upload via POST

**POST /upload_model**
- File upload handling
- Validation (file type, size)
- Unique ID generation (UUID)
- Temporary file storage
- Converter selection based on file type
- Conversion execution
- Model info extraction (vertices, faces, bounds)
- Database storage
- QR code generation
- Cleanup
- Response: JSON with model_id and redirect URL

**GET /view/<model_id>**
- Display 3D model viewer
- Model info from database
- model-viewer component
- AR support

**GET /converted_files/<model_id>/<filename>**
- Serve converted GLB files
- Security: validate model_id format
- CORS headers for AR

**GET /qr_codes/<filename>**
- Serve QR code images

### Authenticated Routes (login_required)

**GET /my_models**
- Display user's models and folders
- Folder navigation
- Search and filter
- Drag & drop support

**POST /create_folder**
- Create new folder
- Validation: name required
- Associate with current user

**POST /delete_folder/<folder_id>**
- Delete folder
- Move models to root (folder_id = None)
- Permission check: owner only

**POST /move_model**
- Move model to folder
- Permission check: owner only

**POST /delete_model/<model_id>**
- Delete model from database
- Delete files from disk
- Permission check: owner or anonymous

**POST /delete_selected_models**
- Bulk delete models
- Permission check: owner or anonymous

### Authentication Routes (auth blueprint)

**GET /auth/login**
- Display login form

**POST /auth/login**
- Validate credentials
- Create session
- Redirect to next page or homepage

**GET /auth/register**
- Display registration form

**POST /auth/register**
- Validate input
- Check username/email uniqueness
- Hash password (Werkzeug)
- Create user
- Auto-login
- Redirect to homepage

**GET /auth/logout**
- Clear session
- Redirect to homepage

---

## 🎨 Frontend JavaScript Features

### Dark Mode Toggle
- localStorage persistence
- System preference detection
- Smooth transition
- Icon change (sun/moon)

### File Upload
- Drag & drop support
- File validation (type, size)
- Preview selected file name
- Show/hide MTL upload for OBJ
- Enable/disable submit button

### Toggle Switches
- Show/hide input fields
- Smooth transitions
- State management

### Color Picker
- Sync between color input and hex input
- Validation for hex format
- Default color: #4CAF50

### Model Selection (my_models.html)
- Checkbox toggle on card click
- Multi-select support
- Show/hide delete button
- Visual feedback (overlay, border)

### Drag & Drop (my_models.html)
- Drag model cards
- Drop on folder cards
- Visual feedback (border highlight)
- AJAX move request

### Modals
- Open/close animations
- Click outside to close
- Form validation
- AJAX submissions

### Search & Filter
- Real-time search
- Sort by date/name
- Update URL parameters

---

## 🔐 Security Features

1. **Authentication:**
   - Password hashing (Werkzeug)
   - Session management (Flask-Login)
   - CSRF protection (Flask-WTF recommended)

2. **File Upload:**
   - File type validation (extension + MIME type)
   - File size limit (100MB)
   - Secure filename (Werkzeug)
   - Unique storage paths (UUID)

3. **Database:**
   - SQL injection prevention (SQLAlchemy ORM)
   - Input validation
   - Permission checks

4. **API:**
   - Login required decorators
   - Owner verification
   - Error handling
   - Logging

---

## 📱 Responsive Design

### Breakpoints (Tailwind)
- **sm:** 640px
- **md:** 768px
- **lg:** 1024px
- **xl:** 1280px

### Grid Layouts
- **Folders/Models:** 1 col (mobile) → 2 (tablet) → 3 (desktop) → 4 (xl)
- **Features:** 1 col (mobile) → 2 (tablet) → 4 (desktop)

### Navigation
- Hamburger menu on mobile (optional)
- Responsive spacing
- Touch-friendly buttons (min 44x44px)

---

## ⚙️ Configuration (config.py)

```python
import os

# Flask
SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
DEBUG = True

# Database
SQLALCHEMY_DATABASE_URI = 'sqlite:///instance/app.db'
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Upload
UPLOAD_FOLDER = 'uploads'
CONVERTED_FOLDER = 'converted'
TEMP_FOLDER = 'temp'
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB
ALLOWED_EXTENSIONS = {'obj', 'fbx', 'glb', 'gltf', 'stl'}
ALLOWED_TEXTURE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'tga', 'bmp'}

# Conversion
DEFAULT_MAX_DIMENSION = 0.5  # meters (50cm)
DEFAULT_COLOR = '#4CAF50'

# Tools
FBX2GLTF_PATH = 'tools/FBX2glTF.exe'  # Windows
OBJ2GLTF_COMMAND = 'npx obj2gltf'
```

---

## 📦 Dependencies (requirements.txt)

```
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-Migrate==4.0.5
Werkzeug==3.0.1
trimesh==4.0.5
pygltflib==1.16.1
numpy==1.24.3
Pillow==10.1.0
qrcode==7.4.2
python-slugify==8.0.1
pyassimp==4.1.4
```

---

## 🚀 Deployment Instructions

### Development
```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies
npm install -g obj2gltf@latest

# Initialize database
python migrate_db.py

# Run application
python app.py
```

### Production
- Use Gunicorn (Linux/Mac) or Waitress (Windows)
- Set environment variables (SECRET_KEY, DATABASE_URL)
- Use PostgreSQL instead of SQLite
- Set DEBUG=False
- Use Nginx reverse proxy
- Enable HTTPS
- Set up file storage (S3, etc.)

---

## 🎯 Key Implementation Notes

1. **File Handling:**
   - Always use secure_filename()
   - Generate unique IDs (UUID) for storage
   - Clean up temporary files after conversion
   - Handle large files with streaming

2. **3D Processing:**
   - Use subprocess with stdin=DEVNULL for external tools
   - Set timeouts (300s) for conversions
   - Handle both Scene and Trimesh objects
   - Preserve textures when possible

3. **UI/UX:**
   - Minimize nested containers
   - Use subtle borders (50% opacity light, 30% dark)
   - Smooth transitions (300ms)
   - Hover effects on interactive elements
   - Loading states for async operations

4. **Error Handling:**
   - Try-except blocks for all conversions
   - Detailed logging
   - User-friendly error messages
   - Cleanup on failure

5. **Performance:**
   - Lazy loading for models
   - Pagination for large lists
   - Optimize images and assets
   - Cache static files

---

## 🎨 Design Principles

1. **Minimalism:** Clean, uncluttered interface
2. **Consistency:** Same patterns throughout
3. **Accessibility:** Proper contrast, keyboard navigation
4. **Feedback:** Loading states, success/error messages
5. **Responsiveness:** Mobile-first approach
6. **Modern:** Gradients, shadows, smooth animations

---

## 📝 Additional Features to Consider

1. **Model Preview Thumbnails:** Generate preview images for model cards
2. **Batch Upload:** Upload multiple files at once
3. **Model Sharing:** Public/private links
4. **API Keys:** For programmatic access
5. **Usage Statistics:** Track conversions, storage
6. **Model Optimization:** Reduce polygon count, compress textures
7. **Export Options:** Multiple formats (USDZ for iOS AR)
8. **Collaboration:** Share folders with other users
9. **Version History:** Track model changes
10. **Comments/Notes:** Add metadata to models

---

## 🔍 Testing Checklist

- [ ] Upload all supported formats (OBJ, FBX, STL, GLB, GLTF)
- [ ] Upload with textures (OBJ + MTL + images)
- [ ] Apply color option
- [ ] Limit size option
- [ ] Dark/light mode toggle
- [ ] User registration
- [ ] User login/logout
- [ ] Create folder
- [ ] Move model to folder
- [ ] Delete model
- [ ] Delete folder
- [ ] Multi-select delete
- [ ] Drag & drop models to folders
- [ ] Search models
- [ ] Sort models
- [ ] View model in 3D
- [ ] AR viewing (mobile)
- [ ] QR code generation
- [ ] Download GLB
- [ ] Responsive design (mobile, tablet, desktop)
- [ ] Error handling (invalid files, large files, etc.)

---

## 🎯 Success Criteria

1. **Functionality:** All conversions work correctly
2. **UI/UX:** Beautiful, intuitive interface
3. **Performance:** Fast conversions (<30s for typical models)
4. **Reliability:** Proper error handling, no crashes
5. **Security:** Safe file handling, authentication
6. **Responsiveness:** Works on all devices
7. **Accessibility:** WCAG 2.1 AA compliance
8. **Code Quality:** Clean, documented, maintainable

---

## 📚 Resources

- **Flask Documentation:** https://flask.palletsprojects.com/
- **Tailwind CSS:** https://tailwindcss.com/
- **Trimesh:** https://trimsh.org/
- **model-viewer:** https://modelviewer.dev/
- **FBX2glTF:** https://github.com/facebookincubator/FBX2glTF
- **obj2gltf:** https://github.com/CesiumGS/obj2gltf

---

## 🎉 Final Notes

This is a complete, production-ready specification for ARVision. The application should be:
- **Beautiful:** Modern, minimalist design with smooth animations
- **Functional:** All features working correctly
- **Secure:** Proper authentication and file handling
- **Performant:** Fast conversions and responsive UI
- **Maintainable:** Clean code, good documentation
- **Scalable:** Ready for production deployment

Good luck building ARVision! 🚀
