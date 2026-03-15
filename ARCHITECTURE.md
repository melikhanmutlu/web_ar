# ARVision Architecture

> System map and technical documentation for the ARVision Web AR platform.

---

## 🏗️ System Overview

ARVision is a Flask-based web application designed to view 3D models (STL, FBX, OBJ) in Augmented Reality using web standards (Model-viewer, WebXR).

### Tech Stack
- **Backend:** Flask / Python 3.11
- **Database:** SQLite (SQLAlchemy)
- **Frontend:** Vanilla JS, Model-viewer (Google), Tailwind CSS
- **Conversion:** Trimesh, pygltflib, obj2gltf, FBX2glTF

---

## 📁 Directory Structure

```
.
├── .agent/                 # [BDK] AI configuration, rules, and skills
├── converters/            # 3D model conversion logic (STL, FBX, OBJ to GLB/USDZ)
├── static/                # Frontend assets (viewer.js, CSS, 3D models)
├── templates/             # HTML templates (Flask/Jinja2)
├── uploads/               # User uploaded source models
├── converted/             # Resulting GLB/USDZ files for AR viewing
├── instance/              # SQLite database storage (app.db)
├── app.py                 # Main Flask application entry point
├── models.py              # SQLAlchemy database models
└── config.py              # Application configuration
```

---

## 🛠️ Core Components

### 1. Model Conversion Pipeline
- **STL Handler:** Uses Trimesh for standard STL to GLB conversion.
- **FBX Handler:** Leverages external `FBX2glTF` binaries.
- **OBJ Handler:** Uses `obj2gltf` (Node.js utility).
- **Auto-Scaling:** Logic in `app.py` and `viewer.js` to ensure models fit AR view space.

### 2. AR Viewing (Model-viewer)
- Integrated Google's `<model-viewer>` web component.
- Supports both **Android (Scene Viewer)** and **iOS (Quick Look / USDZ)**.
- Hotspot management and measurement tools implemented in `viewer.js`.

### 3. Folder & Permission System
- Hierarchical folder structure for organizing models (defined in `models.py`).
- User-based authentication and access control.

---

## 🤖 Agentic Configuration (`.agent/`)

Project follows the **Bilge Development Kit (BDK)** protocol:
- **Rules:** `GEMINI.md` defines primary behavior and routing.
- **Skills:** Specialized modules for `frontend-glassmorphism`, `api-security`, etc.
- **Scripts:** `checklist.py` and `verify_all.py` for quality gates.
- **Memory Bank:** Persistent documentation for architecture decisions and patterns.

---

## 🚀 Deployment

- **Recommended:** Git Bash / Linux environment for full script support.
- **Local:** `python app.py` (Development server).
- **Production:** `start_production.py` (Waitress/Gunicorn).
