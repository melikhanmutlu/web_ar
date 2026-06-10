# WebAR

3D modellerinizi yükleyin, tek linkle paylaşın, telefonla **artırılmış gerçeklikte** görüntüleyin.

- **Desteklenen formatlar:** OBJ, STL, FBX, GLB, glTF → hepsi otomatik olarak GLB'ye dönüştürülür
- **AR:** Android'de Scene Viewer, iOS'ta Quick Look (Blender ile otomatik USDZ üretimi)
- **Paylaşım:** Her model için tahmin edilemez UUID linki + otomatik QR kodu + iframe embed
- **Arayüz:** `<model-viewer>` tabanlı 3D görüntüleyici, klasörlü model paneli

## Mimari

```
app.py            # gunicorn entrypoint (Railway: gunicorn app:app)
worker.py         # arka plan dönüşüm işçisi (ConversionJob tablosunu poll'lar)
webar/
  __init__.py     # uygulama fabrikası (create_app)
  config.py       # tüm ayarlar env değişkenlerinden
  models.py       # User, Folder, Model3D, ConversionJob
  auth.py         # kayıt / giriş / çıkış
  views.py        # sayfalar: panel, görüntüleyici, klasörler, dosya servisi
  api.py          # JSON API: /api/upload, /api/jobs/<id>, /api/models/<id>
  jobs.py         # iş kuyruğu yaşam döngüsü (enqueue + run_conversion_job)
  conversion.py   # format → GLB dönüşüm hattı + USDZ + istatistik
  qr.py           # QR kod üretimi
templates/ static/  # Jinja2 şablonları + framework'süz CSS/JS
migrations/       # Alembic (flask db upgrade)
tools/            # FBX2glTF binary'si + Blender USDZ export scripti
```

### Yükleme akışı

1. `POST /api/upload` dosyayı `uploads/<job_id>/` altına yazar ve bir `ConversionJob` satırı oluşturur.
2. `JOB_QUEUE=true` ise `worker.py` işi sahiplenir (PostgreSQL'de `FOR UPDATE SKIP LOCKED`); değilse istek içinde anında dönüştürülür. İki modda da frontend `GET /api/jobs/<id>` ile aynı sözleşmeyi poll'lar.
3. Dönüşüm: GLB üret → trimesh ile vertex/üçgen/boyut istatistikleri → (varsa Blender) USDZ → QR kodu → `Model3D` kaydı.
4. Tamamlanınca tarayıcı `/m/<model_id>` görüntüleyici sayfasına yönlenir.

## Yerel geliştirme

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
npm install            # obj2gltf (materyalli OBJ dönüşümü için, opsiyonel)
python app.py          # http://localhost:5000 — SQLite, inline dönüşüm
```

Testler: `python -m pytest tests/`

## Railway deploy

Deploy yapılandırması öncekiyle birebir aynıdır:

- **`railway.json`** — Nixpacks builder, `ON_FAILURE` restart politikası
- **`nixpacks.toml`** — Python 3.11 + Node 20 + Blender + assimp; başlangıçta
  `flask db upgrade` → `worker.py` (arka plan) → `gunicorn app:app`
- **`runtime.txt`**, **`.nixpacksignore`**, **`requirements.txt`**, **`package.json`** korunmuştur

### Ortam değişkenleri

| Değişken | Açıklama |
|---|---|
| `DATABASE_URL` | Railway PostgreSQL eklentisi otomatik sağlar (yoksa SQLite) |
| `SECRET_KEY` | Production'da mutlaka ayarlayın |
| `JOB_QUEUE` | `true` → dönüşümleri worker süreci yapar (production önerisi) |
| `USDZ_EXPORT` | iOS için USDZ üretimi (varsayılan açık; Blender yoksa sessizce atlanır) |
| `PUBLIC_BASE_URL` | QR linkleri için taban URL (Railway'de `RAILWAY_PUBLIC_DOMAIN`'den otomatik) |
| `WEB_AR_UPLOAD_DIR` / `WEB_AR_CONVERTED_DIR` / `WEB_AR_QR_DIR` | Kalıcılık için bir Railway volume'üne yönlendirin |

> **Not:** Yüklenen dosyaların deploy'lar arasında kaybolmaması için Railway'de bir
> volume oluşturup `WEB_AR_*_DIR` değişkenlerini o volume'e yönlendirin.
