# Pazar ve Teknoloji Sinyalleri, 2026-07-21

## Karari degistiren bulgular

### 1. Shopify tek basina ana farklilasma alani degil

Shopify resmi dokumani GLB ve USDZ kabul ediyor, buyuk dosyalari otomatik optimize ediyor ve yonetici panelinde kod yazmadan isik, kamera ve arka plan ayari sunuyor. Tema uyumlulugu ve API entegrasyonu halen firsat olsa da "Shopify icin model optimize et" tek basina guclu bir urun tezi degil.

- https://help.shopify.com/en/manual/products/product-media/product-media-types
- https://help.shopify.com/en/manual/online-store/images/3d-images
- https://shopify.dev/docs/api/admin-graphql/latest/objects/model3d

Sonuc: ARVision, Shopify'in yerine gecmek yerine CAD-to-catalog onboarding, platformlar arasi QA, toplu operasyon ve attribution satmali.

### 2. Cross-platform QA halen degerli

Apple Quick Look web sitelerinde USDZ ile AR, custom action ve banner destekliyor. Khronos ise glTF 3D Commerce, KTX2, Asset Auditor ve validation ekosistemini gelistiriyor. Bu, tek dosya donusumunden daha yuksek degerli bir "yayina hazirlik ve uyumluluk" katmanini destekliyor.

- https://developer.apple.com/augmented-reality/quick-look/
- https://developer.apple.com/documentation/ARKit/previewing-a-model-with-ar-quick-look
- https://www.khronos.org/gltf/
- https://www.khronos.org/ktx/

Sonuc: Toplu readiness raporu; dosya boyutu, texture, material, olcek, AR placement, GLB ve USDZ sonucunu birlikte gostermeli.

### 3. En guclu ilk segment CAD varligi hazir ureticiler

NSON urunleri icin DWG, SKP, MAX, 3DS ve FBX; Addo urun bazinda DWG, 3DS, MAX ve SKP; Caris urunlerinde 3D indirme sunuyor. MGT Filtre 2.556'dan fazla Revit modelinden olusan kutuphane yayinliyor. Bu firmalar 3D asset uretme problemini buyuk olcude cozmus durumda.

- https://www.nson.com.tr/
- https://addo.com.tr/products/cube-ofis-oturma-grubu
- https://www.caris.com.tr/kanepe
- https://mgt.com.tr/bim/

Sonuc: Ilk satis mesaji "size model uretelim" degil, "mevcut modellerinizi 10 gunde web ve AR kataloguna donusturelim" olmali.

### 4. Katalog ve ihracat sinyali pilot degerini artiriyor

Creavit 2026 kataloglari yayinliyor ve 65'ten fazla ulkeye urun sundugunu belirtiyor. Enza Home 300'den fazla yurtiçi/yurtdisi magazaya sahip oldugunu belirtiyor. Bu olcek, lokal demo yerine cok dilli, bayi ve web kanallarinda tekrar kullanilan bir katalog altyapisi ihtimalini guclendiriyor.

- https://www.creavit.com.tr/en/documents/catalogues/
- https://www.creavit.com.tr/en/who-we-are/about-us/
- https://www.enzahome.com.tr/

Sonuc: Enterprise hesaba ilk gunden tum katalog degil, tek koleksiyon veya bes urunluk pilot onerilmeli.

## Izlenecek gelismeler

- Shopify product media ve Model3d API degisiklikleri
- Apple Quick Look, RealityKit ve web `<model>` destegi
- model-viewer surumleri ve iOS/Android regresyonlari
- Khronos glTF validator, KTX2 ve 3D Commerce rehberleri
- Hedef firmalarda yeni koleksiyon, e-katalog, BIM kutuphanesi ve e-ticaret yenilemeleri
