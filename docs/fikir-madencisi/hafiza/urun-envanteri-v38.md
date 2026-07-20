# ARVision v38 Urun Envanteri

Kontrol tarihi: 2026-07-21
Kaynak: v38 commit `5bbb1da`, route'lar, modeller, servisler ve testler.

## Bugun satilabilir yetenekler

| Alan | Mevcut yetenek | Kanit |
|---|---|---|
| Donusum | OBJ, FBX, STL, STEP/STP ve GLB tabanli akislar; USDZ uretimi | converter modulleri, upload ve USDZ route'lari |
| Katalog | Klasor, etiket, toplu yukleme, toplu gorunurluk ve model tasima | `models_crud`, `upload` |
| Yayin | Public viewer, iframe embed, QR, ozel paylasim linki | `viewer`, `sharing` |
| E-ticaret | Shopify Liquid ve WooCommerce shortcode snippet uretimi | `/api/models/<id>/integration-snippets` |
| AR | iOS USDZ/Quick Look, Android/model-viewer akisi, zemin/duvar ayari | viewer settings ve USDZ servisleri |
| Duzenleme | Boyut, transform, renk, material preset, slice, olcum, exploded view | editing, geometry ve viewer araclari |
| Is birligi | Organizasyon, roller, paylasilan klasor, yorum, hotspot ve kamera gorunumu | organizations ve hotspots |
| Asset operasyonu | Surumleme, karsilastirma, geri alma, LOD ve derivative | versions ve geometry |
| Analitik | View, AR ve etkilesim olaylari; model bazli panel ve API | engagement ve model analytics |
| Gelistirici | API token, model/analytics API ve webhook | api_tokens ve webhooks |
| Kurumsal | Ozel alan adi, white-label ve plan bazli yetkilendirme temeli | organizations ve plans |
| AI | Meshy ile text/image-to-3D ve prompt/material preset | ai_generation ve material_presets |

## Satisi engelleyen ana bosluklar

1. Katalog onboarding'i dosya merkezli. SKU, urun URL'si, varyant, kategori ve CSV ile toplu esleme akisi yok.
2. Model validation endpoint'i var, fakat yoneticiye sunulabilir toplu "yayina hazirlik" raporu ve otomatik duzeltme kuyrugu yok.
3. Snippet uretiliyor, fakat Shopify/WooCommerce icin urun-SKU esleme, kurulum dogrulama ve tek tik publish baglantisi yok.
4. Analitik olaylari var, fakat urun CTA, sepete ekleme veya teklif talebiyle attribution akisi tamamlanmamis.
5. Business plan ve billing kayitlari var, ancak self-serve odeme saglayicisi bagli degil.
6. Organizasyon ve white-label yetkileri var, fakat B2B pilot onboarding'i ve katalog rollout UI'i tek bir akis olarak paketlenmemis.

## Stratejik sonuc

ARVision'in problemi temel 3D teknoloji eksigi degil, mevcut yeteneklerin uretici katalog operasyonu olarak paketlenmemis olmasidir. Ilk roadmap teknik derinlikten cok onboarding, SKU esleme, toplu QA, publish ve ROI kanitina odaklanmalidir.
