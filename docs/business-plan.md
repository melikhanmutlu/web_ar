# arvision — İş Planı (Üyelik + Kredi Modeli)

*Tarih: Haziran 2026 · Fiyat kaynakları: Meshy resmi dokümanları, Railway resmi fiyatlandırma*

---

## 1. Ürün Özeti

arvision: 3D model yükle (FBX/OBJ/STL/GLB/GLTF) → AR-ready link al. Ek olarak
Meshy API ile metinden/görselden 3D model üretimi. Hedef kullanıcılar:
e-ticaret satıcıları, mimarlar/iç mimarlar, eğitimciler, portfolyo sahipleri.

**Değer önerisi:** "3D dosyanı at, 30 saniyede telefonda AR'da gör, linkini
müşterine gönder." Meshy'nin sattığı şey ham model; bizim sattığımız şey
uçtan uca AR yayını (dönüşüm + USDZ + viewer + QR + paylaşım + kütüphane).

---

## 2. Birim Maliyetler (doğrulanmış rakamlar)

### 2.1 AI Üretim (Meshy)

| Kalem | Değer |
|---|---|
| Text-to-3D tam üretim | **20 kredi / model** |
| Meshy Pro ($20/ay, 1.000 kredi) | $0.020/kredi → **$0.40/model** |
| Meshy Studio ($60/ay, 4.000 kredi) | $0.015/kredi → **$0.30/model** |
| API erişimi | Pro+ planlarda, ön ödemeli kredi paketi |

> Çalışma varsayımı: **model başına AI maliyeti $0.30–0.40** (ölçek
> büyüdükçe $0.30'a yaklaşır).

### 2.2 Altyapı (Railway)

| Kalem | Fiyat | Model başına etkisi |
|---|---|---|
| Hobby plan | $5/ay ($5 kullanım dahil) | sabit |
| Pro plan | $20/ay/koltuk | sabit |
| vCPU | $20/vCPU-ay | Upload dönüşümü ~10-60 sn CPU → **<$0.01/model** |
| RAM | $10/GB-ay | sabit ~512MB-1GB → $5-10/ay |
| Volume depolama | $0.15–0.25/GB-ay | Ortalama model (GLB+USDZ+thumb) ~15-30MB → **$0.003-0.008/ay/model** |
| Egress | $0.05–0.10/GB | AR görüntüleme ~10-20MB → **~$0.001-0.002/görüntüleme** |

### 2.3 Model başına toplam maliyet özeti

| Senaryo | Maliyet |
|---|---|
| Kullanıcı upload'u (AI yok) | ~$0.01 üretim + $0.005/ay depo + $0.001/görüntüleme |
| AI üretimi (Meshy) | **~$0.35** üretim + aynı depo/egress |

**Kritik içgörü:** Upload neredeyse bedava, AI üretimi ise gerçek para.
Kredi sistemi yalnızca AI üretimini ölçmeli; upload'u plan limitleriyle
(model sayısı + depolama GB) sınırlamalı.

---

## 3. Üyelik Modeli Önerisi

**1 kredi = 1 AI üretim** (kullanıcıya Meshy kredisi gösterme — kafa karıştırır).

### Katmanlar

| | **Free** | **Pro — $9/ay** | **Studio — $29/ay** |
|---|---|---|---|
| AI üretim kredisi | 3 (tek seferlik, kayıt hediyesi) | **30/ay** | **150/ay** |
| Model upload | 10 model | 200 model | Sınırsız |
| Depolama | 250 MB | 5 GB | 25 GB |
| AR viewer + QR | ✓ | ✓ | ✓ |
| Embed (iframe) | arvision logolu | logolu | **white-label** |
| Versiyon geçmişi | son 1 | tam | tam |
| Çöp kutusu | 7 gün | 30 gün | 30 gün |
| API erişimi | — | — | ✓ (ileride) |

### Ek kredi paketleri (top-up, abonelere)

| Paket | Fiyat | Birim |
|---|---|---|
| 10 kredi | $6 | $0.60/kredi |
| 50 kredi | $25 | $0.50/kredi |
| 200 kredi | $80 | $0.40/kredi |

### Kredi ekonomisi

- Maliyet $0.30–0.40 → satış $0.40–0.60 → **AI tarafında %25–50 brüt marj**.
- Asıl marj abonelikte: Pro'da 30 kredinin tamamı kullanılsa bile maliyet
  ~$10.5 (30×$0.35) → zararda görünür; ANCAK sektör ortalaması kredi
  kullanım oranı %40–60'tır. Gerçekçi beklenen maliyet: ~$4-6/Pro kullanıcı
  → **%35–55 efektif marj**. Studio'da 150×$0.35=$52.5 tavan; %50 kullanımda
  ~$26 → başabaş riski var → Studio kredisini 120'ye çekmek veya $39 yapmak
  güvenli alternatif. (Karar: lansmanda 150 kredi + kullanım verisiyle revize.)
- **Devretme kuralı:** Kullanılmayan krediler 1 ay devreder, sonra yanar
  (maliyet tavanını sınırlar).

### Kötüye kullanım korumaları (kısmen mevcut)

- Günlük AI limiti: zaten var (`AI_GEN_DAILY_LIMIT=10`) — planla ölçekle:
  Free 3/gün, Pro 15/gün, Studio 50/gün.
- Rate limiting: mevcut (commit d534e8a).
- Free hesapta e-posta doğrulaması olmadan AI kredisi verilmemeli (yeni iş).

---

## 4. Toplam Sistem Maliyeti — Senaryolar

Varsayımlar: ort. model 20MB, aylık kullanıcı başına 5 AR görüntüleme,
ücretli kullanıcıların kredi kullanım oranı %50.

### Senaryo A — Başlangıç (100 kayıtlı, 5 ücretli)

| Kalem | Aylık |
|---|---|
| Railway (Hobby + kullanım) | $10–15 |
| Depolama (~5GB) | $1 |
| Egress (~10GB) | $1 |
| Meshy (5 Pro × 15 üretim × $0.40) | $30 → Meshy Pro $20 paketi yeter |
| **Toplam gider** | **~$35–40** |
| Gelir (5 × $9) | $45 |
| **Net** | **≈ başabaş** |

### Senaryo B — Çekiş (1.000 kayıtlı, 40 ücretli: 35 Pro + 5 Studio)

| Kalem | Aylık |
|---|---|
| Railway (Pro plan + 1 vCPU/1GB sürekli) | $40–60 |
| Depolama (~60GB) | $9–15 |
| Egress (~150GB) | $8–15 |
| Meshy (35×15 + 5×75 = 900 üretim ≈ 18.000 kredi) | Studio $60 ×4-5 ≈ $270 |
| Ödeme komisyonu (Paddle/LS ~%5 + $0.50) | ~$35 |
| **Toplam gider** | **~$370–400** |
| Gelir (35×$9 + 5×$29 + top-up ~$50) | **~$510** |
| **Net** | **+$110–140 (%25 marj)** |

### Senaryo C — Ölçek (10.000 kayıtlı, 400 ücretli)

| Kalem | Aylık |
|---|---|
| Railway (2 vCPU, 2GB, worker ayrı) | $120–180 |
| Depolama (~600GB) → R2/S3'e geçiş şart | $10–90 (R2: $9) |
| Egress (~1.5TB) → Cloudflare R2 (egress $0) | $0–150 |
| Meshy (~9.000 üretim) | ~$2.700 (kurumsal anlaşma görüş) |
| Ödeme komisyonu | ~$280 |
| **Toplam gider** | **~$3.2–3.5K** |
| Gelir (350×$9 + 50×$29 + top-up ~$500) | **~$5.1K** |
| **Net** | **+$1.6–1.9K (%32 marj)** |

> **Ölçek dersi:** $0 egress'li Cloudflare R2'ye depolama göçü, Senaryo
> C'de tek başına ayda $150–240 tasarruf sağlar. 50GB'ı geçince planla.

---

## 5. Başabaş Analizi

- Sabit gider tabanı (Senaryo A): ~$15–20/ay (Railway + domain).
- Pro kullanıcı başına katkı: $9 − ~$4.5 (Meshy %50 kullanım) − ~$0.7
  (komisyon) ≈ **$3.8/ay**.
- **Başabaş: ~5 Pro abone.** Son derece düşük giriş bariyeri — bu modelin
  en güçlü yanı.

---

## 6. Ödeme Altyapısı (Türkiye gerçeği)

Stripe Türkiye'de doğrudan yok. Seçenekler:

| Seçenek | Artı | Eksi |
|---|---|---|
| **Paddle / Lemon Squeezy (MoR)** ⭐ önerilen | KDV/vergiyi onlar yönetir, global kart kabul, kolay entegrasyon | ~%5+$0.50 komisyon |
| iyzico / PayTR | Yerli, TL, düşük komisyon (~%2-3) | Global satışta vergi yükü sende, abonelik yönetimi zayıf |
| Gumroad | En hızlı kurulum | %10 komisyon, abonelik UX zayıf |

**Öneri:** Lemon Squeezy ile başla (webhook → kredi yükleme), hacim
büyüyünce Paddle'a geç.

---

## 7. Teknik Yol Haritası (mevcut kod tabanına göre)

### Faz 1 — Kredi defteri (1-2 hafta)
- `User`: `plan` (free/pro/studio), `credits_balance`, `plan_renews_at`
- Yeni tablo `CreditLedger`: user_id, delta, reason
  (subscription_grant/topup/generation/refund), meshy_task_id, created_at
  → bakiye her zaman ledger toplamından doğrulanabilir
- `/api/generate-3d` → kredi kontrolü + düşümü (başarısız üretimde iade);
  mevcut `AI_GEN_DAILY_LIMIT` plana göre parametreleşir
- Plan limitleri: model sayısı + depolama kotası (storage bar zaten var)

### Faz 2 — Ödeme (1 hafta)
- Lemon Squeezy checkout linkleri + webhook endpoint'i
  (subscription_created/renewed/cancelled, order_created→top-up)
- Basit fiyatlandırma sayfası + hesap/plan sayfası

### Faz 3 — Dönüşüm artırıcılar (sürekli)
- Free→Pro tetikleyiciler: kredi bitince paywall, depolama dolunca uyarı,
  embed'de logo
- E-posta doğrulama (kredi hediyesi şartı), kullanım e-postaları
- Studio: white-label embed + (ileride) API anahtarı

---

## 8. Riskler ve Önlemler

| Risk | Önlem |
|---|---|
| Meshy fiyat artışı / API değişikliği | Kredi fiyatını maliyetten ayrıştır (1 kredi = 1 üretim soyutlaması); alternatif sağlayıcı (Tripo, Hyper3D) adaptörü |
| Düşük kredi kullanımı varsayımının şaşması | Devretme sınırı + günlük limit maliyet tavanı koyar |
| Depolama maliyeti büyümesi | Çöp kutusu purge (var), inaktif free hesap arşivleme, R2 göçü |
| AI çıktı kalitesinden iade talepleri | "Başarısız üretimde kredi iadesi otomatik" politikası (ledger destekliyor) |
| Tek geliştirici riski | Alembic migration + worker ayrımı zaten yapıldı; CI eklenebilir |

---

## 9. KPI'lar (aylık takip)

- Kayıt → ücretli dönüşüm oranı (hedef: %3–5)
- Kredi kullanım oranı (hedef bandı: %40–60)
- Kullanıcı başına AI maliyeti / ARPU oranı (<%45)
- Churn (hedef: <%6/ay)
- AR görüntüleme sayısı (ürünün gerçek değer metriği — paylaşılan link
  görüntülenmiyorsa abonelik yenilenmez)
