# 🚂 Railway.app Deployment Guide

## 📋 Ön Hazırlık

### 1. Railway.app Hesabı Oluştur
- https://railway.app adresine git
- GitHub ile giriş yap (önerilen)

### 2. Railway CLI Kur (Opsiyonel)
```bash
npm install -g @railway/cli
```

---

## 🚀 Deployment Yöntemleri

### Yöntem 1: GitHub ile (Önerilen - Otomatik Deploy)

#### Adım 1: GitHub'a Push
```bash
cd "c:/Users/syste/Desktop/Melikhan/Web/Web Projeler/web_ar-main"

# Git init (eğer yoksa)
git init

# .gitignore kontrol et
# Zaten var, şunları ignore ediyor:
# venv/, __pycache__/, *.pyc, uploads/, converted/, temp/, instance/

# Dosyaları ekle
git add .
git commit -m "Initial commit - ARVision 3D Converter"

# GitHub'a push
git remote add origin https://github.com/KULLANICI_ADINIZ/arvision.git
git branch -M main
git push -u origin main
```

#### Adım 2: Railway'de Proje Oluştur
1. Railway.app'e giriş yap
2. "New Project" → "Deploy from GitHub repo"
3. Repository'yi seç (arvision)
4. Railway otomatik olarak:
   - Python'u algılar
   - `requirements.txt` kurar
   - `Procfile` ile başlatır

#### Adım 3: Environment Variables Ayarla
Railway Dashboard → Variables sekmesi:
```
SECRET_KEY=rastgele-uzun-bir-string-buraya
FLASK_ENV=production
DEBUG=False
```

#### Adım 4: PostgreSQL Ekle (Önerilen)
1. Railway Dashboard → "New" → "Database" → "PostgreSQL"
2. Railway otomatik olarak `DATABASE_URL` environment variable'ı ekler
3. `config.py` dosyasını güncelle (aşağıda)

#### Adım 5: Node.js Buildpack Ekle (obj2gltf için)
Railway Dashboard → Settings → Buildpacks:
- Python buildpack zaten var
- Node.js eklemek için: Settings → "Add Buildpack" → Node.js

`package.json` oluştur:
```json
{
  "name": "arvision",
  "version": "1.0.0",
  "dependencies": {
    "obj2gltf": "^3.1.6"
  }
}
```

#### Adım 6: Deploy!
- Railway otomatik deploy eder
- Logs'u izle: Railway Dashboard → Deployments → View Logs
- Domain: Railway otomatik bir domain verir (örn: arvision-production.up.railway.app)

---

### Yöntem 2: Railway CLI ile

```bash
# Railway CLI ile login
railway login

# Proje oluştur
railway init

# Link to existing project (eğer web'den oluşturduysan)
railway link

# Environment variables ekle
railway variables set SECRET_KEY=your-secret-key
railway variables set FLASK_ENV=production
railway variables set DEBUG=False

# Deploy
railway up

# Logs izle
railway logs
```

---

## 🔧 Kod Güncellemeleri

### 1. config.py Güncelle (PostgreSQL için)

```python
import os

# Flask
SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
DEBUG = os.environ.get('DEBUG', 'False') == 'True'
FLASK_ENV = os.environ.get('FLASK_ENV', 'development')

# Database - Railway PostgreSQL kullan
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL:
    # Railway PostgreSQL
    # Fix: Railway uses postgres:// but SQLAlchemy needs postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
else:
    # Local SQLite
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
DEFAULT_MAX_DIMENSION = float(os.environ.get('DEFAULT_MAX_DIMENSION', 0.5))
DEFAULT_COLOR = os.environ.get('DEFAULT_COLOR', '#4CAF50')

# Tools
FBX2GLTF_PATH = os.environ.get('FBX2GLTF_PATH', 'tools/FBX2glTF.exe')
OBJ2GLTF_COMMAND = os.environ.get('OBJ2GLTF_COMMAND', 'npx obj2gltf')
```

### 2. app.py Güncelle (Port için)

```python
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=app.config['DEBUG'])
```

---

## 📦 File Storage Sorunu

⚠️ **Önemli:** Railway'de dosya sistemi **ephemeral** (geçici)!

Her deploy'da `uploads/`, `converted/`, `temp/` klasörleri silinir.

### Çözüm Seçenekleri:

#### 1. Railway Volumes (Önerilen)
```bash
# Railway Dashboard → Settings → Volumes
# Mount path: /app/uploads
# Mount path: /app/converted
```

#### 2. AWS S3 / Cloudinary (Production için en iyi)
- Dosyaları cloud storage'a yükle
- `boto3` (AWS) veya `cloudinary` paketi kullan

#### 3. Railway Persistent Storage
- Railway'in kendi storage servisi (beta)

---

## 🛠️ FBX2glTF Sorunu

Railway Linux kullanır, `FBX2glTF.exe` çalışmaz!

### Çözüm:

#### 1. Linux Binary Kullan
```bash
# FBX2glTF Linux binary indir
# https://github.com/facebookincubator/FBX2glTF/releases
# tools/FBX2glTF (Linux binary)
```

`config.py` güncelle:
```python
import platform

if platform.system() == 'Windows':
    FBX2GLTF_PATH = 'tools/FBX2glTF.exe'
else:
    FBX2GLTF_PATH = 'tools/FBX2glTF'  # Linux binary
```

#### 2. Docker ile (Alternatif)
Railway Dockerfile'ı destekler:
```dockerfile
FROM python:3.11-slim

# FBX2glTF binary ekle
COPY tools/FBX2glTF /usr/local/bin/FBX2glTF
RUN chmod +x /usr/local/bin/FBX2glTF

# ... rest of Dockerfile
```

---

## 🔍 Deployment Checklist

- [ ] GitHub repo oluşturuldu
- [ ] `.gitignore` doğru (venv, uploads, converted, temp ignore edildi)
- [ ] `requirements.txt` güncel (gunicorn eklendi)
- [ ] `Procfile` oluşturuldu
- [ ] `railway.json` oluşturuldu
- [ ] `runtime.txt` oluşturuldu
- [ ] `package.json` oluşturuldu (obj2gltf için)
- [ ] `config.py` PostgreSQL için güncellendi
- [ ] `app.py` PORT için güncellendi
- [ ] Environment variables ayarlandı (SECRET_KEY, etc.)
- [ ] PostgreSQL database eklendi
- [ ] FBX2glTF Linux binary eklendi
- [ ] Railway Volumes ayarlandı (uploads, converted)
- [ ] Deploy edildi
- [ ] Test edildi (upload, conversion, view)

---

## 🐛 Troubleshooting

### Problem: "Application failed to respond"
**Çözüm:** 
- Logs'u kontrol et: `railway logs`
- PORT environment variable'ı kullanıldığından emin ol
- Gunicorn timeout'u artır (300s)

### Problem: "ModuleNotFoundError"
**Çözüm:**
- `requirements.txt` eksik paket var mı kontrol et
- Railway build logs'u kontrol et

### Problem: "Database connection failed"
**Çözüm:**
- PostgreSQL service eklendi mi?
- `DATABASE_URL` environment variable var mı?
- `config.py` DATABASE_URL'yi doğru parse ediyor mu?

### Problem: "FBX conversion failed"
**Çözüm:**
- Linux binary kullanıldığından emin ol
- Binary executable mi? `chmod +x tools/FBX2glTF`
- Logs'da FBX2glTF çıktısını kontrol et

### Problem: "File not found after upload"
**Çözüm:**
- Railway Volumes kullan
- Veya S3/Cloudinary'ye geç

### Problem: "obj2gltf not found"
**Çözüm:**
- `package.json` var mı?
- Node.js buildpack eklendi mi?
- Build logs'da npm install çalıştı mı?

---

## 📊 Railway Limits (Free Tier)

- **Execution Time:** 500 saat/ay
- **Memory:** 512MB RAM
- **Storage:** Ephemeral (geçici)
- **Bandwidth:** 100GB/ay
- **Databases:** 1 PostgreSQL (500MB)

**Not:** Üretim için Hobby Plan ($5/ay) önerilir.

---

## 🎯 Production Optimizations

### 1. Gunicorn Workers
```python
# Procfile
web: gunicorn --bind 0.0.0.0:$PORT --workers 4 --timeout 300 app:app
```

### 2. Database Connection Pooling
```python
# config.py
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}
```

### 3. Static File Serving
Railway otomatik serve eder, ama CDN kullanmak daha iyi:
- Cloudflare
- AWS CloudFront

### 4. Caching
```python
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'simple'})

@cache.cached(timeout=300)
def expensive_function():
    pass
```

### 5. Logging
```python
import logging

if not app.debug:
    # Production logging
    logging.basicConfig(level=logging.INFO)
```

---

## 🔗 Useful Links

- **Railway Dashboard:** https://railway.app/dashboard
- **Railway Docs:** https://docs.railway.app/
- **Railway Discord:** https://discord.gg/railway
- **FBX2glTF Releases:** https://github.com/facebookincubator/FBX2glTF/releases

---

## 🎉 Deployment Tamamlandı!

Railway'de deploy ettikten sonra:

1. **Domain:** `https://your-app.up.railway.app`
2. **Custom Domain:** Railway Settings → Domains → Add Custom Domain
3. **SSL:** Railway otomatik sağlar
4. **Monitoring:** Railway Dashboard → Metrics
5. **Logs:** Railway Dashboard → Deployments → Logs

**Başarılar!** 🚀
