# WebAR Growth OS

Bu klasor, genel SaaS fikri aramak icin degil, mevcut ARVision urununu gelistirmek ve satmak icin calisir.

Sistem uc soruya surekli cevap uretir:

1. Mevcut urune hangi ozellik eklenirse satis veya pilot baslatma ihtimali en cok artar?
2. Bu urun bugun hangi gercek sirketlere, hangi kullanim senaryosuyla satilabilir?
3. Hangi pazar sinyali, sirket olayi veya teknik gelisme aksiyon almamizi gerektiriyor?

## Agent yapisi

| Agent | Gorev | Ana cikti |
|---|---|---|
| Product Growth Agent | v38 envanteri ile musteri ihtiyacini karsilastirir | Gelir etkili feature kuyrugu |
| Account Research Agent | Gercek sirketleri ve satis tetikleyicilerini bulur | Kaynakli hedef hesap listesi |
| Sales Ops Agent | Hesabi teklif, pilot ve mesaj akimina cevirir | Haftalik satis aksiyon plani |

Agent talimatlari `agents/`, kalici urun bilgisi `hafiza/`, ham pazar kanitlari `sinyaller/`, hedef firmalar `hesaplar/`, yonetici ozeti `ciktilar/` altindadir.

## Urun tezi

Ilk odak, zaten CAD veya 3D varligi bulunan mobilya, aydinlatma, banyo ve yapi urunu ureticileridir. ARVision bu firmalara sifirdan model uretmek yerine mevcut FBX, OBJ, STEP, STL ve benzeri varliklarini web ve mobil AR'a uygun kataloglara donusturme, yayinlama, paylasma ve olcme altyapisi satar.

Ilk teklif:

> Secilen 5 urunu 10 is gununde web ve mobil AR'da yayina alan, firmanin sitesine gomulen ve etkileşimi olcen ucretli katalog pilotu.

## Okuma sirasi

1. `hafiza/urun-envanteri-v38.md`
2. `sen/01-profil.md`
3. `sen/02-kaynaklar.md`
4. `format/kriterler.md`
5. `hesaplar/2026-07-21-hedef-hesaplar.md`
6. `ciktilar/2026-07-21-buyume-satis-raporu.md`

Bulut kurulumlari:

- Codex: `CODEX-CLOUD-KURULUM.md`
- Claude: `CLAUDE-KULLANIM-REHBERI.md`

## Degismez kurallar

- Yeni urun fikri, v38'deki mevcut yetenek ve somut satis engeliyle eslestirilmeden onerilmez.
- Sirket, kisi, unvan, e-posta veya olay uydurulmaz. Her hesapta kaynak URL ve kontrol tarihi bulunur.
- Kisisel e-posta tahmin edilmez. Yalnizca kamusal kurumsal iletisim kanallari kullanilir.
- Lead sayisi degil, dogru ICP ve gorusmeye donusebilecek neden onceliklidir.
- Her feature icin hedef hesap, cozecegi engel, mevcut temel, efor ve basari metrigi yazilir.
- Shopify'in kendi sundugu ozellikler tekrar urunlestirilmez; entegrasyon ancak ARVision'in katalog, CAD donusumu, QA veya analitik degerini tasiyorsa onerilir.
