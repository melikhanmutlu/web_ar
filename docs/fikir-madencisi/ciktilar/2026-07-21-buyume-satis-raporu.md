# ARVision Buyume ve Satis Raporu, 2026-07-21

## Yonetici karari

Ilk odak: CAD/3D varligi hazir ofis mobilyasi ureticilerine bes urunluk ucretli `AR Katalog Pilotu` satmak.

Ilk uc hesap: NSON, Addo ve Caris. Bu sirketlerde urun bazli 3D/CAD varligi kamusal olarak dogrulanabildigi icin model uretme bagimliligi dusuk, ilk degeri gosterme suresi kisadir.

Ilk feature: `CSV/SKU tabanli katalog onboarding ve toplu publish cockpit`. v38'in toplu upload, klasor, etiket, conversion job, viewer ve embed yeteneklerini tek bir B2B pilot akisina baglar.

## Neden bu yon

- ARVision'da temel donusum, viewer, AR, paylasim, analitik, API ve ekip altyapisi zaten var.
- Satis engeli yeni bir 3D motor degil; 5-50 urunu SKU, varyant, urun URL'si ve yayin durumuyla yonetme eksigi.
- Shopify artik buyuk 3D dosyalarini optimize ediyor ve no-code viewer ayarlari sunuyor. Yalnizca Shopify optimizer olmak zayif farklilasma.
- CAD arsivi olan ureticilerde `mevcut modeli web ve AR kanalina acma` teklifi somut ve hizli test edilebilir.

## Feature kuyrugu

| Feature | Cozdugu satis engeli | Mevcut temel | Efor | Skor | Karar |
|---|---|---|---|---:|---|
| CSV/SKU katalog onboarding + publish cockpit | Bes urunluk pilot bile manuel ve daginik gorunuyor | Batch upload, folders, tags, jobs, viewer | 2 hafta | 24 | Simdi yap |
| Toplu AR readiness raporu + fix queue | Musteri hangi dosyanin yayina hazir oldugunu bilmiyor | Validation, asset quality, derivatives, USDZ | 2 hafta | 23 | Simdi yap |
| Viewer CTA + attribution | Pilotun teklif/sepete etkisi kanitlanamiyor | Analytics events, embed, API | 1-2 hafta | 22 | Simdi yap |
| Shopify/Woo direct product mapping | Snippet elle yerlestiriliyor | Integration snippets, API/webhook | 3-4 hafta | 19 | Ilk pilot talebiyle |
| Self-serve odeme | Online upgrade yok | Plans, billing log, credits | 2-4 hafta | 17 | Ucretli pilot sonrasi |
| Gelismis configurator | Varyantli urunlerde degerli ama kapsam genis | Material presets, scenes | 6+ hafta | 13 | Ertele |

## Iki haftalik MVP 1: Catalog Pilot Cockpit

- CSV alanlari: SKU, urun adi, kategori, varyant, urun URL'si, kaynak dosya adi.
- Yuklenen dosyalari CSV satirlariyla eslestirme ve hata listesi.
- Her satirda conversion, GLB, USDZ, thumbnail, validation ve publish durumu.
- Secilen modelleri tek seferde klasore, etikete ve public/embed durumuna alma.
- Pilot sonunda paylasilabilir katalog durum ozeti.

Kabul kriteri: NSON/Addo benzeri bes urunluk ornek katalog tek CSV ve dosya paketiyle olusturuluyor; eksik dosya, basarisiz donusum ve USDZ durumu satir bazinda goruluyor; bes viewer linki ve embed snippet'i tek ekrandan aliniyor.

Basari metrigi: `time-to-first-published-catalog < 60 dakika` ve operatorun manuel ekran gecislerinde en az yuzde 60 azalma.

## Iki haftalik MVP 2: Readiness Report

- Dosya boyutu, triangle, texture boyutu/formati, material/alpha, olcek, bounding box, animasyon ve GLB/USDZ durumu.
- Web, iOS AR ve Android AR icin ayri `hazir`, `uyari`, `bloklu` sonucu.
- Mevcut optimizer/derivative islemlerine yonlendiren fix action.
- Katalog seviyesinde gecen/uyari/bloklu sayisi.

Kabul kriteri: Bes urunluk pilotta teknik sorunlar musteriye gonderilebilir tek raporda aciklaniyor ve her bloklu kaydin aksiyonu var.

Basari metrigi: Ilk yayin sonrasi teknik geri donus sayisi ve model basina hazirlama suresi.

## Iki haftalik MVP 3: CTA ve Attribution

- Viewer icinde yapilandirilabilir `Urunu incele`, `Teklif al` veya `Sepete git` CTA'si.
- Viewer open, AR open ve CTA click olaylarinin ayni session/referrer ile raporlanmasi.
- Model ve katalog bazinda funnel: viewer -> AR -> CTA.
- UTM ve embed domain kirilimi.

Kabul kriteri: Pilot marka hangi urunun kac viewer, AR ve CTA etkilesimi aldigini gorebiliyor.

Basari metrigi: AR acma orani, CTA click-through ve en cok etkilesim alan SKU.

## Ilk 30 gun satis plani

### Hafta 1

- NSON, Addo ve Caris icin kamusal dosyalardan birer urun uygunluk ornegi hazirla; dosya kullanim kosullarini kontrol et.
- Her firma icin 90 saniyelik ekran kaydi ve tek sayfalik pilot kapsami olustur.
- Mesajlari ilgili dijital pazarlama/urun/tasarim rolune gore kisisellestir.

### Hafta 2

- Ilk 5 Tier A hesaba kurumsal kanaldan ulas.
- 4. gunde teknik risk raporu acisiyla, 10. gunde katalog/ROI acisiyla takip et.
- En az uc kesif gorusmesi hedefle; gorusmede format, katalog sahibi, yayin kanali ve basari metrigi dogrula.

### Hafta 3

- En guclu hesapla bes urunluk ucretli pilot kapsam ve fiyat teklifini ver.
- Catalog Pilot Cockpit MVP'sini gercek pilot verisiyle tamamla.
- Scope disini acik tut: sifirdan modelleme, agir configurator ve ozel native uygulama.

### Hafta 4

- Pilotu gercek web sayfasinda veya kampanya landing'inde yayinla.
- Viewer, AR ve CTA baseline'ini raporla.
- 20-50 urunluk katalog rollout ve yillik Business teklifini sun.

## Kesif gorusmesi sorulari

1. Urunlerinizin 3D dosyalari hangi formatlarda ve hangi ekip tarafindan yonetiliyor?
2. 3D dosyalar bugun mimar, bayi, e-ticaret ve son kullanici kanallarinda nasil kullaniliyor?
3. Bir urunun web veya mobil AR'da yayina alinmasi bugun kac adim ve kac gun suruyor?
4. Olcek, malzeme, renk veya cihaz uyumlulugunda en cok hangi sorun geri donuyor?
5. Bes urunluk pilotun basarili sayilmasi icin hangi is metriğini gormek istersiniz?

## Haftalik metrik panosu

| Metrik | Ilk 30 gun hedefi |
|---|---:|
| Dogrulanmis Tier A hesap | 15 |
| Kisisellestirilmis ilk temas | 10 |
| Olumlu cevap | 3 |
| Kesif gorusmesi | 3 |
| Pilot teklifi | 2 |
| Ucretli pilot | 1 |
| Ilk katalog yayin suresi | 10 is gununden kisa |

## Sonraki karar noktasi

On kesif gorusmesinden sonra ICP yeniden puanlanmali. Ofis mobilyasi hesaplari CAD-to-AR ve katalog operasyonuna acik cevap vermezse ikinci segment banyo urunleri, ucuncu segment mimari aydinlatmadir. Yeni bir buyuk feature'a bu gorusmelerden once baslanmamalidir.
