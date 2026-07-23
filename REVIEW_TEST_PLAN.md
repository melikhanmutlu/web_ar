# ARVision — Kapsamlı Review & Test Planı

> **Amaç:** Gerçek bug'ları, güvenlik açıklarını, veri bütünlüğü sorunlarını ve
> performans darboğazlarını bulup kanıtlarıyla raporlamak. Kozmetik/subjektif
> "daha iyi olabilir" yorumları değil.
>
> **Her bulgu için zorunlu format:**
> 1. `dosya:satır`
> 2. Tetikleyen somut girdi/senaryo (tekrarlanabilir)
> 3. Neden hatalı/riskli olduğu
> 4. Önerilen düzeltme
>
> Kesin olmayan bulgular **"Doğrulanmadı"** bölümünde `muhtemelen` etiketiyle.
>
> **Önem sınıfları:** 🔴 Kritik (veri kaybı/güvenlik/ödeme) · 🟠 Yüksek
> (fonksiyonel bug) · 🟡 Orta (edge case) · 🔵 Düşük (kalite/perf).

Bu dosya **canlı bir checklist**'tir. Her tur sonunda kutuları işaretle,
bulguları en alttaki **Bulgu Kütüğü**'ne ekle. Sonraki oturumlarda buradan
devam edilebilir.

---

## Çalışma Yöntemi (her bulgu için)

- [ ] Bulguyu koddan **satır referansıyla** doğrula (grep/read ile).
- [ ] Mümkünse **başarısız bir test** yazarak reprodüksiyon göster
      (`tests/` altına geçici test veya mevcut suite'e ekleme).
- [ ] Ortam kaynaklı hatayı (numpy/native/Blender/Node eksikliği) gerçek
      bug'dan **ayır** — "environment" etiketi.
- [ ] Kanıtı olmayanı **Doğrulanmadı** bölümüne yaz, `muhtemelen` de.

### Ortam ön-kontrolü (denetime başlamadan bir kez)

- [ ] `pytest -q` — mevcut suite yeşil mi, hangileri kırık? (99 test dosyası)
- [ ] `flask db heads` — **tek head** mi? (geçmişte multiple-heads bug'ı vardı)
- [ ] `npm run lint` ve `npm run check` temiz mi?
- [ ] `pip-audit` ve `bandit -r . -q` baseline çıktısını kaydet (yeni bulgu
      farkını görmek için).
- [ ] Native bağımlılıklar mevcut mu: `python -c "import numpy, trimesh, pygltflib, shapely, scipy, networkx"`; Node araçları (`obj2gltf`, `gltfpack`, `gltf-transform`); `tools/FBX2glTF`; Blender/Assimp.

---

## 1. Backend / Route Mantığı (`blueprints/`, `admin.py`, `services/`)

### 1a. Blueprint'ler — mutasyon endpoint denetimi

Her blueprint için: **yetki** (`check_model_mutation_allowed` /
`ModelAccessService` mı ad-hoc mı) · **input validation** (WTForms mı manuel
`request.json`/`request.form` mı; tip/uzunluk/aralık/negatif) · **race
condition** (paralel istek) · **hata yolu** (stack trace sızıntısı, partial
commit).

- [ ] `upload.py` — dosya tipi/boyut limiti, chunked upload birleştirme, staging temizliği
- [ ] `viewer.py` — private/share-link/anonim görüntüleme yol ayrımı
- [ ] `models_crud.py` — create/rename/delete; purge race (aynı anda iki purge)
- [ ] `model_editing.py` — mutation yetkisi + edit-token yolu
- [ ] `model_geometry.py` — transform/slice input aralıkları
- [ ] `model_files.py` — dosya indirme/serve path güvenliği
- [ ] `model_metadata.py` — metin alanları uzunluk/XSS
- [ ] `versions.py` — restore yetkisi, snapshot tutarlılığı
- [ ] `hotspots.py` — hotspot metni (XSS), IDOR (hotspot_id)
- [ ] `sharing.py` — share-link oluştur/iptal/expiry; iptal edilen link hâlâ çalışıyor mu
- [ ] `organizations.py` — org üyeliği kontrolü, davet/rol değişimi yetkisi
- [ ] `ai_generation.py` — Meshy job başlatma, rate limit, kota
- [ ] `ai_image.py` — görsel girdi `data:` URI zorunluluğu (SSRF)
- [ ] `engagement.py` — analytics/lead POST'ları, sendBeacon CSRF yolu
- [ ] `discover.py` — public listeleme; private sızıntı var mı
- [ ] `scenes.py` — sahne CRUD yetkisi
- [ ] `webhooks.py` — imza doğrulama, SSRF target guard
- [ ] `seo.py` — sitemap/robots; kullanıcı verisi sızıntısı
- [ ] `health.py` — 1f'e bakınız
- [ ] `api_tokens.py` — token oluştur/iptal, scope, hash saklama
- [ ] `material_presets.py` — preset CRUD yetki/validation
- [ ] `billing.py` — **ödeme**; 3. bölüm ile birlikte incele
- [ ] `main.py` — anasayfa/statik yollar

**Yetki senaryoları (her mutasyon için ayrı ayrı dene):**
- [ ] Owner değil ama **geçerli edit-token** olan biri
- [ ] Org üyesi **olmayan** biri org modeline erişmeye çalışıyor
- [ ] **Süresi dolmuş** share link
- [ ] **İptal/revoke edilmiş** share link
- [ ] Anonim kullanıcı, edit-token olmadan mutasyon

### 1b. `services/` katmanı

- [ ] `model_access.py` — `ModelAccessService` tek policy noktası mı, bypass var mı
- [ ] `model_permissions.py` — `check_model_mutation_allowed` tüm yolları kapsıyor mu
- [ ] `storage.py` — root-containment: `../`, mutlak path, **symlink**, URL-encode kaçışı
- [ ] `conversion.py` / `conversion_jobs.py` — state machine (pending→processing→completed/failed/dead_letter) tutarlı mı, stale requeue doğru mu
- [ ] `upload_staging.py` — geçici dosya sızıntısı, temizlik
- [ ] `asset_quality.py` — bozuk geometri girdisinde davranış
- [ ] `webhooks.py` — SSRF/DNS-rebinding: internal IP, localhost, link-local, IPv6, redirect zinciri bypass
- [ ] `email.py` — enjeksiyon (header/CRLF), hata yutma
- [ ] `storage_quota.py` — kota aşımı hesabı, negatif/yarış
- [ ] `plans.py` / `credits.py` / `upgrade.py` — plan limitleri, kredi düşme atomikliği
- [ ] `fx.py` — USD→TRY: kur alınamazsa fallback, cache TTL dolumu, **negatif/sıfır kur**
- [ ] `invoicing.py` — tutar/vergi hesabı Decimal mı
- [ ] `payments/paytr.py`, `payments/lemonsqueezy.py`, `payments/base.py` — imza, replay, fiyat sunucuda mı hesaplanıyor
- [ ] `referrals.py` / `growth_metrics.py` / `signal_mining.py` — kötüye kullanım (self-referral), IDOR

### 1c. `worker.py` (JOB_QUEUE)

- [ ] Job claim **atomik** mi — iki worker aynı job'ı alabilir mi (`SELECT ... FOR UPDATE` / atomic UPDATE)
- [ ] Heartbeat kaybında job gerçekten requeue oluyor mu
- [ ] Crash sonrası kısmi state: dosya yazıldı ama DB commit olmadı → tutarlılık
- [ ] Worker çökerse web process etkileniyor mu; restart sonrası kaldığı yerden devam

### 1d. `admin.py`

- [ ] Admin-only guard her endpoint'te var mı (yetki bypass)
- [ ] Bulk action'lar (bulk delete/suspend) atomik mi, yarım kalma
- [ ] Audit log detail'inde secret/token sızıntısı (bkz. 6d)

---

## 2. Converter Pipeline (`converters/`) — güvenilmeyen girdi

- [ ] `base_converter.py` — `safe_join_within` / `assert_safe_obj_references` **her converter'da tutarlı** kullanılıyor mu (grep ile teyit)
- [ ] `obj_converter.py` — `mtllib`/texture path'te `../../etc/passwd`, mutlak path, sembolik referans engelleniyor mu (**zararlı .obj ile dene**)
- [ ] `fbx_converter.py` + `fbx_common/materials/postprocess/probe.py` — harici texture referansı, `FBX2glTF` binary çağrısında arg injection
- [ ] `stl_converter.py` — bozuk/aşırı büyük binary STL, hatalı üçgen sayısı header'ı
- [ ] `step_converter.py` — Blender/Assimp çağrısı timeout/limit
- [ ] **3D model bomb**: aşırı vertex/facet, sonsuz döngü, derin nesting → bellek/CPU tüketimi; **timeout ve boyut limiti var mı**
- [ ] `glb_optimizer.py`, `glb_quality.py`, `lod_generator.py`, `texture_upscale.py`, `thumbnail_render.py` — NaN vertex, sıfır normal, boş mesh → crash mı nazik hata mı
- [ ] `glb_modifier.py`, `mesh_slicer.py` — transform/slice **orijinal dosyayı bozmuyor** mu
- [ ] `version_manager.py` — snapshot restore edilebiliyor mu (**restore edip diff al**)

**Kanıt senaryoları hazırla:** kötü niyetli `.obj` (path traversal mtllib),
dev mesh (bellek), boş/NaN GLB, bozuk STEP.

---

## 3. Güvenlik (OWASP Top 10 + proje-özel)

### 3a. Auth / Session
- [ ] Session fixation: login öncesi/sonrası session id değişiyor mu
- [ ] Logout sonrası eski session cookie geçersiz mi
- [ ] Şifre reset token: **tek kullanımlık** + süreli mi, tahmin edilebilir mi

### 3b. CSRF
- [ ] Her state-changing endpoint token doğruluyor mu (form POST + raw fetch/XHR)
- [ ] `_security_head.html` global fetch wrapper bypass yolu: `<img>` GET-mutasyon, `navigator.sendBeacon`, farklı-origin form action

### 3c. XSS
- [ ] Kullanıcı girdisi (model adı, yorum, hotspot metni, lead mesajı, admin notu) `innerHTML`'de `window.escapeHtml` kullanıyor mu (grep `innerHTML`)
- [ ] Jinja `| safe` kullanılan yerler gerçekten güvenli mi (grep `|safe`/`| safe`)

### 3d. SSRF
- [ ] `ai_generator.py` `data:` URI zorunluluğu bypass: SVG içinde redirect, content-type sahteciliği
- [ ] Webhook target guard: IPv6, DNS rebinding, redirect ile atlatma

### 3e. IDOR
- [ ] model_id / version_id / hotspot_id / share_link_id / api_token / org_id tahminiyle başkasının kaynağına view/edit/delete
- [ ] Her `get_or_404` sonrası **ownership kontrolü** var mı yoksa sadece varlık kontrolü mü

### 3f. Rate limiting
- [ ] Flask-Limiter login/register/AI/upload'da devrede mi, 429 dönüyor mu
- [ ] `X-Forwarded-For` spoofing ile bypass (ProxyFix / trusted proxy ayarı)

### 3g. Path traversal (indirme/serve)
- [ ] `..%2f`, URL-encode, çift-encode, null byte `StorageService` dışına çıkıyor mu

### 3h. Ödeme güvenliği
- [ ] PayTR webhook imza gerçekten doğrulanıyor mu (hash bypass)
- [ ] **Replay**: aynı bildirim iki kez → çift kredi/çift işlem
- [ ] Fiyat/miktar **sunucuda** mı hesaplanıyor (client fiyatı manipüle edebiliyor mu)

### 3i. Secrets sızıntısı
- [ ] `SECRET_KEY`, API anahtarları log/hata mesajı/admin audit detail'ine sızıyor mu

### 3j. Otomatik tarayıcılar
- [ ] `pip-audit` — baseline ötesi yeni bulgu
- [ ] `bandit -r . ` — yeni bulgu (mevcut CI sonuçlarıyla karşılaştır)

---

## 4. Veritabanı (`models.py`, `migrations/`)

- [ ] Tüm FK'lerde `ondelete` doğru mu — user silinince model/ödeme: orphan mı, istenmeyen cascade mi (grep `ForeignKey`, `ondelete`, `cascade`)
- [ ] `flask db heads` **tek head** (48 migration)
- [ ] Sıfırdan DB'de `flask db upgrade` sorunsuz
- [ ] Son 5 migration için `downgrade()` gerçekten çalışıyor mu
- [ ] N+1: admin liste sayfaları (users/models/jobs/billing/audit_log) ve `/discover`, `/my-models`'de eksik `joinedload`/`selectinload`
- [ ] Index: sık filtrelenen kolonlar (status, created_at, user_id, plan) — `EXPLAIN` ile teyit
- [ ] Transaction bütünlüğü: `_apply_successful_payment`, bulk admin action'lar ortasında hata → yarım state
- [ ] Para alanları (amount, price) **Decimal** mı, float yuvarlama riski var mı

---

## 5. Frontend / JS (`static/js/`, `templates/`)

### 5a. Viewer araçları (`static/js/viewer/*`)
Her tool: undo/redo tutarlılığı · save sonrası yenilemede state kalıcı mı ·
hızlı ardışık tıklamada (debounce) çift kayıt/çakışma.
- [ ] `transform-editor.js` · `save-flow.js` · `material-editor.js`
- [ ] `undo-redo.js` · `ar-slicer-layers.js` · `measure-tool.js`
- [ ] `camera-overlay.js` · `presets.js` · `panel-nav.js` / `panel-ui.js`
- [ ] `annotations.js` · `versions.js` · `animation-controls.js`

### 5b. AR / mobil
- [ ] iOS Quick Look linki gerçek cihazda açılıyor mu; cihaz yoksa fallback UI
- [ ] Android Scene Viewer intent açılıyor mu; fallback

### 5c. Erişilebilirlik
- [ ] Modal focus-trap; form `for`/`aria-label` eşleşmesi; renk kontrastı WCAG AA

### 5d. Tarayıcı uyumu
- [ ] Safari/WebKit: model-viewer + AR Quick Look; Firefox WebGL fallback

### 5e. Network / cache
- [ ] Gereksiz büyük payload; statik varlık cache header'ı doğru mu; kullanıcı verisi cache'lenmiyor mu; sayfa başına tekrar eden istek

---

## 6. Sistem / Operasyonel

- [ ] Worker + web eşzamanlı (JOB_QUEUE=true): worker çökerse web etkileniyor mu, restart sonrası devam
- [ ] Disk/volume dolması: upload sırasında disk dolarsa temiz hata mı, yarım dosya mı kalıyor
- [ ] `blueprints/health.py` gerçekten DB+storage+worker durumunu yansıtıyor mu yoksa hep 200 mü
- [ ] `services/observability.py` loglarında hassas veri (şifre, token, kart benzeri alan) var mı

---

## 7. Test Kapsamı & Regresyon

- [ ] `pytest --cov` (varsa) — ödeme/auth/converter kritik yollarından test edilmemiş olanlar
- [ ] Kırık testleri ayır: gerçek bug mı, ortam mı (`test_step_converter.py`, `test_thumbnail_render.py` — numpy/native)
- [ ] `npm run test:e2e` (Playwright, Chromium preinstalled) — çalıştır, flaky'leri işaretle
- [ ] Bulunan her 🔴/🟠 bug için **regresyon testi** ekle

---

## Bulgu Kütüğü

> En yüksek önemden düşüğe sırala. Format: `dosya:satır — senaryo — neden — düzeltme`.

### 🔴 Kritik
- _(henüz yok)_

### 🟠 Yüksek
- _(henüz yok)_

### 🟡 Orta
- _(henüz yok)_

### 🔵 Düşük
- _(henüz yok)_

### ❓ Doğrulanmadı (spekülatif — `muhtemelen`)
- _(henüz yok)_

---

## İlerleme Takibi

| Bölüm | Durum | Not |
|-------|-------|-----|
| 0. Ortam ön-kontrolü | ⬜ | |
| 1. Backend/route | ⬜ | |
| 2. Converter pipeline | ⬜ | |
| 3. Güvenlik | ⬜ | |
| 4. Veritabanı | ⬜ | |
| 5. Frontend/JS | ⬜ | |
| 6. Operasyonel | ⬜ | |
| 7. Test kapsamı | ⬜ | |

_Legend: ⬜ başlanmadı · 🔄 devam · ✅ bitti_
