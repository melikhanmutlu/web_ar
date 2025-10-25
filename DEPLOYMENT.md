# ARVision - Deployment Guide

## 🚀 Başka Bilgisayarda Çalıştırma Seçenekleri

### Seçenek 1: Python ile Çalıştırma (Önerilen)

**Avantajları:**
- Daha küçük dosya boyutu
- Kolay güncelleme
- Daha az hata

**Adımlar:**

1. **Python 3.8+ Kurulumu**
   - https://www.python.org/downloads/ adresinden Python indir
   - "Add Python to PATH" seçeneğini işaretle

2. **Projeyi Kopyala**
   ```bash
   # Tüm proje klasörünü kopyala
   ```

3. **Bağımlılıkları Kur**
   ```bash
   cd web_ar-main
   pip install -r requirements.txt
   ```

4. **obj2gltf Güncelle** (OBJ dosyaları için gerekli)
   ```bash
   npm install -g obj2gltf@latest
   ```

4. **Uygulamayı Çalıştır**
   ```bash
   python app.py
   ```

5. **Tarayıcıda Aç**
   - http://localhost:5000

---

### Seçenek 2: Standalone EXE (Deneysel)

**Avantajları:**
- Python kurulumu gerektirmez
- Tek dosya

**Dezavantajları:**
- Çok büyük dosya (100-200MB)
- Antivirüs uyarıları olabilir
- Daha yavaş başlatma

**Adımlar:**

1. **PyInstaller Kur**
   ```bash
   pip install pyinstaller
   ```

2. **EXE Oluştur**
   ```bash
   pyinstaller --name=ARVision --onefile --add-data "templates;templates" --add-data "static;static" --add-data "converters;converters" --hidden-import=flask --hidden-import=trimesh app.py
   ```

3. **EXE'yi Çalıştır**
   - `dist/ARVision.exe` dosyasını çalıştır
   - Tarayıcıda http://localhost:5000 aç

---

### Seçenek 3: Docker (Gelişmiş)

**Avantajları:**
- Tutarlı çalışma ortamı
- Kolay deployment

**Adımlar:**

1. **Docker Kur**
   - https://www.docker.com/products/docker-desktop

2. **Docker Image Oluştur**
   ```bash
   docker build -t arvision .
   ```

3. **Container Çalıştır**
   ```bash
   docker run -p 5000:5000 arvision
   ```

---

## 📋 Gereksinimler

### Minimum Sistem Gereksinimleri:
- **OS:** Windows 10/11, macOS 10.14+, Linux
- **RAM:** 4GB (8GB önerilen)
- **Disk:** 500MB boş alan
- **Python:** 3.8 veya üzeri (Seçenek 1 için)

### Bağımlılıklar:
Tüm bağımlılıklar `requirements.txt` dosyasında listelenmiştir.

---

## 🔧 Sorun Giderme

### Port 5000 Kullanımda Hatası
```bash
# app.py dosyasında portu değiştir
app.run(debug=False, port=5001)
```

### ModuleNotFoundError
```bash
# Eksik modülü kur
pip install <module_name>
```

### Database Hatası
```bash
# Database'i yeniden oluştur
python migrate_db.py
```

---

## 📦 Proje Yapısı

```
web_ar-main/
├── app.py              # Ana uygulama
├── models.py           # Database modelleri
├── requirements.txt    # Python bağımlılıkları
├── templates/          # HTML şablonları
├── static/            # CSS, JS, resimler
├── converters/        # 3D model dönüştürücüler
├── uploads/           # Yüklenen dosyalar
└── converted/         # Dönüştürülmüş dosyalar
```

---

## 🌐 Production Deployment

Gerçek bir sunucuda yayınlamak için:

1. **Gunicorn Kullan** (Linux/Mac)
   ```bash
   pip install gunicorn
   gunicorn -w 4 -b 0.0.0.0:5000 app:app
   ```

2. **Waitress Kullan** (Windows)
   ```bash
   pip install waitress
   waitress-serve --port=5000 app:app
   ```

3. **Nginx Reverse Proxy** (Önerilen)
   - Nginx ile SSL ve load balancing

---

## 📞 Destek

Sorun yaşarsanız:
1. `DEPLOYMENT.md` dosyasını kontrol edin
2. `requirements.txt` dosyasındaki tüm paketlerin kurulu olduğundan emin olun
3. Python versiyonunun 3.8+ olduğunu kontrol edin

---

**Not:** Standalone EXE yerine Python ile çalıştırma önerilir. Daha stabil ve güncellenebilir.
