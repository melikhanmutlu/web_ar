# ARVision Büyüme Planı — Uygulama Backlog'u

*Kaynak: `docs/growth-strategy.md` · Durum işaretleri: `[ ]` bekliyor · `[x]` tamam · `[~]` kısmi/dış bağımlılık bekliyor*

Her iş; kapsam, dokunulan dosyalar ve doğrulama kriteriyle tanımlıdır. Sıralama =
uygulama sırası. Dış hesap gerektiren işler (MoR API anahtarı, Shopify Partner,
Search Console) kod tarafı bitirilip `[~]` bırakılır; anahtar gelince açılır.

---

## FAZ 1 — Gelir kaçağını durdur (Hafta 1–3)

### 1.1 Yenileme hatırlatma + dunning e-postaları
- [x] **Kapsam:** Worker'a günlük "lifecycle sweep": T-7 ve T-1 yenileme hatırlatması
  (planı yaklaşan ücretli kullanıcı), T+3 win-back (süresi dolup Free'ye düşen ödemeli
  kullanıcı — `Payment.period_end` üzerinden). Aynı e-postanın bir dönem için yalnız
  bir kez gitmesini garanti eden `LifecycleEmail` tablosu (user_id, kind, dedupe_key
  unique). Yenileme yapılınca `plan_expires_at` değişir → dedupe anahtarı değişir →
  sonraki dönem otomatik yeniden kurulur.
- **Dosyalar:** `models.py` (+`LifecycleEmail`), `migrations/versions/…_add_lifecycle_email.py`,
  `services/lifecycle_emails.py` (yeni), `worker.py` (saatlik blokta çağrı),
  `tests/test_lifecycle_emails.py` (yeni).
- **Doğrulama:** pytest — pencere seçimi, tekilleştirme (iki sweep = tek e-posta),
  yenileme sonrası yeniden kurulma, SMTP başarısızsa kayıt atılmaz (retry edilebilir).

### 1.2 Kredi top-up checkout'u
- [x] **Kapsam:** `Payment`'a `kind` ('plan'|'topup') + `credits` kolonu; top-up paket
  tanımları (10/50/200 kredi — admin'den düzenlenebilir site ayarı); `/billing/topup/<paket>`
  checkout'u (mevcut provider soyutlaması üzerinden); başarılı callback'te
  `grant_ai_credits` (ledger'lı); `billing.html`'e paket kartları.
- **Dosyalar:** `models.py`, migration, `blueprints/billing.py`, `services/credits.py`
  (gerekirse), `templates/billing.html`, `tests/test_billing_topup.py`.
- **Doğrulama:** pytest — topup callback kredisi yüklüyor, idempotent replay, plan'a dokunmuyor.

### 1.3 MoR sağlayıcısı (Lemon Squeezy) — global ödeme + recurring
- [~] **Kapsam:** *(kod tamam + testli; canlı store/variant anahtarları dış bağımlılık)* `services/payments/lemonsqueezy.py` (hosted checkout URL üretimi +
  `X-Signature` HMAC doğrulamalı webhook); `subscription_payment_success` → plan uzatma,
  `order_created` (topup) → kredi; `/billing/ls/webhook` endpoint'i (CSRF-exempt,
  rate-limit'li, PayTR callback kalıbı); sağlayıcı seçimi env ile
  (`PAYMENT_PROVIDER=paytr|lemonsqueezy`).
- **Dosyalar:** `services/payments/lemonsqueezy.py`, `services/payments/__init__.py`,
  `blueprints/billing.py`, `config.py`, `.env.example`, `tests/test_billing_lemonsqueezy.py`.
- **Doğrulama:** pytest — sahte imzalı webhook kabul/ret, plan grant, idempotent replay.
  `[~]` canlı uçtan uca test store anahtarı gelince.

### 1.4 Growth panosu (`/admin/growth`)
- [x] **Kapsam:** Aktivasyon hunisi (kayıt → ilk model → ilk paylaşım → ücretli),
  aktif abone sayısı + plan kırılımı, MRR (aktif ücretli planların aylık fiyat toplamı),
  son 30 gün yenileme oranı (`Payment` üzerinden), kredi kullanım oranı, haftalık kayıt
  trendi. Salt-okunur SQL özetleri; grafik gerekmez, tablo/sayı yeter (v1).
- **Dosyalar:** `admin.py`, `templates/admin/growth.html`, `tests/test_admin_growth.py`.
- **Doğrulama:** pytest — sayılar bilinen fixture verisiyle doğru; admin-olmayan 403.

### 1.5 Upgrade tetikleyicileri (paywall anları)
- [x] **Kapsam:** Limit/kota reddi dönen uçlara standart `upgrade` alanı
  (`{"reason": "storage_quota", "plan": "pro"}`); frontend'de tek paylaşımlı modal
  ("Pro'ya geç" + `?upgrade_reason=` UTM'li pricing linki); kapsanan noktalar: upload
  kotası, model sayısı, AI kredi/limit, depolama, batch, plan-gated özellikler
  (org/webhook/custom domain istekleri).
- **Dosyalar:** ilgili blueprint'ler (`upload.py`, `ai_generation.py`, `models_crud.py`,
  `organizations.py`, `webhooks.py`), `static/js/` ortak modal, `templates/` include,
  `tests/test_upgrade_prompts.py`.
- **Doğrulama:** pytest — reddedilen isteklerde `upgrade` alanı; lint (`npm run lint`).

---

## FAZ 2 — B2B satış yüzeyi (Hafta 3–6)

### 2.1 Segment landing sayfaları
- [x] `/for/ecommerce`, `/for/architecture`, `/for/agencies` — tek Jinja şablonu +
  segment veri sözlüğü (başlık, acılar, özellik eşlemesi, CTA); `_seo_head` meta;
  sitemap'e ekleme (`blueprints/seo.py::SITEMAP_STATIC_ENDPOINTS`).
- **Doğrulama:** pytest — 200 + segment içeriği; sitemap'te URL'ler.

### 2.2 Demo / satış akışı ("Talk to sales")
- [x] `SalesLead` tablosu (isim, e-posta, şirket, mesaj, kaynak, durum); `/contact-sales`
  formu (CSRF + rate limit + honeypot); admin'e bildirim e-postası; `/admin`'de lead
  listesi + durum güncelleme. Cal.com linki site ayarı olarak (`SiteSetting`).
- **Doğrulama:** pytest — form kaydı, rate limit, admin listesi.

### 2.3 `/security` güven sayfası
- [x] Veri saklama/gizlilik/altyapı/yedekleme/şifreleme özeti; footer + pricing'den link;
  sitemap'e ekleme. İçerik mevcut mimariden türetilir (gerçek olmayan iddia yazılmaz).
- **Doğrulama:** sayfa 200, lint.

### 2.4 Business self-serve 14 gün trial
- [x] `User.business_trial_used_at` kolonu; `/billing/trial` POST → `plan=business`,
  `plan_expires_at=+14g` (tek sefer); pricing + billing'de "14 gün dene" butonu;
  1.1'deki T-7/T-1 hatırlatmaları trial bitişini de kapsar (aynı mekanizma).
- **Doğrulama:** pytest — tek kullanımlık, süre sonunda mevcut sweep'le Free'ye iner.

### 2.5 Koltuk-bazlı org sınırı (v1)
- [x] Plan limitlerine `max_org_members` (Business seed değeriyle); org üye davetinde
  enforcement (`services/org_membership.py`); admin plan editörüne alan
  (`LIMIT_KEYS`'e ekleme). Gerçek koltuk-başı faturalama MoR sonrası (Faz 3+).
- **Doğrulama:** pytest — limit üstü davet reddi + upgrade alanı (1.5 kalıbı).

### 2.6 Embed entegrasyon rehberi (Shopify MVP'nin ön adımı)
- [ ] `/developers`'a "Add AR to your store" rehberi: kopyala-yapıştır embed snippet
  üretici (model seç → hazır iframe/QR kodu), Shopify/Woo tema talimatları.
  `[~]` Shopify App Store uygulaması ayrı depo/Partner hesabı ister — dış bağımlılık.
- **Doğrulama:** sayfa 200, snippet doğru model URL'siyle üretiliyor.

---

## FAZ 3 — PLG derinleştirme (Hafta 6–12)

### 3.1 Hoş geldin / aktivasyon e-posta dizisi
- [x] 1.1 altyapısını genişlet: D0 hoş geldin, D1 "modelini paylaş" (yükledi ama
  paylaşmadı), D2 "ilk modelini yükle" (hiç yüklemedi). Aynı `LifecycleEmail`
  tekilleştirmesi; kullanıcı başına gün başına en fazla 1 lifecycle e-postası kuralı.
- **Doğrulama:** pytest — segment seçimi + tekilleştirme + günlük tavan.

### 3.2 Referans programı
- [x] `User.referral_code` (+ `referred_by_id`); kayıt akışında `?ref=` yakalama;
  davet eden + edilen tarafa AI kredisi (ledger `reason=referral`); kötüye kullanım
  tavanı (aylık N ödül); profil sayfasında davet linki + sayaç.
- **Doğrulama:** pytest — çift taraflı kredi, self-referral reddi, tavan.

### 3.3 `/vs/*` ve `/convert/*` SEO sayfaları
- [x] Şablonlaştırılmış karşılaştırma (`/vs/sketchfab`, `/vs/meshy`) ve format
  (`/convert/fbx-to-glb`, `/convert/obj-to-glb`, `/convert/stl-to-ar`) sayfaları;
  içerik veri dosyasından; sitemap + iç linkler. COMPETITOR-REPORT'taki dürüst
  karşılaştırma ilkesi (kaybedilen yerler de yazılır).
- **Doğrulama:** pytest — 200 + sitemap; lint.

### 3.4 Onboarding checklist'i (ürün içi)
- [x] Dashboard'da 4 adım: model yükle → AR'da aç → linki paylaş → AI dene. İlerleme
  mevcut verilerden türetilir (yeni tablo yok); tamamlanınca kaybolur.
- **Doğrulama:** Playwright smoke + pytest (adım hesaplama).

### 3.5 Haftalık otomatik iş raporu
- [x] Worker'da pazartesi sweep'i: kayıt, aktivasyon %, yeni MRR, churn, kredi
  kullanımı, top 5 model / org → admin e-postası. 1.4 panosuyla aynı sorgu katmanını
  paylaşır (`services/growth_metrics.py`).
- **Doğrulama:** pytest — rapor içeriği fixture veriyle; haftada bir tekilleştirme.

### 3.6 B2B sinyal madenciliği
- [x] Günlük sweep: aynı e-posta domain'inden ≥3 kullanıcı, org kurulumu, yüksek AR
  görüntülenme (≥100/model), API kullanımı → `SalesLead(source='signal')` + admin
  e-postası. Ücretsiz e-posta domain'leri (gmail vb.) hariç tutulur.
- **Doğrulama:** pytest — sinyal kuralları + tekilleştirme.

### 3.7 Rakip izleme otomasyonu
- [x] `scripts/competitor_watch.py`: rakip pricing URL listesini çek, normalize et,
  önceki snapshot ile diff → değişiklikte admin e-postası. Zamanlama: worker aylık
  sweep veya CI cron. `[~]` egress politikasına bağlı.
- **Doğrulama:** pytest — diff mantığı sahte HTML'le.

### 3.8 E-arşiv/fatura adaptör iskeleti (TR kurumsal)
- [x] `services/invoicing.py` arayüzü + Paraşüt adaptör iskeleti; ödeme sonrası
  fatura kaydı kuyruğu. `[~]` API anahtarı dış bağımlılık.

---

## Sürekli (her fazla birlikte)
- Her yeni endpoint: blueprint'e, `check_model_mutation_allowed`/`ModelAccessService`
  kalıplarıyla; CSRF; rate limit; testli.
- Her şema değişikliği: Alembic migration.
- Her UI değişikliği: `npm run lint` + gerekiyorsa Playwright smoke.
- Cuma: changelog güncellemesi (gemiye binenler) — pazarlama içeriği olarak da kullanılır.

---

## Bug-hunt turu (3 paralel inceleme + migration doğrulaması)

Faz 1-3 kodu adversaryal olarak tarandı; doğrulanan gerçek buglar düzeltildi ve
her biri için regresyon testi eklendi:

- **[HIGH]** Lemon Squeezy ilk-fatura webhook tekrarı tam bir abonelik dönemini
  çift-veriyordu (para sızıntısı) → per-fatura idempotency (`billing.py`).
- **[HIGH]** `signal_mining` `func.instr` kullanıyordu (SQLite-only); Postgres'te
  her sweep patlar ve worker maintenance bloğunu hot-loop'a sokardı → Python-tarafı
  domain gruplama + her sweep'i izole `try/except`'e alan worker (`signal_mining.py`, `worker.py`).
- **[MED]** Growth MRR/abone sayısı trial + comp hesapları ücretli sayıyordu →
  yalnız gerçek ödemesi olanlar (`growth_metrics.py`).
- **[MED]** Seat limiti Free/lapsed org sahibinde `None→sınırsız` fallthrough ile
  kayboluyordu → 0'a floor (`organizations.py`).
- **[MED]** Rakip izleme geçici fetch hatasında sahte fiyat-değişim alarmı üretiyordu
  → önceki snapshot'ı taşıma (`competitor_watch.py`).
- **[MED-LOW]** Win-back yanlış/eski dönemi seçip ikinci kez gönderebiliyordu →
  mutlak en-son dönem (`lifecycle_emails.py`).
- **[LOW]** `set_lead_status` `request.referrer`'a açık yönlendirme → sabit iç URL (`admin.py`).
- **[LOW]** Rakip izleme yalnız sıralama değişince boş alarm üretiyordu → yalnız
  gerçek add/remove (`competitor_watch.py`).
- **[LOW]** Haftalık rapor kısmi teslimde tüm haftayı "gönderildi" işaretliyordu →
  alıcı-bazlı takip (`weekly_report.py`).
- **[düzeltildi]** Referral migration'ı SQLite'ta `flask db upgrade`'i kırıyordu →
  batch mode (`c83a5e7f2b91`).

Temiz onaylananlar: referrals, onboarding e-postaları (saatlik sweep semantiği),
onboarding checklist, invoicing seam, migration zinciri.
