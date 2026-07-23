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

> **Tur 1 — 2026-07-23.** 6 paralel denetim ajanı + baseline pytest (646 passed,
> 3 failed, 2 skipped). Bulgular önem sırasına göre; çapraz-ajan tekrarları
> tekilleştirildi. Format: `dosya:satır — senaryo — neden — düzeltme`.

### 🔴 Kritik
- **K1 — Converter harici-texture URI'sinde path traversal → keyfi sunucu dosyası okuma.**
  `converters/glb_quality.py:70-88` (`_find_texture`, `embed_external_textures→finalize_glb`
  ile **her** conversion'da çalışır) ve `converters/fbx_postprocess.py:602-637`
  (`_embed_external_textures`, `search_paths` ham `image.uri` join'liyor).
  Senaryo: texture referansı mutlak path (`/etc/passwd`) veya `../../../..`
  traversal olan bir FBX/glTF yükle; `Path(root) / Path(uri)` mutlak path'te
  `root`'u atar, `../` ile sandbox'tan çıkar; dosya `read_bytes()` ile GLB binary
  chunk'ına gömülür ve saldırganın indirebildiği GLB'ye yazılır → secret/`.env`/
  başka kullanıcı asset'i sızıntısı. **Tutarsızlık:** kardeş fonksiyon
  `_embed_external_textures_gltf` (`fbx_postprocess.py:140-147`) `safe_join_within`'i
  doğru kullanıyor — bu iki yol atlanmış. Düzeltme: her aday path'i `safe_join_within`'den
  geçir, mutlak/`..` içeren `uri`'yi reddet, yalnızca `uri_path.name` kullan.
  ⚠️ Erişilebilirlik: FBX2glTF'in ham external `uri` emit etmesine bağlı — bkz.
  Doğrulanmadı D1. Kod düzeyinde kesinlikle açık.

### 🟠 Yüksek
- **Y1 — API token'ları kullanıcı deaktive/org'dan atıldıktan sonra da çalışıyor.**
  `blueprints/api_tokens.py:37-52` (`_bearer_token` yalnızca `token.is_active`'e
  bakıyor), `:121-125`. Senaryo: (a) org admin'i org-scoped `models:write` token
  üretir, sonra org'dan çıkarılır → token org modellerinde read/update/soft-delete
  yetkisini korur; (b) admin bir kullanıcıyı deaktive eder → kullanıcı login olamaz
  ama token'ı çalışmaya devam eder. Düzeltme: `_bearer_token`'da `token.user`'ı
  yükle, `not user.is_active_flag` ise reddet; org-scoped token'da her çağrıda
  `_organization_membership` yeniden kontrol et.
- **Y2 — Pillow 12.2.0: 20 bilinen CVE, güvenilmeyen görsel işliyor.**
  `requirements.txt` (pillow 12.2.0), kullanım `blueprints/model_files.py:148`
  (`Image.open`/`verify` user base64 thumbnail'de) + converters/thumbnail.
  `pip-audit` 20 açık raporluyor, hepsi **12.3.0**'da fixli. Senaryo: authenticated
  kullanıcı crafted PNG POST'lar → decoder heap/buffer sorunları → crash/DoS/memory
  corruption. Düzeltme: `pillow>=12.3.0`, pin güncelle (tek satır).
- **Y3 — Org-creator/admin olan kullanıcı silinemiyor (FK RESTRICT).**
  `models.py:156` (`Organization.created_by`, `ondelete` yok), `models.py:749`
  (`AdminAuditLog.actor_id`, `ondelete` yok); ikisi de FK-rules migration'ında
  (`8d4e1f7a2b9c`) yok. Canlı SQL ile kanıtlandı: user+org+audit ekle, `DELETE FROM
  user` → `IntegrityError: FOREIGN KEY constraint failed`. Admin "Delete user"
  → `{"success": false, "error": "Delete failed"}` (`admin.py:779-782`); bulk delete
  tek transaction, bir org-creator batch'in tamamını düşürüyor. Düzeltme: migration
  ile `admin_audit_log.actor_id` → `SET NULL`; `organization.created_by` politikası
  belirle (`SET NULL`+nullable veya `_delete_user_and_content`'te org'ları önce reassign).
- **Y4 — Version download unlisted/public modelin tüm geçmişini herkese açıyor (2 P0 testi kırık, KANITLI).**
  `blueprints/versions.py:171` (`check_model_view_allowed` — view-tier),
  `services/model_access.py:56` (yalnızca `visibility=="private"` bloklanıyor),
  varsayılan görünürlük `models.py:273` (`"unlisted"`). `tests/test_p0_hardening.py:103,109`
  anonim ve başka-kullanıcı için 403 bekliyor, ikisi de **200** alıyor. Private
  korunuyor (non-owner 403), unlisted/public'te link'i olan herkes tüm versiyon
  GLB'lerini indirebiliyor. Kod yorumu (`versions.py:167-170`) view-tier'i bilinçli
  gerekçelendiriyor → **insan kararı gerek:** ya version download owner/share-gated
  yapılsın (`check_model_mutation_allowed`), ya da 2 P0 test güncellensin.

### 🟡 Orta
- **O1 — MTL allowlist eksik.** `converters/obj_converter.py:17-20` (`_MTL_FILE_KEYS`)
  `map_ns`, PBR map'leri (`map_pr/pm/ps/...`) kapsamıyor; obj2gltf bunları çözüp
  açıyor → kapsanmayan key altında traversal validate edilmiyor. Düzeltme: obj2gltf'in
  tüm `map_*` direktiflerini allowlist'e al veya generic dosya-referansı taraması.
- **O2 — OBJ converter'da mesh karmaşıklık guard'ı yok.** `converters/obj_converter.py:292,338`
  (`trimesh.load` limitsiz); STL (`stl_converter.py:154-162`) ve STEP
  (`step_converter.py:162-185`) `MAX_MESH_FACES` uyguluyor. Crafted büyük OBJ →
  bellek/latency. Düzeltme: aynı guard'ı obj2gltf çıktısından sonra uygula.
- **O3 — Webhook SSRF redirect bypass.** `services/webhooks.py:135` (`requests.post`,
  `allow_redirects` default True). Guard yalnızca orijinal hostname'i pinliyor;
  302 `Location: http://169.254.169.254/...` takip edilerek internal/metadata'ya
  ulaşılıyor (blind SSRF). Düzeltme: `allow_redirects=False` (veya her hop'ta
  `_resolve_safe_ips`).
- **O4 — Login `next` açık yönlendirme (backslash).** `auth.py:87-88`.
  `urlparse('/\\evil.com').netloc == ''` → güvenli sanılıyor; `?next=/\evil.com`
  → tarayıcı `\`→`/` normalize edip `//evil.com`'a gidiyor (phishing). Düzeltme:
  `startswith('/')` ve `not startswith(('//','/\\'))`, ya da
  `url_has_allowed_host_and_scheme`. (Tarayıcıya bağlı — bkz. D3.)
- **O5 — Ham exception string'i client'a sızıyor (yaygın).** `hotspots.py`,
  `versions.py:49,107,136,158,195`, `model_editing.py:126,240,480,525,737`,
  `models_crud.py:383,476,540,580,612,659,693,737`, `scenes.py:61-63,82`
  (`jsonify({"error": str(e)}), 500`). Absolute path/trimesh/SQLAlchemy iç bilgisi
  sızıyor. Düzeltme: `str(e)`'yi logla, generic mesaj dön.
- **O6 — `generate_3d` DB row lock'unu Meshy HTTP boyunca tutuyor.**
  `blueprints/ai_generation.py:70`→`:143`. User row `FOR UPDATE` kilitli kalıp
  Meshy round-trip'i bekliyor → connection pool tükenmesi. Düzeltme: allowance'ı
  kısa kilitte düş+commit, external çağrıyı kilit dışına al.
- **O7 — `/discover` tüm public katalogu belleğe çekip Python'da paginate ediyor.**
  `blueprints/discover.py:26,33` (`query...all()` sonra slice). Unauthenticated,
  N ile lineer bellek/latency DoS. Düzeltme: SQL `LIMIT/OFFSET` + `+1` ile `has_more`.
  (Backend ve DB ajanları ortak buldu.)
- **O8 — Engagement sayaçları throttle'sız/anonim.** `blueprints/engagement.py:82-93`
  (`track_share`), `:96-107` (`track_download`, CSRF-exempt). Anonim caller
  `share_count`/`download_count` şişirebilir + sınırsız `ModelAnalyticsEvent` satırı
  → analytics bozulması + DB büyüme DoS. Düzeltme: per-IP rate limit + dedup.
- **O9 — `UserModel.user_id` ve `folder_id` index eksik (en sık filtre).**
  `models.py:249,250`. `/my_models`, admin user-detail/delete, storage aggregation
  full-scan. Düzeltme: `index=True` + migration (`ix_user_model_user_id`,
  `ix_user_model_folder_id`).
- **O10 — LemonSqueezy renewal iki ayrı commit → kalıcı strand.** `blueprints/billing.py:314-327`.
  Pending renewal commit'lenip (`:325-326`) sonra `_apply_successful_payment` ayrı
  commit (`:362`); arada crash olursa redelivery guard (`:310`) pending satırı görüp
  branch'i atlıyor → plan hiç uzatılmıyor, self-heal yok. Düzeltme: create+apply
  tek transaction, veya redelivery'de pending renewal'ı yeniden uygula.
- **O11 — Health check storage'ı yansıtmıyor + worker ölümü web probe'unu 503 yapıyor.**
  `blueprints/health.py:17-39`. DB `SELECT 1` (iyi) ve `JOB_QUEUE=true`'da worker
  heartbeat kontrol ediliyor ama disk/writability hiç kontrol edilmiyor (dolu volume
  → 200). Ayrıca worker liveness `/healthz`'e bağlı → ölü worker web instance'ını
  LB'den düşürebilir. Düzeltme: storage writability probe ekle; worker liveness'i
  ayrı path'e (`/healthz/worker`) taşı.
- **O12 — Comment/camera-view submit'inde debounce yok → çift kayıt.**
  `static/js/viewer/annotations.js:264-279` (comment), `:18-43` (Save Camera View).
  Çift-tık iki POST → iki kayıt (input/`savedViews` yanıt dönene dek güncellenmiyor).
  Düzeltme: handler başında butonu disable et, `.then/.catch`'te geri aç.

### 🔵 Düşük
- **D-L1 — View-tier dosya route'u backup/intermediate GLB'leri veriyor.**
  `blueprints/model_files.py:35-75`. `model_backup_<ts>.glb`, `modified_<ts>.glb`,
  `temp_*.glb` (ts = `int(time.time())`, tahmin edilebilir) view-only share ile
  indirilebiliyor → pre-edit/sliced geometri sızıntısı. Düzeltme: served filename
  allowlist'i.
- **D-L2 — `create_hotspot`/`create_camera_view` numeric coercion yok.**
  `blueprints/hotspots.py:58-83,296-306`. `create_measurement` (`:347-356`) `float()`
  sarıyor; bunlar ham JSON'u float kolonlara yazıyor → Postgres'te yanlış tip commit'te
  500 (O5 leak'iyle), NaN/Inf kabul. Düzeltme: `float()` ile coerce/validate.
- **D-L3 — Color/material mutasyonları stale `model.filename` path'ine yazıyor.**
  `blueprints/models_crud.py:210-218`, `blueprints/material_presets.py:125-134`.
  Kod geri kalanı `model.glb_path` kullanıyor (volume remount'ta `filename` stale
  oluyor — `model_editing.py:500-511`). Düzeltme: `model.glb_path` kullan.
- **D-L4 — Mutation policy anonim+token-hash'siz modelde ALLOW'a düşüyor.**
  `services/model_access.py:42-47`. `user_id is None` ve `edit_token_hash` falsy ise
  `AccessDecision(True)`. Şu an erişilemiyor (her anonim upload token hash set ediyor)
  ama latent full auth-bypass. Düzeltme: ne ownership ne token-hash yoksa default-deny.
- **D-L5 — İlk upload GLB'si atomik değil.** `app.py:2000` (`shutil.copy2`), `:2009`.
  Disk dolarsa truncated `model.glb` kalır; ama `UserModel` satırı yalnızca başarıda
  eklendiği için orphan (serve edilmez) — disk leak, served-corruption değil. Düzeltme
  (ops.): `.tmp` + `os.replace`; büyük yazımlardan önce free-space preflight.
- **D-L6 — Read-only demo viewer editing JS içeriyor (1 test kırık, template drift).**
  `tests/test_home_viewer_demo.py:27`. `/demo/viewer` `ar-slicer-layers.js` içeriyor
  (test yokluğunu assert ediyor). Güvenlik açığı değil (mutasyonlar server-guarded)
  ama "read-only" niyetiyle çelişik. Düzeltme: demo template'inden slicer `<script>`'i
  çıkar veya testi güncelle.
- **D-L7 — Save sonrası camera PATCH sessizce düşebilir.** `static/js/viewer/save-flow.js:132-141`.
  `viewer-settings` PATCH `try/catch` ile yutulup koşulsuz `reload()`; başarısız
  olursa hazırlanan kamera görünümü kaybolur, uyarı yok. Düzeltme: PATCH başarısızsa
  non-blocking uyarı ver.
- **D-L8 — Tutarsız escape (bugün exploit değil).** `versions.js:143`
  (`v.file_size_formatted` escape'siz), `ar-slicer-layers.js:806` (`origColorHex`
  attribute'a escape'siz). Server-üretimli → şu an güvenli; tutarlılık için `escapeHtml`.
- **D-L9 — Diğer.** STL guard'dan önce belleğe yükleniyor (`stl_converter.py:118`);
  `Plan.price` Integer, cent ifade edemez (`models.py:771`); ikincil unindexed FK'ler
  (`CameraView.model_id:578`, `HotspotComment.user_id:475`, `ConversionJob.user_id:882`);
  `/my_models` folder döngüsü N+1 (`models_crud.py:57-62`); login'de session rotate
  edilmiyor (signed-cookie olduğu için pratikte mitigasyonlu, `auth.py:79-89`).

### ❓ Doğrulanmadı (spekülatif — `muhtemelen`)
- **D1 — K1 erişilebilirliği:** FBX2glTF'in ham traversal `uri`'yi verbatim external
  `image.uri` olarak emit ettiği çalıştırılarak doğrulanmadı. Kod düzeyinde açık kesin;
  **muhtemelen erişilebilir**.
- **D2 — obj2gltf'in çözdüğü tam MTL key seti** (O1): paket ağaçta vendored değildi,
  hangi `map_*` key'lerinin dosya açtığı **muhtemelen** map listesi kadar.
- **D3 — O4 tarayıcı bağımlı:** `\`→`/` normalizasyonu Chrome/Edge'de var; guard bypass
  kod düzeyinde kesin, exploit **muhtemelen** tarayıcıya bağlı.

---

## Test Durumu (Tur 1)

- **646 passed · 3 failed · 2 skipped** (~368s). **3 kırığın hepsi GERÇEK, ortam değil.**
  - `test_p0_hardening.py::test_download_version_blocks_other_users` → **Y4**
  - `test_p0_hardening.py::test_download_version_requires_login_for_owned_model` → **Y4**
  - `test_home_viewer_demo.py::test_demo_viewer_is_static_read_only_and_not_indexable` → **D-L6**
- `test_step_converter.py` (cascadio ile) ve `test_thumbnail_render.py` **PASS** — bu
  oturumda ortam sorunu görünmüyor. Native deps (numpy/trimesh/...) mevcut.
- Stderr'deki `no such table: conversion_job` → per-test SQLite teardown'ı yarışan
  daemon thread'lerden gelen **warning**, test failure değil (kozmetik gürültü).

## Kapsam (services/blueprints/converters — toplam %66)

- **Riskli-düşük kapsam:** `services/payments/paytr.py` **%57** (callback/verify gövdesi
  test edilmemiş — en yüksek riskli boşluk), `auth.py` **%59** (register+referral,
  change-password happy path'leri test edilmemiş), `fbx_converter.py` **%8**,
  `obj_converter.py` **%11**, `model_files.py` **%27**.
- **İyi kapsam:** `model_access.py` %91, `model_permissions.py` %96,
  `conversion_jobs.py` %100, `storage.py` %89, `webhooks.py` %85.
- Playwright e2e (`tests/e2e/`) bu turda **çalıştırılmadı** (browser).

## Operasyonel cevaplar (Tur 1)

- Worker crash → web etkilenmiyor (ayrı process); restart'ta `requeue_stale_jobs()`
  (`worker.py:180`) poison-pill korumasıyla düzgün devam ediyor. Postgres job-claim
  `FOR UPDATE SKIP LOCKED` (`worker.py:88`) — iki worker aynı job'ı alamaz.
- Disk full → mevcut dosyalar atomic write'la korunuyor; ilk-upload GLB'si hariç
  (D-L5). Fiziksel free-space preflight yok (yalnızca logical quota).
- Log leak → `observability.py` temiz (body/header/secret loglamıyor); artık risk
  yalnızca caller-side, aktif sızıntı bulunmadı.

---

## İlerleme Takibi

| Bölüm | Durum | Not |
|-------|-------|-----|
| 0. Ortam ön-kontrolü | ✅ | Tur 1: tek head, native OK, 651 test toplandı |
| 1. Backend/route | ✅ | Tur 1: Y1, O5/O6/O7/O8, D-L1..4 |
| 2. Converter pipeline | ✅ | Tur 1: K1, O1/O2, D-L9 |
| 3. Güvenlik | ✅ | Tur 1: Y2, O3/O4; ödeme/CSRF/path-traversal sağlam |
| 4. Veritabanı | ✅ | Tur 1: Y3, O9/O10; migration zinciri temiz |
| 5. Frontend/JS | ✅ | Tur 1: O12, D-L6/L7/L8; frontend iyi sertleşmiş |
| 6. Operasyonel | ✅ | Tur 1: O11, D-L5; worker/log sağlam |
| 7. Test kapsamı | ✅ | Tur 1: 646/3/2, 3 kırık gerçek; kapsam %66 |

_Legend: ⬜ başlanmadı · 🔄 devam · ✅ bitti_
