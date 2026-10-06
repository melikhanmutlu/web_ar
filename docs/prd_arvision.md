# Ürün Gereksinim Dokümanı (PRD) - ARVision

## 1. Proje Genel Bakış
**ARVision**, kullanıcıların 3D modellerini (OBJ, FBX, STL) web üzerinden yüklemelerine, bu modelleri optimize edilmiş GLB formatına dönüştürmelerine ve hem web tarayıcısı üzerinden hem de Artırılmış Gerçeklik (AR) teknolojisiyle mobil cihazlarında görüntülemelerine olanak tanıyan tam kapsamlı bir web platformudur.

## 2. Hedefler ve Amaçlar
*   **Modellerin Kolay Dönüşümü:** Karmaşık 3D formatlarını web ve AR uyumlu standart formatlara (GLB/USDZ) otomatik dönüştürmek.
*   **Etkileşimli Deneyim:** Kullanıcılara modeller üzerinde ölçüm yapma, kesit alma ve görsel düzenlemeler yapma imkanı sunmak.
*   **Erişilebilirlik:** QR kod teknolojisi ile masaüstünden mobil AR deneyimine pürüzsüz geçiş sağlamak.
*   **Organizasyon:** Kullanıcıların modellerini klasör yapısı ve versiyon takibi ile yönetebilmelerini sağlamak.

## 3. Hedef Kitle
*   3D Tasarımcılar ve Mimarlar
*   E-ticaret platformu sahipleri (ürünlerini AR ile sergilemek isteyenler)
*   Endüstriyel ürün tasarımcıları
*   Mühendisler ve teknik personel (ölçüm ve analiz araçları için)

## 4. Teknik Teknoloji Yığını (Tech Stack)
### Backend
*   **Framework:** Flask (Python 3.8+)
*   **Veritabanı:** SQLAlchemy ile SQLite (Geliştirme aşamasında)
*   **Kimlik Doğrulama:** Flask-Login
*   **3D İşleme Kütüphaneleri:** Trimesh, PyGLTFlib, NumPy
*   **Dönüştürme Araçları:** FBX2glTF, obj2gltf (Node.js)

### Frontend
*   **Tasarım:** Tailwind CSS 3.x (Modern, minimal ve responsive UI)
*   **3D Görüntüleyici:** Google `<model-viewer>`
*   **Etkileşim:** Vanilla JavaScript (Hız ve verimlilik odaklı)
*   **Fontlar:** Poppins (Başlıklar), Inter (Metinler)

## 5. Temel Özellikler

### 5.1. Model Yükleme ve Dönüştürme
*   **Çoklu Format Desteği:** OBJ (MTL ve dokularla birlikte), FBX, STL, GLB, GLTF.
*   **Otomatik Dönüştürme:** Yüklenen modellerin otomatik olarak GLB (ve iOS için USDZ) formatına geçirilmesi.
*   **Ön İşleme Ayarları:** Yükleme sırasında model boyutunu sınırlama (cm bazında) ve ana renk uygulama opsiyonları.

### 5.2. Gelişmiş 3D Görüntüleyici Araçları
*   **Kamera Kontrolleri:** Orbit, zoom, pan, FOV (Görüş açısı) ayarı.
*   **Görsel Düzenleme:** Arkaplan rengi, çevre aydınlatması (Environment), gölge yoğunluğu ve pozlama kontolü.
*   **Manipülasyon:** Modelin X, Y, Z eksenlerinde ölçeklendirilmesi, konumlandırılması ve döndürülmesi.
*   **Analiz Araçları:**
    *   **Ölçüm Modu:** İki nokta arası mesafe ve üç nokta arası açı ölçümü.
    *   **Kesit Alma (Cross Section):** Modelin X, Y veya Z eksenlerinde kesitlerinin incelenmesi.
*   **Bilgi Paneli:** Vertice/Face sayıları, model boyutları (En, Boy, Derinlik) ve watertight (su sızdırmazlık) durumu.

### 5.3. Kullanıcı Yönetimi ve Organizasyon
*   **Dashboard:** Kişisel model geçmişi ve yönetimi.
*   **Klasör Sistemi:** Modelleri kategorize etmek için iç içe klasör yapısı.
*   **Versiyon Takibi:** Modeller üzerinde yapılan değişikliklerin (ölçekleme, renk değişimi vb.) versiyonlama ile geriye dönük takibi.
*   **Arama ve Filtreleme:** İsim, tarih ve boyuta göre modelleri organize etme.

### 5.4. AR ve Paylaşım
*   **Native AR Deneyimi:** Android (Scene Viewer) ve iOS (Quick Look) cihazlar için tam destek.
*   **QR Kod Entegrasyonu:** Masaüstünde incelenen modelin mobil cihaza aktarımı için otomatik QR kod oluşturma.
*   **İndirme Seçenekleri:** Optimize edilmiş GLB dosyalarının indirilmesi.

## 6. Fonksiyonel Gereksinimler
1.  Sistem, 100MB'a kadar olan 3D dosyalarını kabul etmelidir.
2.  OBJ dosyaları yüklenirken ilişkili .mtl ve doku dosyaları (jpg, png, bmp vb.) eşleştirilmelidir.
3.  Kullanıcı giriş yapmadan model dönüştürebilmeli ancak kaydetmek için hesap oluşturmalıdır.
4.  Dönüştürme işlemi arka planda (asenkron) loglanarak takip edilmelidir.

## 7. Fonksiyonel Olmayan Gereksinimler
*   **Performans:** Model dönüştürme işlemi ortalama boyutlu modeller için <30 saniye sürmelidir.
*   **Güvenlik:** Yüklenen dosyalar `secure_filename` süzgecinden geçmeli, UUID ile depolanmalıdır.
*   **Responsive Tasarım:** Uygulama mobil, tablet ve masaüstü cihazlarda sorunsuz çalışmalıdır (Mobile-first yaklaşımı).
*   **Kullanılabilirlik:** Karanlık ve aydınlık mod desteği kullanıcı tercihine sunulmalıdır.

## 8. Veri Modeli
*   **User:** ID, Username, Email, PasswordHash, Timestamps.
*   **Folder:** ID, Name, Slug, UserID, ParentID.
*   **UserModel:** ID (UUID), Filename, USDZ_path, Metadata (Vertices, Faces, Bounds), Color, Folders, VersionHistory.
*   **ModelHotspot:** ID, ModelID, Position(X,Y,Z), Title, Description.
*   **ModelVersion:** ModelID, VersionNumber, Path, Operation(Transform, Slice, etc.).

## 9. Gelecek Geliştirmeler (Roadmap)
*   Toplu model yükleme (Batch upload).
*   Ortak çalışma (Folder sharing).
*   Model optimizasyonu (Polygon sayısı azaltma).
*   API erişimi (Üçüncü parti entegrasyonlar için).
*   USDZ formatının sunucu tarafında otomatik üretimi için daha gelişmiş araçlar.
