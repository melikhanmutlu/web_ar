# ARVision — Hızlandırılmış Büyüme Planı (Teknik + Ticari)

*Tarih: 21 Temmuz 2026 · Hazırlayan: Senior Full-Stack + Growth/Sales perspektifiyle bütünleşik plan*
*Tamamlayıcı dokümanlar: `docs/business-plan.md` (birim ekonomi), `COMPETITOR-REPORT.md` (rekabet), `MARKETING-AUDIT.md` (pazarlama denetimi)*

---

## 0. Yönetici Özeti

**Durum:** ARVision teknik olarak satışa hazır bir üründür. Haziran denetiminde eksik
görünen temellerin çoğu bu arada kapatıldı: SEO/OG altyapısı, şeffaf fiyatlandırma
sayfası, herkese açık galeri (`/discover`), PayTR ödeme entegrasyonu, DB-tabanlı ve
admin'den yönetilebilir planlar, self-serve API/developer paneli, organizasyon
analitiği ve white-label. Ürün artık "pazarlama yüzeyi eksik" fazından çıkıp
**"dağıtım ve gelir motoru eksik"** fazına geçti.

**Tek cümlelik strateji:** B2C tarafında self-serve PLG (product-led growth)
döngüsünü otomatikleştirerek düşük maliyetli hacim üret; bu hacimden çıkan sinyallerle
(org kullanımı, embed hacmi, API kullanımı) B2B hesaplarını tespit edip **satış-destekli
Business/Enterprise anlaşmalarına** çevir. Aynı ürün, iki motor.

**En kritik 5 boşluk (gelir kaybettiren sırayla):**

1. **Yinelenen abonelik yok.** Mevcut PayTR akışı tek dönemlik ödeme + `plan_expires_at`
   ile çalışıyor; süre dolunca kullanıcı sessizce Free'ye düşüyor. Bu, SaaS'ın en pahalı
   hatası: pasif churn. → Yenileme hatırlatma otomasyonu (hemen) + kayıtlı kart/recurring
   (PayTR tekrarlayan ödeme veya global sağlayıcı) (30 gün içinde).
2. **Global ödeme yok.** PayTR TRY-odaklı; rakip fiyat noktaları USD. Lemon Squeezy /
   Paddle (Merchant of Record) adaptörü `services/payments/base.py` soyutlamasına
   eklenerek global satış açılmalı. Vergi/KDV yükünü MoR taşır.
3. **B2B satış yüzeyi yok.** "Talk to sales / demo iste" akışı, segment landing sayfaları
   (/for-ecommerce, /for-architecture), güvenlik/veri sayfası ve vaka çalışmaları yok.
   B2B alıcısı bunlar olmadan Business planına kendi kendine gelmez.
4. **Yaşam döngüsü otomasyonu yok.** E-posta altyapısı (SMTP) var ama onboarding /
   aktivasyon / kota-doldu / kredi-bitti / yenileme / kazanma (win-back) dizileri yok.
   Dönüşüm tetikleyicileri ürün içinde üretiliyor ama hiçbiri gelire bağlanmıyor.
5. **Metrik görünürlüğü yok.** Model-bazlı analitik var; **iş metrikleri** (kayıt→aktivasyon→
   ücretli dönüşüm hunisi, MRR, churn, kredi kullanım oranı) tek bir yerde izlenmiyor.
   Ölçmeden tempolu büyüme yönetilemez.

**90 günlük hedefler (öneri):** Yenileme oranı >%70 · kayıt→ücretli dönüşüm %3+ ·
20+ ücretli abone (başabaş ~5 Pro, bkz. business-plan) · 2 B2B pilot (Business planında
logo + vaka çalışması) · organik trafikte ayda %30 bileşik artış.

**Yatırım gerektirmeyen kaldıraç:** Ürünün ürettiği her AR linki ve her embed bir
edinim kanalıdır. Bu döngü artık teknik olarak çalışıyor (OG önizleme + galeri +
embed); planın büyük kısmı bu döngüyü **otomasyonla beslemek** ve **ölçmek** üzerine
kuruludur.

---

## 1. Mevcut Durum Özeti (Temmuz 2026)

### Gemide olanlar (satış argümanı olarak kullanılabilir)
- Uçtan uca dönüşüm: STL/FBX/OBJ/STEP → GLB/USDZ, iOS Quick Look + Android Scene Viewer, QR, embed.
- AI text/image → 3D (Meshy) + kredi sistemi (`services/credits.py`, ledger'lı).
- Fiyatlandırma: Free/Pro(19)/Business(99), DB-tabanlı, admin CRUD'lu (`services/plans.py`).
- Ödeme: PayTR (tek dönemlik), `Payment` kaydı, hash-doğrulamalı callback (`blueprints/billing.py`).
- B2B temelleri: Organizasyonlar + roller, org analitiği + CSV export, white-label tema,
  custom domain, webhooks, API token'ları + `/api/v1` + OpenAPI + developers paneli.
- Büyüme yüzeyi: OG/Twitter kartları (`_seo_head.html`), robots/sitemap (`blueprints/seo.py`),
  `/discover` galerisi, pricing sayfası.
- Operasyon: worker kuyruğu, Alembic migration'ları, CI (pytest + pip-audit + bandit + Playwright),
  JSON loglama (`services/observability.py`), `/metrics`.

### Eksikler (bu planın konusu)
- Recurring billing + dunning, global ödeme (MoR), fatura/e-arşiv entegrasyonu.
- Yaşam döngüsü e-postaları, ürün-içi upgrade tetikleyicileri (paywall anları).
- B2B: segment sayfaları, demo/satış akışı, güvenlik-güven sayfası, vaka çalışmaları,
  Shopify/WooCommerce entegrasyonu, koltuk-bazlı org faturalama.
- İş metrikleri panosu (aktivasyon hunisi, MRR, churn, kredi kullanımı, CAC).
- Referans/davet programı, içerik-SEO üretim hattı.

---

## 2. Konumlandırma ve Hedef Segmentler

**Kategori (COMPETITOR-REPORT ile uyumlu):** *"Herhangi bir 3D dosyasını — ya da bir
AI promptunu — saniyeler içinde telefonda çalışan, paylaşılabilir bir AR linkine
çeviren en hızlı yol."* Tüm mesajlaşma tek bu cümleden türetilir; converter/AI/host
kimlikleri "nasıl"dır, "ne" değildir.

### B2C (self-serve, hacim motoru)
| Segment | Acı | Kanca | Plan |
|---|---|---|---|
| Maker / 3D-print hobisti | STL'i telefonda gösterememek | "STL'ini at, AR linkini WhatsApp'tan yolla" | Free→Pro |
| Freelance 3D sanatçı / portfolyo | Müşteriye iş teslimi/onayı | Versiyonlu, parola korumalı paylaşım | Pro |
| Etsy / küçük e-ticaret satıcısı | Ürünü "evinde gör" deneyimi | Embed + QR, kod yok | Pro |
| AI-meraklısı üretici | Meshy çıktısını paylaşamamak | "Üret → anında AR linki" | Free→Pro (kredi top-up) |

### B2B (satış-destekli, gelir motoru)
| Segment | Acı | Kanca | Plan |
|---|---|---|---|
| Mobilya / dekorasyon e-ticareti | İade oranı, "yerinde nasıl durur" | Ürün sayfasına AR embed (Shopify) | Business |
| Mimarlık / iç mimarlık ofisi | Müşteri sunumu, revizyon turları | Org + versiyon + hotspot + white-label | Business |
| Ajanslar (3D içerik üreten) | Müşteri başına teslim altyapısı | Custom domain + white-label + API | Business/Enterprise |
| Eğitim kurumları | Etkileşimli materyal | Toplu yükleme + org + embed | Business (eğitim indirimi) |

**B2C→B2B köprüsü (planın kalbi):** Free/Pro kullanıcı davranışından B2B sinyali çıkar:
aynı domain'den 3+ kayıt, org oluşturma, embed'in bir e-ticaret sitesinde görünmesi,
API kullanımı, yüksek AR görüntülenme. Bu sinyaller otomatik olarak bir "sales-ready
lead" listesine düşmeli (Bölüm 5'teki otomasyon #6).

---

## 3. Ticari Plan

### 3.1 Fiyatlandırma aksiyonları
1. **Yıllık plan ekle** (2 ay bedava = ~%17 indirim). `billing_period="yearly"` altyapısı
   zaten var; pricing sayfasına aylık/yıllık anahtarı eklenecek. Yıllık peşin tahsilat,
   erken evrede nakit akışının en ucuz finansmanıdır.
2. **Kredi top-up paketlerini satışa aç** (business-plan §3'teki 10/50/200'lük paketler).
   Ledger hazır; sadece checkout'a "credit_topup" ürün tipi eklenecek. AI kullanan
   kullanıcıda ARPU'yu abonelik dışına genişletir.
3. **USD fiyat listesi** MoR sağlayıcısı devreye girince: Pro $12–15, Business $79–99
   (rakip bandı: Sketchfab ≈$15–60, Vectary ≈$12–40 — canlı doğrula). TRY fiyatları
   yerel pazar için korunur (bölgesel fiyatlandırma avantajı).
4. **Enterprise "bizimle konuş" katmanı** pricing'e eklenir: SSO, SLA, özel limitler,
   fatura ile ödeme. Fiyatı sabitleme; teklif bazlı başla (ilk 3-5 anlaşmada fiyat keşfi).
5. **Free planı aktivasyona göre ayarla:** e-posta doğrulaması olmadan AI kredisi yok
   (kötüye kullanım + liste kalitesi), buna karşılık "ilk modelini yükle → +2 kredi"
   gibi aktivasyon ödülleri.

### 3.2 Satış kanalları ve GTM

**B2C (PLG, tamamı otomatik):**
- Viral döngü: paylaşılan link → OG önizleme → görüntüleyen kayıt olur → kendi linkini
  paylaşır. Embed'de "Powered by ARVision" atfı (Free/Pro'da; Business'ta kaldırılabilir —
  white-label zaten bunun için var). Bu atıf tıklanabilir + UTM'li olmalı.
- SEO içerik hattı: format-acısı sayfaları ("FBX to GLB", "STL'i AR'da görüntüle",
  "USDZ nedir") + `/vs/sketchfab`, `/vs/meshy` karşılaştırma sayfaları + `/discover`
  galerisinin indekslenen model sayfaları. Hedef: ayda 4-8 sayfa, şablonlaştırılmış üretim.
- Topluluk: r/3Dprinting, r/Blender, Printables/Thingiverse toplulukları, X/LinkedIn'de
  "önce/sonra AR" videoları. Haftada 2-3 organik gönderi; ürün içi "paylaş" anına
  hazır-metin/video ekle.
- Launch anları: Product Hunt lansmanı (tek seferlik, hazır olunca), Hacker News "Show HN"
  (developers paneli + API hikâyesiyle).

**B2B (sales-assist, insan + otomasyon karışımı):**
- **Inbound:** Segment landing sayfaları + "demo iste" formu → takvim (Cal.com) →
  CRM'e düşer. Business planı denemesi: 14 gün, kredi kartı istemeden, satış onaylı.
- **Outbound (hedefli, spam değil):** Haftada 20-30 hesaplık liste — AR kullanmayan ama
  3D varlığı olan mobilya/dekor e-ticaret siteleri, mimarlık ofisleri. Kanca kişisel:
  "Sitenizdeki X ürününü AR'a çevirdim, linki: …" (ürünün kendisi demo üretir — bu,
  ARVision'ın haksız avantajı: outbound e-postanın eki bizzat çalışan AR linki).
- **Entegrasyon kanalı:** Shopify App Store'a basit bir "AR viewer" uygulaması (embed +
  ürün eşleme). App Store'un kendisi bir edinim kanalıdır; e-ticaret ICP'sine en kısa yol.
- **Ortaklıklar:** 3D tarama servisleri, ürün fotoğrafçıları, e-ticaret ajansları —
  %20-25 tekrarlayan komisyonlu referans programı.

### 3.3 Satış süreci (B2B, hafif tutulmuş)
1. Sinyal/başvuru → 2. 25 dk demo (müşterinin kendi ürünüyle canlı dönüşüm) →
3. 14 gün pilot (başarı kriteri baştan yazılır: "ürün sayfasında AR, X görüntülenme") →
4. Business abonelik veya yıllık teklif → 5. 30. günde vaka çalışması izni iste.
İlk 10 anlaşmada kurucu-satışı; script ve itiraz bankası bu görüşmelerden yazılır.

---

## 4. Teknik Yol Haritası (satışı hızlandıran işler, öncelik sıralı)

Her madde mevcut mimariye (blueprint + services) oturur; hiçbiri büyük refactor değildir.

### Faz 1 — Gelir kaçağını durdur (Hafta 1-3)
| İş | Kapsam | Neden |
|---|---|---|
| Yenileme hatırlatma + dunning e-postaları | Worker sweep'ine T-7/T-1/T+3 e-postaları (`expire_stale_plans` yanına); `send_email` mevcut | Pasif churn'ü durdurur — en yüksek ROI'li iş |
| Lemon Squeezy / Paddle sağlayıcısı | `services/payments/` altına ikinci provider (base.py soyutlaması hazır); webhook → plan grant | Global satış + gerçek recurring + vergi yükü MoR'da |
| Kredi top-up checkout'u | `Payment`'a `kind=topup`; başarılı callback → `credits.grant` | Hazır talebi paraya çevirir |
| İş metrikleri panosu (admin) | `/admin/growth`: kayıt→doğrulama→ilk model→ilk paylaşım→ücretli hunisi, MRR, aktif abone, kredi kullanım %, yenileme % | Ölçüm olmadan tempo yönetilemez |
| Upgrade tetikleyicileri | Kota/limit'e çarpan her yerde (upload, AI, depolama, batch) bağlama duyarlı "Pro'ya geç" modali + `?upgrade_reason=` UTM'i | Paywall anları = dönüşümün %80'i |

### Faz 2 — B2B satış yüzeyi (Hafta 3-6)
| İş | Kapsam |
|---|---|
| Segment landing sayfaları | `/for/ecommerce`, `/for/architecture`, `/for/agencies` — aynı Jinja şablonu, segment verisiyle; sitemap'e ekle |
| Demo/satış akışı | "Talk to sales" formu → e-posta + admin bildirimi; Cal.com linki |
| Güven sayfası | `/security`: veri saklama, gizlilik, altyapı, yedekleme; B2B'nin ön koşulu |
| Business trial | Admin'den süreli plan atama zaten var (`plan_expires_at`); self-serve "14 gün dene" butonuna bağla |
| Koltuk-bazlı org faturalama (v1) | Business planına "N koltuk dahil, koltuk başı $X" — org üye sayısı zaten modelde |
| Shopify uygulaması (MVP) | Embed snippet + ürün eşleme; App Store girişi ayrı sprint |

### Faz 3 — PLG derinleştirme (Hafta 6-12)
| İş | Kapsam |
|---|---|
| Referans programı | Davet linki → her iki tarafa AI kredisi; ledger hazır olduğundan ucuz iş |
| Karşılaştırma + format SEO sayfaları | `/vs/*` ve `/convert/*` şablon sayfaları (statik içerik + canlı demo bileşeni) |
| Onboarding checklist'i (ürün içi) | "Model yükle → AR'da aç → linki paylaş → AI dene" 4 adımlı ilerleme çubuğu; aktivasyonu tanımlar |
| Public API hikâyesi | Developers paneli mevcut; rate-limit'li ücretsiz tier + docs'a örnek reçeteler ("CI'da otomatik AR linki") |
| E-arşiv/fatura entegrasyonu (TR) | Paraşüt/BizimHesap API — TR kurumsal satış için fatura şart |

**Teknik borç bekçileri (büyürken batmamak için):** R2/S3 depolama göçü 50GB eşiğinde
(business-plan §4C), Redis rate-limit çoklu instance'ta, `/metrics`'e iş metrikleri
(kayıt, dönüşüm, ödeme) sayaçlarının eklenmesi, Sentry (veya eşleniği) hata izleme.

---

## 5. Otomatikleştirilecek Sistemler

Amaç: kurucu zamanının satış görüşmeleri + ürün dışında hiçbir rutine gitmemesi.

1. **Yaşam döngüsü e-postaları (worker-tabanlı, mevcut SMTP ile):**
   - Kayıt → hoş geldin + ilk model rehberi (gün 0)
   - Model yükledi ama paylaşmadı → "linkini gönder" (gün 1)
   - Hiç model yüklemedi → örnek galeri + 1 tık şablon (gün 2)
   - AI kredisi bitti → top-up teklifi (anlık)
   - Depolama/kota %80 → upgrade (anlık)
   - Yenileme T-7/T-1/T+3 → dunning dizisi
   - 30 gün inaktif ücretli → win-back
   Uygulama: `worker.py`'ye günlük "lifecycle sweep" + `EmailLog` tablosu (aynı e-posta
   iki kez gitmesin). Üçüncü parti araç gerekmez; ölçek büyüyünce Loops/Customer.io'ya taşınır.

2. **Dunning + abonelik durumu:** MoR webhook'ları (ödeme başarısız → yeniden dene
   bildirimi → 7 gün ödemesiz → downgrade) tamamen otomatik; admin sadece istisna görür.

3. **Haftalık iş raporu (otomatik e-posta, pazartesi 08:00):** kayıt, aktivasyon %,
   yeni MRR, churn, kredi kullanımı, en çok görüntülenen 5 model, en aktif 5 org.
   Worker'da tek fonksiyon; kurucunun haftalık karar toplantısının gündemi budur.

4. **B2B sinyal madenciliği (sales-ready lead listesi):** Günlük sweep — aynı şirket
   domain'inden ≥3 kullanıcı, org kurulumu, embed referer'ında ticari domain, API
   kullanımı, tek modelde ≥100 AR görüntülenme → admin'e "bugün aranacaklar" e-postası.
   CRM'e (başta basit bir tablo/Notion, sonra HubSpot Free) otomatik satır.

5. **İçerik/SEO hattı:** Ayda bir `sitemap` fark raporu + Search Console API'den
   pozisyon/klik çekimi → hangi format sayfası yazılacak listesi. İçerik taslakları
   AI-destekli üretilir, insan onayıyla yayınlanır (kalite kontrolsüz AI içeriği yayınlama).

6. **Rakip izleme:** COMPETITOR-REPORT §"İzleme Planı"nın otomasyonu — aylık cron:
   rakip pricing sayfalarını çek, diff varsa e-posta; Meshy/Tripo changelog RSS takibi
   ("AR paylaşım özelliği eklediler mi" tehdidi). Google Alerts kurulumları (manuel, 1 kez).

7. **Operasyon nöbetçileri:** Conversion job hata oranı > eşik → uyarı; depolama
   büyüme trendi → R2 göç hatırlatması; `pip-audit`/`bandit` zaten CI'da — haftalık
   zamanlanmış CI çalıştırması eklenir (bağımlılık CVE'leri PR beklemeden yakalansın).

8. **Sosyal kanıt toplama:** Ödeme sonrası 30. günde otomatik "deneyimini paylaş"
   e-postası (yorum/tweet isteği); NPS mini anketi (1 soru) 14. günde ürün içinde.

---

## 6. Düzenli Araştırma Ritmi

| Sıklık | Araştırma | Kaynak/Araç | Çıktı |
|---|---|---|---|
| Haftalık (30 dk) | Huni metrikleri + kayıt kaynakları incelemesi | `/admin/growth` + haftalık otomatik rapor | 1 deney kararı |
| Haftalık (30 dk) | Kullanıcı geri bildirimi taraması | Destek e-postaları, iptal nedenleri, NPS yorumları | Yol haritası girdisi |
| 2 haftada bir | 3-5 kullanıcı görüşmesi (özellikle: yeni ücretli + yeni churn eden) | 15 dk görüşme; iptal akışına "neden?" zorunlu tek soru | ICP/mesaj güncellemesi |
| Aylık | Rakip fiyat/özellik diff'i | Otomatik scraper raporu + manuel doğrulama | Fiyat/konum kararı |
| Aylık | SEO/anahtar kelime performansı | Search Console + hedef sorgu listesi | Sonraki 4-8 içerik konusu |
| Aylık | Birim ekonomi güncellemesi | Meshy faturası / Railway kullanımı vs. business-plan varsayımları | Marj sapması varsa fiyat/limit aksiyonu |
| Çeyreklik | Pazar taraması: yeni AI-3D sağlayıcıları (Tripo, Hyper3D, …), WebXR/Quick Look platform değişiklikleri | Sağlayıcı docs, WWDC/Google I/O notları | Tedarikçi çeşitlendirme + özellik fırsatı |
| Çeyreklik | G2/Capterra/Trustpilot kategori taraması + kendi listelenme durumun | Canlı tarama | Review-toplama kampanyası |
| Çeyreklik | Fiyatlandırma araştırması (kullanım verisiyle) | Kredi kullanım dağılımı, plan geçiş matrisi | Plan/limit revizyonu |

Kural: her araştırma çıktısı ya bir **deneye** ya bir **yol haritası maddesine**
bağlanır; bağlanmıyorsa o araştırma takvimden çıkarılır.

---

## 7. KPI'lar ve Hedefler

**Kuzey Yıldızı:** Haftalık paylaşılan-ve-görüntülenen AR linki sayısı (ürün değeri
gerçekleşme anı; business-plan §9 ile uyumlu).

| Metrik | Şimdi | 30 gün | 90 gün |
|---|---|---|---|
| Kayıt → aktivasyon (ilk paylaşım) | ölçülmüyor | ölçülüyor + taban | %40 |
| Kayıt → ücretli | ölçülmüyor | %1-2 | %3-5 |
| Ücretli abone | ~0 | 8-10 | 20+ (2'si Business) |
| Yenileme oranı | takipsiz (pasif churn) | >%50 | >%70 |
| MRR | ~0 | $150-250 | $600-1.000 |
| Organik oturum/ay | düşük | +%30 | 3x taban |
| B2B pilot | 0 | 1 | 2 (vaka çalışmalı) |
| Kredi kullanım oranı | — | %40-60 bandında izleniyor | bandın içinde (marj koruması) |

---

## 8. 90 Günlük Sprint Takvimi (özet)

- **Hafta 1-2:** Dunning/yenileme e-postaları · growth panosu · upgrade tetikleyicileri ·
  ilk 10 outbound "ürününüzü AR'a çevirdim" e-postası (manuel, öğrenme amaçlı).
- **Hafta 3-4:** MoR sağlayıcı entegrasyonu (USD + recurring) · yıllık planlar · kredi
  top-up satışı · `/security` + demo formu.
- **Hafta 5-6:** Segment landing sayfaları · lifecycle e-posta dizileri (hoş geldin/
  aktivasyon) · B2B sinyal sweep'i · ilk 2 `/vs` sayfası.
- **Hafta 7-9:** Shopify MVP · referans programı · onboarding checklist'i · Product Hunt
  hazırlığı · ilk B2B pilotun kapanışı.
- **Hafta 10-12:** Product Hunt lansmanı · vaka çalışması yayını · format-SEO sayfa
  serisi · koltuk-bazlı Business faturalama · çeyreklik fiyat revizyonu (veriyle).

Ritim: haftalık tek öncelik ("bu hafta gemiye ne biniyor?"), pazartesi otomatik rapor +
30 dk karar, cuma gemiye binenin duyurusu (changelog + sosyal gönderi — changelog'un
kendisi pazarlama içeriğidir).

---

## 9. Riskler ve Önlemler

| Risk | Önlem |
|---|---|
| Meshy'nin AR-paylaşım katmanı eklemesi (en büyük stratejik tehdit) | "Üret→AR→paylaş" mesajını derinleştir; dönüşüm+hosting+org+analytics paketinin AI'dan bağımsız değerini büyüt; Tripo/Hyper3D adaptörüyle tedarikçi bağımlılığını kır |
| Tek dönemlik ödemeyle pasif churn | Faz 1 dunning + MoR recurring (bu planın 1 numarası) |
| Kredi marjı varsayımının şaşması | Aylık birim-ekonomi kontrolü (Bölüm 6); devretme sınırı + günlük limitler mevcut |
| Tek geliştirici dar boğazı | Otomasyon-öncelikli plan; her manuel rutin 2. tekrarında otomatikleştirilir; CI/testler mevcut disiplinle korunur |
| Depolama/egress maliyeti | 50GB eşiğinde R2 göçü (hazırlığı Faz 3'te başlat) |
| B2B satış döngüsünün uzaması | Pilotlar süreli ve başarı-kriterli; self-serve Business her zaman açık kalır |

---

*Bu plan; `docs/business-plan.md`'nin birim ekonomisini, `COMPETITOR-REPORT.md`'nin
konumlandırmasını ve `MARKETING-AUDIT.md`'nin (büyük ölçüde kapatılmış) denetim
bulgularını tek bir uygulanabilir yol haritasında birleştirir. Revizyon ritmi: 30 günde
bir, gerçekleşen metriklerle.*
