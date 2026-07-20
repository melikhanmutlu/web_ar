# Kaynaklar ve Arama Sistemi

## Product intelligence

- ARVision kodu, testleri, plan limitleri ve son Git degisiklikleri.
- Shopify Help ve Shopify Developer dokumani.
- Apple Developer AR Quick Look ve USDZ dokumani.
- Google model-viewer dokumani ve GitHub issue'lari.
- Khronos glTF, 3D Commerce, KTX2 ve Asset Auditor kaynaklari.
- Rakip urunlerin resmi dokumani, fiyat sayfasi, changelog'u ve uygulama magazasi yorumlari.

## Account intelligence

- Sirketin resmi urun, katalog, teknik dosya, BIM/3D indirme, proje ve iletisim sayfalari.
- Sirketin resmi haberleri ve basin bultenleri.
- Ticaret fuari katilimci listeleri: Intermob, MODEF, Light + Building, Unicera ve ilgili sektorel fuarlar.
- BIMobject ve ureticinin kendi BIM/CAD kutuphanesi.
- LinkedIn sirket sayfasi ve yalnizca herkese acik profesyonel rol bilgisi.
- Shopify Store Leads veya BuiltWith gibi kaynaklar ancak erisim ve lisans uygunsa; yoksa teknoloji altyapisi tahmin edilmez.

## Satis tetikleyicileri

- Yeni koleksiyon veya urun ailesi lansmani.
- Yeni e-ticaret sitesi, dijital katalog veya mobil deneyim.
- 3D, BIM, DWG, SKP, FBX, STEP veya Revit dosyasi yayinlama.
- Yeni ihracat pazari, bayi agi veya showroom acilisi.
- AR/3D, urun configuratoru, sanal showroom veya dijital donusum girisimi.
- E-ticaret, dijital pazarlama, BIM, urun veya inovasyon rolune yeni alim.
- Web sitesinde 3D gorunum var fakat mobil AR, toplu yayin veya analitik yok.

## Ornek aramalar

```text
site:com.tr ("3D indir" OR "DWG" OR "SKP" OR "FBX") mobilya
site:com.tr ("BIM kutuphanesi" OR "Revit") aydinlatma
site:com.tr ("yeni koleksiyon" OR "e-katalog") mobilya 2026
site:linkedin.com/company Turkey furniture manufacturer 3D BIM
site:linkedin.com/in ("E-commerce Manager" OR "Digital Marketing Manager") <sirket>
site:shopify.com/news 3D AR commerce
site:github.com/google/model-viewer/issues AR iOS Android
site:khronos.org glTF 3D commerce latest
```

## Kayit standardi

Her bulgu su alanlari tasir: `kontrol_tarihi`, `kaynak_url`, `sirket`, `ulke`, `sektor`, `kanit`, `tetikleyici`, `varsayim`, `sonraki_dogrulama`.

Kanit ve yorum ayrilir. Ornegin "FBX indirilebilir" kanittir; "donusum pipeline'i satin alabilir" yorumdur.

## Karar defteri

- 2026-07-21: Genel fikir madenciligi durduruldu. Mevcut ARVision urunune gelir getirecek feature ve gercek hedef hesap arastirmasina gecildi.
- 2026-07-21: Ilk ICP, mevcut CAD/3D katalogu olan Turkiye merkezli mobilya, aydinlatma ve banyo/yapi urunu ureticileri olarak secildi.
- 2026-07-21: Ilk teklif, bes urunluk ucretli AR katalog pilotu olarak tanimlandi.
