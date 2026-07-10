# Rekabetçi İstihbarat Raporu: ARVision

**URL:** https://webar.up.railway.app (güncel; ileride değişecek)
**Tarih:** 13 Haziran 2026
**Analiz edilen rakip sayısı:** 8 (4 doğrudan, 2 dolaylı, 2 aspirasyonel)
**Rekabetçi Konum: Zayıf–Orta** (güçlü ürün kaması, kurulmamış pazarlama/güven altyapısı)

> **Veri kaynağı uyarısı:** Bu rapor, çalışma ortamının egress kısıtı nedeniyle
> rakip siteleri ve G2/Capterra/Trustpilot **canlı çekilemeden** hazırlandı.
> Rakip profilleri eğitim bilgisine (Ocak 2026) ve ARVision'ın frontend kaynağına
> dayanır. **Kesin fiyatlar, takipçi sayıları ve yıldız puanları "≈/doğrula" ile
> işaretlenmiştir ve yayın öncesi canlı doğrulanmalıdır.** Açık-ağlı bir makinede
> `competitor_scanner.py` ve `/market competitors` ile kesin rakamlar alınabilir.

---

## Yönetici Özeti

ARVision, **"herhangi bir 3D dosyasını yükle → saniyeler içinde çalışan, paylaşılabilir
bir AR linki al"** kamasıyla net bir boşluğa oturuyor; üstüne **yerleşik AI 3D üretimi**
(Meshy backend'i) ekleyerek çoğu "AR görüntüleyici" rakibinin sunmadığı bir kanca
sağlıyor. Sürtünmesiz + ücretsiz + AI'lı bu kombinasyon gerçek bir farklılaşma
potansiyeli.

Ne var ki rakipler — özellikle kategori lideri **Sketchfab** ve tasarım-odaklı
**Vectary** — pazarlamanın masa-payı (table stakes) saydığı her şeyi çoktan kurmuş:
zengin link önizlemeleri, derin SEO, sosyal kanıt, topluluk ve "vs/alternatif"
sayfaları. ARVision bunların neredeyse hiçbirine sahip değil (bkz. MARKETING-AUDIT
skoru 48/100). Yani ARVision **üründe rekabetçi ama pazarlama yüzeyinde görünmez** —
linkleri paylaşılıyor ama önizlemesiz, içeriği indekslenmiyor, kimliği üç işe bölünmüş.

Ek bir stratejik risk: AI üretiminde ARVision, tedarikçisi **Meshy**'nin (ve Tripo/Luma
gibi sağlayıcıların) doğrudan tüketiciye sunduğu ürünle dolaylı rekabet hâlinde. Bu
katmanda ARVision'ın savunulabilir değeri AI değil, **"üretilen modeli anında AR'a
hazır paylaşılabilir linke çevirme"** kolaylığı — bu mesaj hiç vurgulanmıyor.

**En kritik 3 stratejik öneri:** (1) Paylaşım döngüsünü silahlandır (link önizlemeleri
+ herkese açık galeri) — rakiplerin en güçlü olduğu yer ve ARVision'ın en zayıf olduğu
yer. (2) Tek bir kategori sahiplen ("en hızlı ürün→AR linki") ve "vs Sketchfab / vs
Meshy" alternatif sayfaları kur (yüksek-niyetli arama trafiği). (3) Güven katmanı ekle
(gizlilik ifadesi, sosyal kanıt) — yükleme-temelli bir araçta dönüşümün ön koşulu.

---

## Rakip Genel Görünümü

### Doğrudan Rakipler (aynı iş: 3D model → web/AR paylaşımı)

| Rakip | Konumlanma | Fiyat (≈/doğrula) | Ana Farklılaştırıcı |
|-------|-----------|-------------------|---------------------|
| **Sketchfab** (Epic) | "3D modellerini yayınla & paylaş" — kategori lideri | Ücretsiz + Plus/Pro ≈ $15–60/ay | Devasa topluluk, mükemmel paylaşım/embed, SEO |
| **Vectary** | "Tarayıcıda 3D/AR tasarım & paylaşım" | Ücretsiz + ücretli ≈ $12–40/ay | Tarayıcı içi tasarım editörü + AR |
| **echo3D** | "3D/AR için içerik yönetimi + CDN" (geliştirici) | Ücretsiz tier + kullanım bazlı | Backend/CDN, API-öncelikli |
| **Augment / Plattar / Threekit** | "E-ticaret/perakende ürün AR'ı" | Kurumsal/Custom | Ticaret entegrasyonu, konfigüratör |

### Dolaylı Rakipler (aynı sorunu farklı çözen)

| Rakip | Konumlanma | Notlar |
|-------|-----------|--------|
| **Meshy / Tripo / Luma AI** | "Metin/görsel → 3D model (AI)" | ARVision'ın AI tedarikçisi *ve* DTC rakibi; AR-link katmanı yok |
| **Google `<model-viewer>`** | Açık kaynak AR web bileşeni | Ücretsiz/DIY; hosting, dönüşüm, paylaşım yok — ARVision'ın çözdüğü işler |

### Aspirasyonel Rakipler (olunmak istenen)

| Rakip | Neden aspirasyonel |
|-------|--------------------|
| **Sketchfab** | Paylaşım/topluluk/SEO'da olmak istenen yer |
| **Shopify AR / Adobe Aero** | Ticaret/yetkilendirme ölçeğinde AR'ı normalleştiren oyuncular |

---

## Detaylı Rakip Profilleri

### Sketchfab (doğrudan, kategori lideri)
- **Mesaj:** Yayınla, sergile, sat — 3D için "YouTube". Net, tek cümlelik konum.
- **Güçlü:** Milyonlarca model + topluluk (ağ etkisi); kusursuz zengin link önizlemeleri
  ve embed; derin SEO (her model indekslenebilir sayfa); native + WebAR.
- **Zayıf:** AI üretimi zayıf/yok; yeni kullanıcı için "yükle-paylaş" akışı ARVision kadar
  hafif değil; topluluk odağı, hızlı "ürünümü AR'a koyayım" niyetinden uzaklaşabilir.
- **SWOT → ARVision fırsatı:** Sketchfab'ın AI boşluğu ve ağır arayüzü, ARVision'ın
  "hafif + AI'lı" konumuna alan açar.

### Vectary (doğrudan)
- **Mesaj:** Tarayıcıda 3D/AR tasarımı, kod yok.
- **Güçlü:** Güçlü tarayıcı-içi editör, şablonlar, AR önizleme, iyi SEO/eğitim içeriği.
- **Zayıf:** Tasarım editörü öğrenme eğrisi; "sadece var olan dosyamı hızlı AR'a çevir"
  niyeti için fazla ağır.
- **ARVision fırsatı:** "Tasarlama, sadece yükle/üret ve paylaş" sadeliği.

### echo3D (dolaylı, geliştirici)
- **Mesaj:** 3D/AR uygulamaları için içerik yönetimi + CDN.
- **Güçlü:** Ölçeklenebilir backend, API, kullanım-bazlı model.
- **Zayıf:** Son-kullanıcıya dönük "yükle-paylaş" değeri yok; teknik kitle.
- **ARVision fırsatı:** Teknik olmayan kullanıcıya dönüklük.

### Meshy / Tripo / Luma AI (dolaylı, AI 3D üretimi)
- **Mesaj:** Metin/görselden saniyeler içinde 3D model.
- **Güçlü:** Üretim kalitesi/hızı; ARVision'ın AI özelliği zaten Meshy'ye dayanıyor.
- **Zayıf:** Çıktıyı "AR'a hazır, paylaşılabilir, telefonda çalışan link"e çevirme
  katmanı yok; iOS/Android AR + USDZ akışını kullanıcı kendi kurmak zorunda.
- **ARVision fırsatı/tehdidi:** ARVision'ın asıl savunulabilir değeri burada —
  "üret → anında AR linki". **Tehdit:** Meshy bu katmanı kendisi eklerse ARVision'ın
  AI tarafındaki ayrımı zayıflar.

### Google model-viewer (dolaylı, DIY)
- **Güçlü:** Ücretsiz, Google destekli, geliştirici benimsemesi.
- **Zayıf:** Hosting, dönüşüm (FBX/OBJ/STL→GLB/USDZ), paylaşım, QR yok — hepsi
  ARVision'ın hazır sunduğu işler.
- **ARVision fırsatı:** "model-viewer'ı kendin kurma; biz dönüşüm+hosting+link veriyoruz."

---

## Karşılaştırma Tabloları

### Özellik Karşılaştırması
| Kategori | Özellik | ARVision | Sketchfab | Vectary | model-viewer |
|----------|---------|----------|-----------|---------|--------------|
| Çekirdek | FBX/OBJ/STL→GLB dönüşümü | Tam | Kısmi | Kısmi | Yok |
| Çekirdek | iOS Quick Look (USDZ) | Tam | Tam | Tam | Kısmi |
| Çekirdek | Android Scene Viewer | Tam | Tam | Tam | Tam |
| Çekirdek | Paylaşılabilir link | Tam | Tam | Tam | Yok |
| Çekirdek | Zengin link önizlemesi (OG) | **Yok** | Tam | Tam | Yok |
| Çekirdek | Embed görüntüleyici | Tam | Tam | Tam | Tam (DIY) |
| AI | Metin/görsel→3D üretim | Tam | Yok | Kısmi | Yok |
| Editör | Tarayıcı-içi düzenleme/slice | Kısmi | Kısmi | Tam | Yok |
| Keşif | Herkese açık galeri/topluluk | **Yok** | Tam | Kısmi | Yok |
| Güven | Sosyal kanıt/yorum | **Yok** | Tam | Kısmi | — |

**ARVision moat'ları:** Dönüşüm genişliği + yerleşik AI + sürtünmesiz ücretsiz akış.
**ARVision açıkları:** Link önizlemesi, galeri/topluluk, güven sinyalleri.

### Fiyatlama Karşılaştırması (≈ — canlı doğrula)
| Plan | ARVision | Sketchfab | Vectary |
|------|----------|-----------|---------|
| Ücretsiz plan | Evet (AI günlük limitli) | Evet | Evet |
| Başlangıç | — (belirsiz) | ≈ $15/ay | ≈ $12/ay |
| Pro | — | ≈ $60/ay | ≈ $40/ay |
| Fiyat şeffaflığı | Fiyatlandırma sayfası yok | Şeffaf | Şeffaf |
| Model | Belirsiz (AI kredi iması var) | Abonelik | Abonelik |

> ARVision'da kamuya açık bir **fiyatlandırma stratejisi/sayfası görünmüyor**; AI
> "kredi" ve "günlük limit" ima ediliyor. Bu, hem dönüşüm hem konumlanma için boşluk.

### Konumlanma Haritası
```
                         PREMIUM / KURUMSAL
                                |
              Plattar/Threekit  |  Adobe Aero
                                |  Shopify AR
        Vectary                 |
  BASİT ──────────────────────┼────────────────────── GÜÇLÜ/DERİN
        ARVision               |  Sketchfab
        (+AI, hafif)           |  echo3D
                                |  Meshy/Tripo (AI)
                         ÜCRETSİZ / HAFİF
```
*ARVision "basit + ücretsiz + AI" çeyreğinde yalnız sayılır — savunulması ve
iletişimi gereken değerli bir konum.*

### İçerik & SEO Boşluk Analizi
```
İÇERİK BOŞLUKLARI (Rakipler kapsıyor, ARVision kapsamıyor):
  1. "STL/FBX/OBJ AR'da nasıl görüntülenir" — yüksek niyet, düşük rekabet
  2. "OBJ to GLB / FBX to GLB dönüştürme" — yüksek niyet (ARVision'ın tam işi)
  3. "iPhone için USDZ AR" — orta-yüksek niyet
  4. "Sketchfab/Vectary alternatifi" — bottom-of-funnel, hiç yok
  5. Herkese açık örnek model galerisi (indekslenebilir yüzey) — kritik boşluk
```

---

## SWOT Analizi — ARVision

**Güçlü (Strengths):** Net hero vaadi; geniş format dönüşümü; yerleşik AI üretimi;
sürtünmesiz ücretsiz akış; iOS+Android AR + embed hazır.

**Zayıf (Weaknesses):** Sıfır link önizlemesi/OG; SEO temeli yok; sosyal kanıt/güven
yok; fiyatlama/konum belirsiz; galeri/topluluk yok; AI değeri login arkasında.

**Fırsatlar (Opportunities):** "En hızlı ürün→AR linki" kategorisini sahiplenmek;
"vs Sketchfab / vs Meshy" alternatif sayfaları; format-derdi SEO içeriği; embed
atıflı viral döngü; AI çıktısını AR-linke bağlama mesajı (kimse net yapmıyor).

**Tehditler (Threats):** Sketchfab'ın topluluk/SEO ağ etkisi; Meshy/Tripo'nun AI
katmanına "paylaşım" eklemesi; Shopify/Adobe'nin AR'ı platformlarına gömmesi.

---

## Stratejik Öneriler

### "Çalınmaya Değer" Taktikler
1. **Sketchfab — zengin link önizlemeleri & her modele indekslenebilir sayfa.**
   Neden işliyor: her paylaşım hem tıklanır hem SEO yüzeyi. Nasıl: view/embed'e OG/Twitter
   (mevcut thumbnail ile). Efor: Düşük · Etki: Yüksek.
2. **Sketchfab/Vectary — herkese açık galeri/topluluk.** Sosyal kanıt + SEO + döngü.
   Nasıl: opt-in herkese açık model akışı. Efor: Orta · Etki: Yüksek.
3. **Vectary — eğitim/tutorial içeriği (SEO).** "Nasıl yapılır" içerikleri yüksek-niyetli
   trafik çeker. Efor: Orta · Etki: Orta-Yüksek.
4. **Sketchfab — şeffaf, değer-önce fiyatlandırma sayfası.** Belirsizliği gider.
   Efor: Düşük · Etki: Orta.
5. **Meshy — AI çıktısının canlı örneğini login öncesi göster.** Wow'u duvardan öne al.
   Efor: Orta · Etki: Orta-Yüksek.
6. **Genel — embed'de "Powered by ARVision" atfı.** Her embed bir edinim kanalı.
   Efor: Düşük · Etki: Orta (bileşik).

### Farklılaşma Stratejisi
- **Kategori:** "Herhangi bir 3D dosyasını (ya da bir AI promptunu) saniyeler içinde
  telefonlarda çalışan, paylaşılabilir bir AR linkine çeviren en hızlı yol."
- **Özellik:** Tek üründe **dönüşüm + AI üretim + AR hosting + paylaşım** — rakipler
  bunların yalnız bir-iki parçasını veriyor.
- **Felsefe:** "Tasarlama/öğrenme yok — yükle/üret, paylaş." Vectary'nin editör
  ağırlığına ve model-viewer'ın DIY yüküne karşı sadelik.

### Oluşturulacak "Alternatif" Sayfaları
```
SAYFA: ARVision vs Sketchfab        → /vs/sketchfab
  Kanca: "Topluluk değil, hızlı AR linki mi arıyorsun? Neden ekipler ARVision seçiyor."
  Kazandığı yer: hız, ücretsizlik, yerleşik AI, format genişliği.
  Dürüst kaybettiği yer: topluluk/keşif ölçeği.

SAYFA: ARVision vs Meshy (AI)        → /vs/meshy
  Kanca: "AI ile model üret — sonra? ARVision onu anında AR-linke çevirir."
  Kazandığı yer: üretim→AR→paylaşım tek akış; USDZ/QR otomatik.

SAYFA: model-viewer kurmadan AR      → /alternatives/model-viewer
  Kanca: "model-viewer'ı kendin host etme; dönüşüm+hosting+link hazır gelsin."
```

### Geçiş (Switching) Anlatısı
```
Meshy/Tripo → ARVision:
  Neden geçilir: 1) Üretilen modeli AR'a hazır hâle getirme zahmeti, 2) iOS USDZ/QR
  kurulum derdi, 3) paylaşılabilir tek link ihtiyacı.
  Hikâye şablonu: "Çoğu kullanıcı gibi [isim] modeli Meshy'de üretti ama telefonda
  AR olarak göstermek isteyince USDZ/hosting'e takıldı. ARVision'a geçince tek
  yüklemeyle çalışan bir AR linki aldı."
  Teklif: AI ile üretilenler için ücretsiz AR-link + ilk N üretim hediyesi.
```

---

## Rekabetçi İzleme Planı
- [ ] Sketchfab, Vectary, Meshy için Google Alerts kur
- [ ] Rakiplerin fiyatlandırma sayfalarını aylık kontrol et
- [ ] G2/Capterra/Trustpilot'ta kategori puanlarını üç ayda bir tara (canlı)
- [ ] Meshy/Tripo/Luma'nın "paylaşım/AR" özelliği eklemesini izle (en büyük tehdit)
- [ ] Meta Ad Library / Google Ads Transparency'de rakip reklamlarını takip et

| Rakip Hamlesi | Yanıt Stratejisi | Süre |
|----------------|------------------|------|
| Fiyat indirimi | Değer/kaliteyi vurgula, fiyat savaşına girme | 1 hafta |
| Yeni özellik | Alaka değerlendir, yol haritasını müşteriye ilet | 2 hafta |
| AI sağlayıcının "AR paylaşım" eklemesi | "üret→AR→paylaş tek akış" mesajını derinleştir | 1-2 hafta |
| Negatif karşılaştırma içeriği | Olgusal, dengeli karşılaştırma sayfası yayınla | 1 hafta |

---

## Sonraki Adımlar
1. **Paylaşım döngüsünü silahlandır** — link önizlemeleri (view/embed OG) + herkese
   açık galeri. Rakiplerin en güçlü, ARVision'ın en zayıf olduğu alan.
2. **"vs Sketchfab" ve "vs Meshy" alternatif sayfalarını** kur — bottom-of-funnel
   arama trafiğini yakala, farklılaşmayı netleştir.
3. **Güven + fiyat netliği** ekle — gizlilik ifadesi, sosyal kanıt, şeffaf fiyat sayfası.

*AI Marketing Suite (Claude Code) — `/market competitors` · kaynak + bilgi-tabanlı çalışma*
