#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ARVision Rekabetçi İstihbarat Raporu - Türkçe PDF."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak, ListFlowable, ListItem, Preformatted)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

pdfmetrics.registerFont(TTFont("DJ", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DJ-Bold", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DJ-Mono", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"))
REG, BOLD, MONO = "DJ", "DJ-Bold", "DJ-Mono"

C = {"primary": HexColor("#1B2A4A"), "accent": HexColor("#2D5BFF"), "highlight": HexColor("#FF6B35"),
     "success": HexColor("#00C853"), "warning": HexColor("#FFB300"), "danger": HexColor("#FF1744"),
     "light": HexColor("#F5F7FA"), "text": HexColor("#2C3E50"), "muted": HexColor("#7F8C9B"),
     "border": HexColor("#E0E6ED")}

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

st = getSampleStyleSheet()
def S(n, **kw):
    kw.setdefault("fontName", REG); kw.setdefault("textColor", C["text"])
    return ParagraphStyle(n, parent=st["Normal"], **kw)
title = S("t", fontName=BOLD, fontSize=24, textColor=C["primary"], leading=28, spaceAfter=4)
sub = S("s", fontSize=11, textColor=C["muted"], spaceAfter=2)
h1 = S("h1", fontName=BOLD, fontSize=16, textColor=C["primary"], spaceBefore=15, spaceAfter=7, leading=19)
h2 = S("h2", fontName=BOLD, fontSize=12, textColor=C["accent"], spaceBefore=9, spaceAfter=3)
body = S("b", fontSize=9.6, leading=14, spaceAfter=5, alignment=TA_JUSTIFY)
bl = S("bl", fontSize=9.2, leading=12.5)
small = S("sm", fontSize=8, textColor=C["muted"], leading=11)
mono = S("mono", fontName=MONO, fontSize=7.6, leading=9.5, textColor=C["text"])

def bullets(items, color):
    return ListFlowable([ListItem(Paragraph(esc(x), bl), bulletColor=color) for x in items],
                        bulletType="bullet", start="•", leftIndent=13, spaceBefore=1, spaceAfter=5)

def THS(extra):
    return TableStyle([("BACKGROUND", (0, 0), (-1, 0), C["primary"]), ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), BOLD), ("FONTNAME", (0, 1), (-1, -1), REG),
        ("FONTSIZE", (0, 0), (-1, -1), 8.2), ("GRID", (0, 0), (-1, -1), 0.5, C["border"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C["light"]]), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5)] + extra)
def tbl(data, widths, extra=None, wrapcols=None):
    if wrapcols:
        data = [[Paragraph(esc(c), bl) if (j in wrapcols and r > 0) else c for j, c in enumerate(row)]
                for r, row in enumerate(data)]
    t = Table(data, colWidths=widths); t.setStyle(THS(extra or [])); return t

E = []
# Kapak
E.append(Spacer(1, 0.5 * inch))
E.append(Paragraph("Rekabetçi İstihbarat Raporu", title))
E.append(Paragraph("ARVision · https://webar.up.railway.app · 13 Haziran 2026", sub))
E.append(Paragraph("Analiz edilen rakip: 8 (4 doğrudan · 2 dolaylı · 2 aspirasyonel)", sub))
E.append(Paragraph("Rekabetçi Konum: Zayıf–Orta", S("pos", fontName=BOLD, fontSize=13, textColor=C["warning"], spaceBefore=8, spaceAfter=8)))
E.append(Paragraph("Yönetici Özeti", h1))
for p in [
 "ARVision, \"herhangi bir 3D dosyasını yükle → saniyeler içinde çalışan, paylaşılabilir bir AR linki al\" kamasıyla net bir boşluğa oturuyor; üstüne yerleşik AI 3D üretimi (Meshy backend'i) ekleyerek çoğu AR-görüntüleyici rakibinin sunmadığı bir kanca sağlıyor. Sürtünmesiz + ücretsiz + AI'lı bu kombinasyon gerçek bir farklılaşma potansiyeli.",
 "Ne var ki rakipler — özellikle kategori lideri Sketchfab ve tasarım-odaklı Vectary — pazarlamanın masa-payı saydığı her şeyi kurmuş: zengin link önizlemeleri, derin SEO, sosyal kanıt, topluluk ve vs/alternatif sayfaları. ARVision bunların neredeyse hiçbirine sahip değil (MARKETING-AUDIT skoru 48/100). Yani üründe rekabetçi ama pazarlama yüzeyinde görünmez.",
 "Ek risk: AI üretiminde ARVision, tedarikçisi Meshy'nin (ve Tripo/Luma'nın) doğrudan tüketiciye sunduğu ürünle dolaylı rekabet hâlinde. Bu katmanda savunulabilir değer AI değil, \"üretilen modeli anında AR'a hazır paylaşılabilir linke çevirme\" kolaylığı — ve bu mesaj hiç vurgulanmıyor.",
 "En kritik 3 öneri: (1) Paylaşım döngüsünü silahlandır (link önizleme + galeri). (2) Tek kategori sahiplen + vs Sketchfab/vs Meshy sayfaları. (3) Güven katmanı ekle (gizlilik, sosyal kanıt, şeffaf fiyat).",
]:
    E.append(Paragraph(esc(p), body))
E.append(Paragraph("Veri kaynağı uyarısı: Rakip siteleri ve G2/Capterra, çalışma ortamının egress kısıtı nedeniyle CANLI çekilemedi. Profiller eğitim bilgisine (Ocak 2026) ve ARVision frontend kaynağına dayanır. Kesin fiyat/takipçi/puanlar ≈/doğrula ile işaretlidir; yayın öncesi canlı doğrulanmalıdır.", small))
E.append(PageBreak())

# Rakip genel görünümü
E.append(Paragraph("Rakip Genel Görünümü", h1))
E.append(Paragraph("Doğrudan Rakipler", h2))
E.append(tbl([["Rakip", "Konumlanma", "Fiyat (≈)", "Ana Farklılaştırıcı"],
  ["Sketchfab (Epic)", "3D yayınla & paylaş — kategori lideri", "Ücretsiz + $15–60/ay", "Devasa topluluk, kusursuz paylaşım/embed, SEO"],
  ["Vectary", "Tarayıcıda 3D/AR tasarım & paylaşım", "Ücretsiz + $12–40/ay", "Tarayıcı-içi tasarım editörü + AR"],
  ["echo3D", "3D/AR için içerik yönetimi + CDN", "Ücretsiz + kullanım", "Backend/CDN, API-öncelikli"],
  ["Augment/Plattar/Threekit", "E-ticaret/perakende ürün AR'ı", "Kurumsal/Custom", "Ticaret entegrasyonu, konfigüratör"]],
  [108, 150, 80, 150], wrapcols={1, 3}))
E.append(Paragraph("Dolaylı Rakipler", h2))
E.append(tbl([["Rakip", "Konumlanma", "Not"],
  ["Meshy / Tripo / Luma AI", "Metin/görsel → 3D (AI)", "ARVision'ın AI tedarikçisi VE DTC rakibi; AR-link katmanı yok"],
  ["Google model-viewer", "Açık kaynak AR web bileşeni", "Ücretsiz/DIY; hosting/dönüşüm/paylaşım yok — ARVision'ın işleri"]],
  [120, 130, 238], wrapcols={1, 2}))
E.append(Paragraph("Aspirasyonel Rakipler", h2))
E.append(tbl([["Rakip", "Neden aspirasyonel"],
  ["Sketchfab", "Paylaşım/topluluk/SEO'da olunmak istenen yer"],
  ["Shopify AR / Adobe Aero", "Ticaret/yetkilendirme ölçeğinde AR'ı normalleştiren oyuncular"]],
  [140, 348], wrapcols={1}))
E.append(PageBreak())

# Profiller
E.append(Paragraph("Detaylı Rakip Profilleri", h1))
profiles = [
 ("Sketchfab (doğrudan, kategori lideri)",
  ["Güçlü: milyonlarca model + topluluk (ağ etkisi); kusursuz zengin link önizleme + embed; derin SEO (her model indekslenebilir sayfa); native + WebAR."],
  ["Zayıf: AI üretimi zayıf/yok; yeni kullanıcıya akış ARVision kadar hafif değil; topluluk odağı hızlı 'ürünümü AR'a koyayım' niyetinden uzaklaşabilir.",
   "ARVision fırsatı: AI boşluğu + ağır arayüz, 'hafif + AI'lı' konuma alan açar."]),
 ("Vectary (doğrudan)",
  ["Güçlü: güçlü tarayıcı-içi editör, şablonlar, AR önizleme, iyi SEO/eğitim içeriği."],
  ["Zayıf: editör öğrenme eğrisi; 'var olan dosyamı hızlı AR'a çevir' niyeti için ağır.",
   "ARVision fırsatı: 'tasarlama, sadece yükle/üret ve paylaş' sadeliği."]),
 ("Meshy / Tripo / Luma AI (dolaylı, AI 3D üretimi)",
  ["Güçlü: üretim kalitesi/hızı; ARVision'ın AI özelliği zaten Meshy'ye dayanıyor."],
  ["Zayıf: çıktıyı 'AR'a hazır, paylaşılabilir, telefonda çalışan link'e çevirme katmanı yok; iOS USDZ/QR kurulumunu kullanıcı yapmak zorunda.",
   "ARVision'ın asıl savunulabilir değeri burada: 'üret → anında AR linki'.",
   "TEHDİT: Meshy bu katmanı kendisi eklerse AI tarafındaki ayrım zayıflar."]),
 ("Google model-viewer (dolaylı, DIY)",
  ["Güçlü: ücretsiz, Google destekli, geliştirici benimsemesi."],
  ["Zayıf: hosting, dönüşüm (FBX/OBJ/STL→GLB/USDZ), paylaşım, QR yok — hepsi ARVision'ın hazır sunduğu işler.",
   "ARVision fırsatı: 'model-viewer'ı kendin kurma; biz dönüşüm+hosting+link veriyoruz.'"]),
]
for name, strong, gaps in profiles:
    E.append(Paragraph(esc(name), h2))
    E.append(bullets(strong, C["success"]))
    E.append(bullets(gaps, C["danger"]))
E.append(PageBreak())

# Özellik & fiyat
E.append(Paragraph("Karşılaştırma Tabloları", h1))
E.append(Paragraph("Özellik Karşılaştırması", h2))
feat = [["Özellik", "ARVision", "Sketchfab", "Vectary", "model-viewer"],
 ["FBX/OBJ/STL→GLB dönüşümü", "Tam", "Kısmi", "Kısmi", "Yok"],
 ["iOS Quick Look (USDZ)", "Tam", "Tam", "Tam", "Kısmi"],
 ["Paylaşılabilir link", "Tam", "Tam", "Tam", "Yok"],
 ["Zengin link önizleme (OG)", "YOK", "Tam", "Tam", "Yok"],
 ["Embed görüntüleyici", "Tam", "Tam", "Tam", "Tam (DIY)"],
 ["Metin/görsel→3D (AI)", "Tam", "Yok", "Kısmi", "Yok"],
 ["Herkese açık galeri/topluluk", "YOK", "Tam", "Kısmi", "Yok"],
 ["Sosyal kanıt/yorum", "YOK", "Tam", "Kısmi", "—"]]
E.append(tbl(feat, [165, 70, 75, 65, 95], [("ALIGN", (1, 0), (-1, -1), "CENTER")]))
E.append(Paragraph("ARVision moat'ları: dönüşüm genişliği + yerleşik AI + sürtünmesiz ücretsiz akış. Açıkları: link önizleme, galeri/topluluk, güven sinyalleri.", small))
E.append(Paragraph("Fiyatlama (≈ — canlı doğrula)", h2))
E.append(tbl([["Plan", "ARVision", "Sketchfab", "Vectary"],
 ["Ücretsiz plan", "Evet (AI limitli)", "Evet", "Evet"],
 ["Başlangıç", "— (belirsiz)", "≈ $15/ay", "≈ $12/ay"],
 ["Pro", "—", "≈ $60/ay", "≈ $40/ay"],
 ["Fiyat şeffaflığı", "Fiyat sayfası YOK", "Şeffaf", "Şeffaf"]],
 [120, 130, 120, 118], [("ALIGN", (1, 0), (-1, -1), "CENTER")]))
E.append(Paragraph("Konumlanma Haritası", h2))
E.append(Preformatted(
"""                    PREMIUM / KURUMSAL
                           |
         Plattar/Threekit  |  Adobe Aero / Shopify AR
                           |
   Vectary                 |
BASİT ─────────────────────┼───────────────────── GÜÇLÜ/DERİN
   ARVision (+AI, hafif)    |  Sketchfab · echo3D
                           |  Meshy/Tripo (AI)
                    ÜCRETSİZ / HAFİF""", mono))
E.append(Paragraph("ARVision 'basit + ücretsiz + AI' çeyreğinde yalnız — savunulması ve iletişimi gereken değerli bir konum.", small))
E.append(PageBreak())

# SEO boşlukları + SWOT
E.append(Paragraph("İçerik & SEO Boşluk Analizi", h1))
E.append(bullets([
 "\"STL/FBX/OBJ AR'da nasıl görüntülenir\" — yüksek niyet, düşük rekabet",
 "\"OBJ to GLB / FBX to GLB dönüştürme\" — yüksek niyet (ARVision'ın tam işi)",
 "\"iPhone için USDZ AR\" — orta-yüksek niyet",
 "\"Sketchfab/Vectary alternatifi\" — bottom-of-funnel, hiç yok",
 "Herkese açık örnek model galerisi (indekslenebilir yüzey) — kritik boşluk"], C["accent"]))
E.append(Paragraph("SWOT — ARVision", h1))
sw = [["Güçlü (S)", "Zayıf (W)"],
 ["Net hero vaadi; geniş format dönüşümü; yerleşik AI; sürtünmesiz ücretsiz akış; iOS+Android AR + embed hazır.",
  "Sıfır link önizleme/OG; SEO temeli yok; sosyal kanıt/güven yok; fiyat/konum belirsiz; galeri yok; AI login arkasında."],
 ["Fırsatlar (O)", "Tehditler (T)"],
 ["'En hızlı ürün→AR linki' kategorisini sahiplenmek; vs Sketchfab/vs Meshy sayfaları; format-derdi SEO; embed atıflı viral döngü.",
  "Sketchfab'ın topluluk/SEO ağ etkisi; Meshy/Tripo'nun AI'ya 'paylaşım' eklemesi; Shopify/Adobe'nin AR'ı platforma gömmesi."]]
swt = Table([[Paragraph("<b>"+esc(sw[0][0])+"</b>", bl), Paragraph("<b>"+esc(sw[0][1])+"</b>", bl)],
             [Paragraph(esc(sw[1][0]), bl), Paragraph(esc(sw[1][1]), bl)],
             [Paragraph("<b>"+esc(sw[2][0])+"</b>", bl), Paragraph("<b>"+esc(sw[2][1])+"</b>", bl)],
             [Paragraph(esc(sw[3][0]), bl), Paragraph(esc(sw[3][1]), bl)]], colWidths=[244, 244])
swt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, C["border"]), ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("BACKGROUND", (0, 0), (0, 0), HexColor("#E8F8EE")), ("BACKGROUND", (1, 0), (1, 0), HexColor("#FDEAEA")),
    ("BACKGROUND", (0, 2), (0, 2), HexColor("#E8F0FE")), ("BACKGROUND", (1, 2), (1, 2), HexColor("#FFF4E0")),
    ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6)]))
E.append(swt)
E.append(PageBreak())

# Stratejik öneriler
E.append(Paragraph("Stratejik Öneriler", h1))
E.append(Paragraph("Çalınmaya Değer Taktikler", h2))
E.append(tbl([["#", "Taktik (kaynak → ARVision'a)", "Efor", "Etki"],
 ["1", "Sketchfab: zengin link önizleme + her modele indekslenebilir sayfa (view/embed OG, mevcut thumbnail).", "Düşük", "Yüksek"],
 ["2", "Sketchfab/Vectary: herkese açık galeri/topluluk (sosyal kanıt + SEO + döngü).", "Orta", "Yüksek"],
 ["3", "Vectary: eğitim/tutorial içeriği (yüksek-niyetli SEO trafiği).", "Orta", "Orta-Yük."],
 ["4", "Sketchfab: şeffaf, değer-önce fiyatlandırma sayfası.", "Düşük", "Orta"],
 ["5", "Meshy: AI çıktısının canlı örneğini login öncesi göster.", "Orta", "Orta-Yük."],
 ["6", "Genel: embed'de 'Powered by ARVision' atfı (her embed bir kanal).", "Düşük", "Orta"]],
 [16, 332, 60, 64], [("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
                     ("ALIGN", (2, 0), (-1, -1), "CENTER")], wrapcols={1}))
E.append(Paragraph("Farklılaşma Stratejisi", h2))
E.append(bullets([
 "Kategori: 'Herhangi bir 3D dosyasını (ya da AI promptunu) saniyeler içinde telefonlarda çalışan, paylaşılabilir AR linkine çeviren en hızlı yol.'",
 "Özellik: tek üründe dönüşüm + AI üretim + AR hosting + paylaşım — rakipler yalnız bir-iki parçayı veriyor.",
 "Felsefe: 'tasarlama/öğrenme yok — yükle/üret, paylaş.'"], C["accent"]))
E.append(Paragraph("Oluşturulacak 'Alternatif' Sayfaları", h2))
E.append(bullets([
 "ARVision vs Sketchfab (/vs/sketchfab): 'Topluluk değil, hızlı AR linki mi arıyorsun?' — hız/ücretsizlik/AI/format kazanır; topluluk ölçeği kaybeder (dürüst).",
 "ARVision vs Meshy (/vs/meshy): 'AI ile üret — sonra? ARVision onu anında AR-linke çevirir.' — üret→AR→paylaş tek akış; USDZ/QR otomatik.",
 "model-viewer kurmadan AR (/alternatives/model-viewer): 'kendin host etme; dönüşüm+hosting+link hazır gelsin.'"], C["highlight"]))
E.append(Paragraph("Geçiş Anlatısı (Meshy/Tripo → ARVision)", h2))
E.append(Paragraph(esc("Neden geçilir: üretilen modeli AR'a hazırlama zahmeti, iOS USDZ/QR kurulum derdi, tek paylaşılabilir link ihtiyacı. Teklif: AI ile üretilenler için ücretsiz AR-link + ilk N üretim hediyesi."), body))
E.append(PageBreak())

# İzleme + sonraki adımlar
E.append(Paragraph("Rekabetçi İzleme Planı", h1))
E.append(tbl([["Rakip Hamlesi", "Yanıt Stratejisi", "Süre"],
 ["Fiyat indirimi", "Değer/kaliteyi vurgula, fiyat savaşına girme", "1 hafta"],
 ["Yeni özellik", "Alaka değerlendir, yol haritasını müşteriye ilet", "2 hafta"],
 ["AI sağlayıcı 'AR paylaşım' eklerse", "'üret→AR→paylaş tek akış' mesajını derinleştir", "1-2 hafta"],
 ["Negatif karşılaştırma içeriği", "Olgusal, dengeli karşılaştırma sayfası yayınla", "1 hafta"]],
 [150, 250, 88], wrapcols={1}))
E.append(Paragraph("İzleme: Sketchfab/Vectary/Meshy için Google Alerts; rakip fiyat sayfaları aylık; G2/Capterra üç ayda bir (canlı); Meshy/Tripo'nun 'AR paylaşım' eklemesini izle (en büyük tehdit).", small))
E.append(Paragraph("Sonraki Adımlar", h1))
E.append(bullets([
 "Paylaşım döngüsünü silahlandır — link önizleme (view/embed OG) + herkese açık galeri. Rakiplerin en güçlü, ARVision'ın en zayıf alanı.",
 "'vs Sketchfab' ve 'vs Meshy' alternatif sayfalarını kur — bottom-of-funnel arama trafiğini yakala, farklılaşmayı netleştir.",
 "Güven + fiyat netliği ekle — gizlilik ifadesi, sosyal kanıt, şeffaf fiyat sayfası."], C["success"]))
E.append(Spacer(1, 0.25 * inch))
E.append(Paragraph("AI Marketing Suite (Claude Code) — /market competitors · kaynak + bilgi-tabanlı çalışma", small))

out = "/home/user/web_ar/REKABET-RAPORU-ARVision.pdf"
SimpleDocTemplate(out, pagesize=A4, rightMargin=40, leftMargin=40, topMargin=44, bottomMargin=40).build(E)
print("OK:", out)
