# Web AR Uygulaması

3D modelleri web üzerinden görüntülemek ve AR deneyimi sunmak için geliştirilmiş bir web uygulaması.

## Sistem Gereklilikleri

### Zorunlu Yazılımlar
- Python 3.8 veya daha yeni bir sürüm
  - İndirme linki: https://www.python.org/downloads/
  - **ÖNEMLİ**: Kurulum sırasında "Add Python to PATH" seçeneğini işaretlemeyi unutmayın!
- Node.js 14.x veya daha yeni bir sürüm
  - İndirme linki: https://nodejs.org/
  - LTS (Long Term Support) sürümünü indirmeniz önerilir

### Tarayıcı Desteği
- Modern bir web tarayıcısı (Chrome, Firefox, Edge vb.)
- WebGL desteği
- WebXR desteği (AR özelliği için)

## Kurulum

### Otomatik Kurulum (Önerilen)
1. Zip dosyasını istediğiniz bir klasöre çıkarın
2. `install.cmd` dosyasını çalıştırın
3. Kurulum tamamlandıktan sonra `start_server.cmd` ile sunucuyu başlatın
4. Tarayıcınızda `http://localhost:5000` adresine gidin

### Manuel Kurulum
Eğer otomatik kurulum çalışmazsa, aşağıdaki adımları takip edin:

1. Python virtual environment oluşturun:
   ```bash
   python -m venv venv
   ```

2. Virtual environment'ı aktifleştirin:
   - Windows:
     ```bash
     venv\Scripts\activate
     ```
   - Linux/Mac:
     ```bash
     source venv/bin/activate
     ```

3. Python paketlerini yükleyin:
   ```bash
   pip install -r requirements.txt
   ```

4. Node.js paketlerini yükleyin:
   ```bash
   npm install
   ```

5. obj2gltf'i global olarak yükleyin:
   ```bash
   npm install -g obj2gltf
   ```

6. Veritabanını oluşturun:
   ```bash
   flask db upgrade
   ```

7. Sunucuyu başlatın:
   ```bash
   python app.py
   ```

## Kullanım

1. Web tarayıcınızda `http://localhost:5000` adresine gidin
2. Hesap oluşturun veya giriş yapın
3. OBJ formatındaki 3D modelinizi yükleyin
4. Model otomatik olarak GLB formatına dönüştürülecek
5. Modeli web üzerinde görüntüleyin veya AR deneyimi için QR kodu kullanın

## Sorun Giderme

### Python Bulunamadı Hatası
- Python'un PATH'e eklendiğinden emin olun
- Python kurulumunu "Add Python to PATH" seçeneği ile tekrar yapın
- Bilgisayarınızı yeniden başlatın

### Node.js Paket Yükleme Hataları
- Node.js'in doğru şekilde kurulduğundan emin olun
- npm cache'ini temizleyin: `npm cache clean --force`
- Bilgisayarınızı yeniden başlatın

### Veritabanı Hataları
- `instance` klasörünü silin ve `flask db upgrade` komutunu tekrar çalıştırın
- Tüm migrations dosyalarının mevcut olduğundan emin olun

## Lisans

Bu proje MIT lisansı altında lisanslanmıştır. Detaylar için `LICENSE` dosyasına bakın.
