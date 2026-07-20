# Codex Cloud Kurulum Rehberi

## Hedef mimari

- GitHub, kod ve Growth OS dosyalari icin kalici kaynak.
- Codex Cloud, repo analizi, feature gelistirme, test ve PR hazirlama icin.
- ChatGPT web Scheduled, gunluk pazar ve hedef hesap arastirmasi icin.
- Scheduled veya cloud task ciktilari once rapor/PR olarak gelir. Disariya mesaj
  gonderme insan onayina baglidir.

## 1. GitHub ve Codex Cloud

1. `melikhanmutlu/web_ar` reposunu Codex hesabina bagla.
2. Codex Settings > Environments altinda bu repo icin environment olustur.
3. Varsayilan branch olarak `main` sec.
4. Python 3.12 ve Node.js 20 kullan.
5. Setup script:

   ```bash
   python -m pip install -r requirements.txt
   npm ci
   ```

6. Agent internet access'i arastirma gorevleri icin ac. Mumkunse HTTP
   `GET/HEAD` ile sinirla. Kod gelistirme gorevlerinde interneti yalnizca
   gerekli dokuman ve paket alan adlariyla sinirla.
7. Environment'i bir kez su promptla test et:

   ```text
   AGENTS.md dosyasini oku. ARVision v38 urun envanterini koddan dogrula.
   Dosya degistirmeden mevcut Growth OS yapisini ve ilk uc satis odakli
   feature'i ozetle.
   ```

Cloud task repo checkout'u, setup'i, kod degisikliklerini ve testleri izole bir
container'da yapar. Sonucta diff ve gerekirse PR hazirlanir.

## 2. Web Scheduled gorevleri

### Gunluk satis radari

- Zaman: hafta ici 09:00, Europe/Istanbul.
- Kaynak prompt:
  `.github/prompts/webar-sales-radar.md`
- Cikti: en fazla 10 yeni/guncellenmis hesap, kaynaklar ve aksiyonlar.
- Kalici kayit: onaylanan bulgular
  `docs/fikir-madencisi/hesaplar/` altinda tarihli rapora eklenir.

### Haftalik product-growth

- Zaman: pazartesi 10:00, Europe/Istanbul.
- Kaynak prompt:
  `.github/prompts/webar-product-growth.md`
- Cikti: en fazla 3 feature ve 10 hesap aksiyonu.
- Kod degisikligi gerekirse ayri Codex Cloud task ve draft PR acilir.

Web Scheduled gorevleri yerel klasoru kalici tutmaz. Gerekli talimatlar GitHub
reposunda, bagli projede veya task promptunda bulunmalidir.

## 3. Guvenlik

- Cloud environment'a uygulamanin production secret'larini koyma.
- Arastirma gorevlerinde yazma yetkisini kapali veya minimum tut.
- External outreach, CRM yazimi, issue/PR acma ve merge aksiyonlarini insan
  onayina bagla.
- Sirket ve kisi verilerinde yalnizca kamusal profesyonel bilgiyi kullan.
- Ilk uc scheduled run'i elle incele, sonra sorgu ve sikligi ayarla.

## 4. API anahtarsiz ve API anahtarli secenek

ChatGPT/Codex aboneligindeki cloud ve Scheduled gorevleri icin GitHub Actions
API anahtari gerekmez. Tamamen GitHub cron uzerinden headless Codex calistirmak
istenirse `openai/codex-action@v1` ve repository secret olarak
`OPENAI_API_KEY` gerekir. Secret yokken bu workflow eklenmemelidir.
