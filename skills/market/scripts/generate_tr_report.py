#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Detaylı Türkçe pazarlama denetim raporu (ARVision)."""
import os
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch, mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                TableStyle, PageBreak, ListFlowable, ListItem)
from reportlab.graphics.shapes import Drawing, Rect, Circle, String
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# --- Türkçe destekli font ---
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FBB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
pdfmetrics.registerFont(TTFont("DJ", FB))
pdfmetrics.registerFont(TTFont("DJ-Bold", FBB))
REG, BOLD = "DJ", "DJ-Bold"

C = {
    "primary": HexColor("#1B2A4A"), "accent": HexColor("#2D5BFF"),
    "highlight": HexColor("#FF6B35"), "success": HexColor("#00C853"),
    "warning": HexColor("#FFB300"), "danger": HexColor("#FF1744"),
    "light": HexColor("#F5F7FA"), "text": HexColor("#2C3E50"),
    "muted": HexColor("#7F8C9B"), "border": HexColor("#E0E6ED"),
}

def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def scolor(s):
    return C["success"] if s >= 80 else C["accent"] if s >= 60 else C["warning"] if s >= 40 else C["danger"]

def gauge(score, size=120):
    d = Drawing(size + 20, size + 20)
    cx = cy = size / 2 + 10
    d.add(Circle(cx, cy, size / 2, fillColor=C["light"], strokeColor=C["border"], strokeWidth=2))
    d.add(Circle(cx, cy, size / 2 - 9, fillColor=scolor(score), strokeColor=None))
    d.add(Circle(cx, cy, size / 2 - 22, fillColor=white, strokeColor=None))
    d.add(String(cx, cy - 6, str(int(score)), fontSize=30, fillColor=C["primary"], textAnchor="middle", fontName=BOLD))
    d.add(String(cx, cy - 24, "/ 100", fontSize=10, fillColor=C["muted"], textAnchor="middle", fontName=REG))
    return d

def barchart(items, width=470):
    h = len(items) * 30 + 10
    d = Drawing(width, h)
    bx, maxw, bh = 175, width - 230, 18
    for i, (cat, sc) in enumerate(items):
        y = h - 25 - i * 30
        d.add(String(5, y + 4, cat, fontSize=9, fillColor=C["text"], fontName=REG))
        d.add(Rect(bx, y, maxw, bh, fillColor=C["light"], strokeColor=None))
        d.add(Rect(bx, y, (sc / 100) * maxw, bh, fillColor=scolor(sc), strokeColor=None))
        d.add(String(bx + maxw + 8, y + 4, str(int(sc)), fontSize=10, fillColor=C["text"], fontName=BOLD))
    return d

# ---------------- İçerik ----------------
URL = "https://webar.up.railway.app"
DATE = "13 Haziran 2026"
BRAND = "ARVision"
OVERALL = 48
GRADE = "D"

EXEC = ("ARVision, mükemmel ve sonuç odaklı bir ürün hikâyesine sahip "
        "(\"Bir model yükle. AR'a hazır bir link al.\") ama bu hikâye neredeyse "
        "hiç var olmayan bir pazarlama yüzeyiyle gölgeleniyor. Puanı aşağı çeken "
        "şey ürün değil; keşfedilebilirlik ve paylaşılabilirlik. Sitede meta "
        "description, Open Graph/Twitter kartı, yapısal veri (structured data), "
        "robots.txt ve sitemap yok. En kritiği: ürünün ana büyüme döngüsü AR model "
        "linklerini paylaşmak, ama paylaşılan sayfaların hiç sosyal önizlemesi yok — "
        "link WhatsApp/LinkedIn/X'te çıplak bir URL olarak görünüyor. Zengin link "
        "önizlemelerini (uygulamanın zaten ürettiği thumbnail'larla), SEO temelini ve "
        "bir güven/kullanım-senaryosu katmanını eklemek, paylaşım odaklı bir araç için "
        "huni-başı trafiğinde %20–50 artışın zeminini hazırlar. Skorun düşük olması bir "
        "startup için olağan: sorun üründe değil, pazarlama altyapısının henüz "
        "kurulmamış olmasında — ve maddelerin çoğu 1–2 günlük işler.")

CATS = [
    ("İçerik & Mesaj", 62, "25%"),
    ("Dönüşüm (CRO)", 58, "20%"),
    ("SEO & Keşfedilebilirlik", 28, "20%"),
    ("Rekabetçi Konumlanma", 45, "15%"),
    ("Marka & Güven", 40, "10%"),
    ("Büyüme & Strateji", 48, "10%"),
]

# Kategori başına derin analiz: (başlık, skor, [güçlü], [açık], özet)
ANALYSIS = [
    ("İçerik & Mesaj", 62,
     ["Hero başlığı 5 saniye testini rahat geçiyor: \"Bir model yükle. AR'a hazır link al.\" — eylemi ve kazanımı net söylüyor.",
      "AI bölümünün \"Anlat ya da göster — 3D model al\" ifadesi temiz, paralel bir kanca.",
      "Mikro-kopya düşünülmüş: \"STL/OBJ dosyaları birimsizdir — kaynak boyutu nasıl yorumlanacağını seç\" gibi notlar gerçek kullanıcı sürtünmesini azaltıyor."],
     ["Fayda/sonuç katmanı yok — bir AR linki kullanıcının işine ne katıyor, anlatılmıyor.",
      "Hiçbir yerde sosyal kanıt yok (sayaç, müşteri yorumu, logo).",
      "Özellik kartları fayda değil özellik odaklı (\"Çoklu Format\", \"Hızlı Dönüşüm\").",
      "Kullanım senaryosu çerçevesi yok; ziyaretçi kendini kendi nitelemek zorunda."],
     "Mesajın çekirdeği güçlü; eksik olan kanıt, fayda dili ve 'kim için' netliği. Bunlar kopya düzeltmeleriyle hızlı kapanır."),
    ("Dönüşüm (CRO)", 58,
     ["Tek ve net birincil aksiyon (sürükle-bırak yükleme).",
      "Format/boyut yönlendirmeleri akışın içinde veriliyor.",
      "AI akışı iyi sahnelenmiş (görsel önizle → seç → 3D üret)."],
     ["AI değeri, çıktısı gösterilmeden önce login arkasında kilitli (\"Üretmek için giriş yap\") — 'vay be' anı duvardan sonra yaşanıyor.",
      "Yükleme CTA'sının yanında güven sinyali yok (\"dosyalarınız gizli\", sayaç, garanti yok).",
      "Sonucu gösteren bir demo/GIF yok; \"AR'a hazır link\" tüm akış bitene kadar soyut kalıyor.",
      "Hazır olmayan ziyaretçi için ikincil CTA yok (örn. \"örnek gör\")."],
     "Akış temiz ama değeri kanıtlayan unsurlar ve login öncesi 'wow' eksik. Trust sinyali + demo + login duvarını geri çekmek dönüşümü artırır."),
    ("SEO & Keşfedilebilirlik", 28,
     ["model-viewer tabanlı temiz, modern bir teknik temel mevcut."],
     ["Hiçbir şablonda meta description yok.",
      "Hiçbir yerde Open Graph / Twitter kartı yok (tüm şablonlarda doğrulandı).",
      "JSON-LD / yapısal veri yok.",
      "robots.txt route'u yok, sitemap route'u yok.",
      "Ana sayfa başlığı jenerik: \"Home — arvision\".",
      "Herkese açık model sayfaları indeksleme/önizleme için optimize değil."],
     "Raporun en büyük açığı. Site hem arama motorlarına hem de link önizleyicilere neredeyse görünmez — paylaşım odaklı bir ürün için kritik. Hepsi birkaç küçük ekleme."),
    ("Rekabetçi Konumlanma", 45,
     ["Hero'daki \"saniyeler içinde çalışan AR linki, ücretsiz\" vaadi gerçek bir kama (wedge) içeriyor."],
     ["Farklılaşma mesajı, karşılaştırma/\"vs\" çerçevesi yok.",
      "Kategori tanımı yok: dönüştürücü mü, AR host mu, AI üretici mi belirsiz.",
      "Kimlik tek bir omurga olmadan üç işe bölünmüş.",
      "Üçüncü-taraf sitelerde itibar/değerlendirme varlığı görünmüyor."],
     "Gerçek avantaj (sürtünmesiz ücretsiz dönüşüm + yerleşik AI) hero'da var ama hiç savunulmuyor/karşılaştırılmıyor. Tek bir kategori seçip sahiplenmek gerekiyor."),
    ("Marka & Güven", 40,
     ["Sade, dağınık olmayan arayüz; mikro-kopya tonu tutarlı."],
     ["Hakkında/ekip/misyon sayfası yok.",
      "Müşteri yorumu, logo, vaka çalışması yok.",
      "Kullanıcılar (bazen tescilli) 3D varlık yüklerken hiçbir gizlilik/güven ifadesi yok.",
      "Marka ifadesi minimal (küçük harf 'arvision', öykü yok)."],
     "Yükleme temelli bir araç için güven ifadesinin tamamen yokluğu dönüşüm freni. Kayıtlı-kullanıcı geçmişi var ama fayda olarak çerçevelenmemiş."),
    ("Büyüme & Strateji", 48,
     ["Mimari güçlü bir viral döngü içeriyor: her dönüştürülen model bir paylaşılabilir link ve gömülebilir (embed) bir görüntüleyici."],
     ["Paylaşılan linklerin önizlemesi yok → döngü silahlandırılmamış.",
      "Herkese açık model galerisi yok.",
      "Embed atıfı (\"Powered by ARVision\") yok.",
      "Referans (referral) yok, e-posta onboarding yok (kayıtlı kullanıcı geçmişi zaten tutuluyor)."],
     "Latent döngü potansiyeli yüksek; önizleme + galeri + embed atıfı eklendiğinde gerçek dağıtıma dönüşür. AI üretimi güçlü bir kazanım kancası ama login arkasında saklı."),
]

FINDINGS = [
    ("Kritik", "Paylaşılan model sayfaları (/view/ID) ve /embed/ID rotasında Open Graph / Twitter kartı YOK. Ürünün ana döngüsü link paylaşımı, ama paylaşılan link WhatsApp/iMessage/LinkedIn/X'te görselsiz, başlıksız, thumbnail'sız görünüyor. Thumbnail'lar zaten üretiliyor (serve_thumbnail) ama sayfa head'ine bağlanmamış."),
    ("Kritik", "SEO temeli yok: tüm şablonlarda sıfır meta description, JSON-LD yapısal veri yok, robots.txt yok, sitemap yok. Ana sayfa başlığı jenerik ('Home — arvision'). Site arama motorlarına ve link önizleyicilere neredeyse görünmez."),
    ("Yüksek", "En güçlü kazanım kancası olan AI üretimi, kullanıcı örnek çıktıyı görmeden login arkasında kilitli ('Üretmek için giriş yap'). 'Wow' anı duvardan sonra yaşanıyor."),
    ("Yüksek", "Hiçbir yerde sosyal kanıt yok (dönüşüm sayacı, yorum, logo) ve tescilli 3D varlık yüklenmesine rağmen gizlilik/güven ifadesi yok."),
    ("Orta", "Bölünmüş kimlik: landing aynı anda üç ürün gibi okunuyor (format dönüştürücü + AR host + AI üretici), birleştirici kategori/farklılaşma çerçevesi yok."),
    ("Orta", "Özellik kartları fayda değil özellik odaklı ('Çoklu Format', 'Hızlı Dönüşüm') ve ziyaretçinin kendini nitelemesi için kullanım senaryosu çerçevesi yok."),
    ("Orta", "Büyüme döngüleri zayıf: herkese açık galeri yok, embed atıfı yok, referral yok, geçmişi zaten tutulan kayıtlı kullanıcılar için e-posta onboarding yok."),
    ("Düşük", "Minimal marka ifadesi (küçük harf logo; hakkında/ekip/misyon sayfası yok)."),
]

# Aksiyon: (madde, efor, etki, süre)
QUICK = [
    ("view.html ve embed.html'e Open Graph + Twitter kartı ekle; og:image olarak mevcut /thumbnail/ID, og:title olarak model adı, kısa bir açıklama kullan — her paylaşılan linki zengin önizlemeye çevirir.", "Düşük", "Yüksek", "1–2 gün"),
    ("Ana sayfa başlığını 'Home — arvision'dan 'ARVision — 3D modelleri paylaşılabilir AR linkine dönüştür'e değiştir; 150 karakterlik meta description ekle.", "Düşük", "Orta", "1 gün"),
    ("robots.txt ve sitemap route'larını ekle; arama motorları tarayabilsin, herkese açık model sayfaları keşfedilebilir olsun.", "Düşük", "Orta", "1 gün"),
    ("Markalı bir ana sayfa OG paylaşım görseli üret (kurulu web-asset-generator skill'i tam bunun için) ve index.html'de referansla.", "Düşük", "Orta", "0,5 gün"),
    ("Hero yakınında canlı sosyal-kanıt sayacı göster ('12.480 model dönüştürüldü') — veri zaten DB'de.", "Düşük", "Orta", "0,5 gün"),
    ("Hero altına 2–3 kullanım senaryosu satırı: 'E-ticaret ürün sayfaları · mimari & mobilya · sınıflar için.'", "Düşük", "Orta", "0,5 gün"),
]
MEDIUM = [
    ("Tek bir kategori seç ve sahiplen: tek bir işle öne çık ('ürününüzü AR'a koymanın en hızlı yolu'); dönüşüm ve AI'yı 'ne' değil 'nasıl' olarak çerçevele.", "Orta", "Yüksek", "1–2 hafta"),
    ("Herkese açık, opt-in model galerisi kur: indekslenebilir SEO yüzeyi + sosyal kanıt + referral yüzeyi; her paylaşılan model bir reklamdır.", "Orta", "Yüksek", "2–4 hafta"),
    ("E-posta onboarding dizisi kur (hoş geldin → ilk modelini yükle → AR linkini paylaş → AI üretimini dene).", "Orta", "Orta", "1–2 hafta"),
    ("Landing CRO turu: yükleme CTA'sı yanında güven sinyalleri, 10 saniyelik 'AR'a hazır link' demo GIF'i, ilk kullanıcı için daha basit format/boyut seçenekleri.", "Orta", "Orta", "1 hafta"),
]
STRAT = [
    ("Format derdine yönelik içerik/SEO hamlesi: 'STL/FBX/OBJ AR'da nasıl görüntülenir', 'OBJ to GLB dönüştürme', 'iPhone AR için USDZ' — ARVision'ın tam yaptığı işe denk gelen yüksek-niyetli, düşük-rekabetli aramalar.", "Yüksek", "Yüksek", "1–3 ay"),
    ("Paylaşım döngüsünü ürünleştir: 'Powered by ARVision' atıflı, cilalı gömülebilir AR görüntüleyici — her müşteri embed'i bir büyüme kanalı olur.", "Yüksek", "Yüksek", "1–2 ay"),
    ("Segment-özel landing sayfaları (e-ticaret / mimari / eğitim) — aynı dönüştürücü üzerinden, segmente özel kopya ve örneklerle.", "Yüksek", "Orta", "1–3 ay"),
]

IMPACT = [
    ("Paylaşılan linklerde OG/Twitter önizleme", "Yüksek (mevcut döngüyü güçlendirir)", "Yüksek", "1–2 gün"),
    ("Ana sayfa başlık + meta description + OG", "Orta (indekslenebilirlik/CTR)", "Yüksek", "1 gün"),
    ("robots.txt + sitemap", "Orta (zamanla bileşik etki)", "Orta", "1 gün"),
    ("Landing'e sosyal kanıt + kullanım senaryosu", "Orta (dönüşüm)", "Orta", "2–3 gün"),
    ("AI çıktısını login öncesi göster", "Orta (aktivasyon)", "Orta", "2–4 gün"),
    ("Herkese açık model galerisi", "Yüksek (uzun vade)", "Orta", "2–4 hafta"),
    ("E-posta onboarding dizisi", "Orta (aktivasyon/retention)", "Orta", "1–2 hafta"),
]

COMPET = [
    ["Faktör", "ARVision", "Sketchfab", "Vectary", "model-viewer (DIY)"],
    ["Başlık Netliği", "8/10", "7/10", "7/10", "—"],
    ["Değer Vaadi Gücü", "7/10", "8/10", "7/10", "—"],
    ["Güven Sinyalleri", "3/10", "9/10", "8/10", "—"],
    ["Link Önizlemeleri", "1/10", "9/10", "8/10", "2/10"],
    ["SEO Temeli", "2/10", "9/10", "8/10", "—"],
    ["AI Üretimi", "7/10", "4/10", "6/10", "0/10"],
    ["Ücretsiz/Sürtünmesiz", "8/10", "6/10", "5/10", "—"],
]

NEXT = [
    "Zengin link önizlemelerini yayına al (view + embed'e OG/Twitter, mevcut thumbnail ile) — tek en yüksek kaldıraçlı değişiklik.",
    "SEO temelini at (başlık, meta description, ana sayfa OG, robots, sitemap).",
    "Landing'e güven + kullanım senaryosu katmanı ekle ve AI sonucunu login duvarından önce göster.",
]

# ---------------- PDF kurulum ----------------
styles = getSampleStyleSheet()
def S(name, **kw):
    kw.setdefault("fontName", REG)
    kw.setdefault("textColor", C["text"])
    return ParagraphStyle(name, parent=styles["Normal"], **kw)
title = S("t", fontName=BOLD, fontSize=26, textColor=C["primary"], spaceAfter=4, leading=30)
sub = S("s", fontSize=12, textColor=C["muted"], spaceAfter=2)
h1 = S("h1", fontName=BOLD, fontSize=17, textColor=C["primary"], spaceBefore=16, spaceAfter=8, leading=20)
h2 = S("h2", fontName=BOLD, fontSize=12.5, textColor=C["accent"], spaceBefore=10, spaceAfter=4)
body = S("b", fontSize=9.7, leading=14, spaceAfter=5, alignment=TA_JUSTIFY)
bullet = S("bl", fontSize=9.3, leading=13)
small = S("sm", fontSize=8, textColor=C["muted"])

def bullets(items, color=None):
    return ListFlowable(
        [ListItem(Paragraph(esc(x), bullet), bulletColor=color or C["accent"]) for x in items],
        bulletType="bullet", start="•", leftIndent=14, spaceBefore=2, spaceAfter=6)

def th(style):
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), C["primary"]),
        ("TEXTCOLOR", (0, 0), (-1, 0), white),
        ("FONTNAME", (0, 0), (-1, 0), BOLD),
        ("FONTNAME", (0, 1), (-1, -1), REG),
        ("FONTSIZE", (0, 0), (-1, -1), 8.4),
        ("GRID", (0, 0), (-1, -1), 0.5, C["border"]),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [white, C["light"]]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ] + style)

E = []
# Kapak
E.append(Spacer(1, 0.7 * inch))
E.append(Paragraph("Pazarlama Denetim Raporu", title))
E.append(Paragraph(BRAND, sub))
E.append(Paragraph(URL + "  ·  " + DATE, sub))
E.append(Paragraph("İş tipi: SaaS / self-servis araç (3D→AR dönüştürücü + AI 3D üretimi)", sub))
E.append(Spacer(1, 0.3 * inch))
E.append(gauge(OVERALL))
E.append(Paragraph(f"Genel Pazarlama Skoru: {OVERALL}/100  (Not: {GRADE} — ortalama altı, hızlı düzeltilebilir)", h1))
E.append(Paragraph(esc(EXEC), body))
E.append(Spacer(1, 0.15 * inch))
E.append(Paragraph("Kapsam notu: Bu denetim, canlı host bu ortamdan erişilemediği için (egress allowlist) "
                   "frontend KAYNAK KODU üzerinden yapıldı. Mesaj, kopya, CTA, SEO/meta ve sosyal-paylaşım "
                   "hazırlığını yüksek güvenle kapsar; canlı sayfa hızı / Core Web Vitals dahil değildir.", small))
E.append(PageBreak())

# Skor dağılımı
E.append(Paragraph("Skor Dağılımı", h1))
E.append(barchart([(c[0], c[1]) for c in CATS]))
E.append(Spacer(1, 0.15 * inch))
rows = [["Kategori", "Skor", "Ağırlık", "Ağırlıklı", "Durum"]]
total = 0
for name, sc, w in CATS:
    wv = sc * float(w.strip("%")) / 100
    total += wv
    st = "Güçlü" if sc >= 75 else "İyileştir" if sc >= 50 else "Kritik"
    rows.append([name, f"{sc}/100", w, f"{wv:.1f}", st])
rows.append(["TOPLAM", "", "100%", f"{total:.0f}/100", f"Not {GRADE}"])
t = Table(rows, colWidths=[150, 55, 55, 65, 75])
t.setStyle(th([("FONTNAME", (0, -1), (-1, -1), BOLD), ("BACKGROUND", (0, -1), (-1, -1), C["light"]),
               ("ALIGN", (1, 0), (-1, -1), "CENTER")]))
E.append(t)
E.append(PageBreak())

# Kategori bazında detaylı analiz
E.append(Paragraph("Kategori Bazında Detaylı Analiz", h1))
for name, sc, strong, gaps, summ in ANALYSIS:
    E.append(Paragraph(f"{esc(name)} — {sc}/100", h2))
    E.append(Paragraph("<b>Güçlü yönler</b>", bullet))
    E.append(bullets(strong, C["success"]))
    E.append(Paragraph("<b>Açıklar</b>", bullet))
    E.append(bullets(gaps, C["danger"]))
    E.append(Paragraph("<b>Özet:</b> " + esc(summ), body))
E.append(PageBreak())

# Bulgular
E.append(Paragraph("Önemli Bulgular", h1))
sevcol = {"Kritik": C["danger"], "Yüksek": C["highlight"], "Orta": C["warning"], "Düşük": C["accent"]}
frows = [["Önem", "Bulgu"]]
for sev, txt in FINDINGS:
    frows.append([sev, Paragraph(esc(txt), bullet)])
ft = Table(frows, colWidths=[55, 415])
fcmd = [("ALIGN", (0, 0), (0, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP")]
for i, (sev, _) in enumerate(FINDINGS, 1):
    fcmd.append(("TEXTCOLOR", (0, i), (0, i), sevcol.get(sev, C["warning"])))
    fcmd.append(("FONTNAME", (0, i), (0, i), BOLD))
ft.setStyle(th(fcmd))
E.append(ft)
E.append(PageBreak())

# Aksiyon planı (efor/etki/süre tablolu)
E.append(Paragraph("Öncelikli Aksiyon Planı", h1))
def action_table(items):
    r = [["#", "Aksiyon", "Efor", "Etki", "Süre"]]
    for i, (txt, ef, et, sr) in enumerate(items, 1):
        r.append([str(i), Paragraph(esc(txt), bullet), ef, et, sr])
    tt = Table(r, colWidths=[18, 300, 50, 50, 52])
    tt.setStyle(th([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
                    ("ALIGN", (2, 0), (-1, -1), "CENTER")]))
    return tt
E.append(Paragraph("Hızlı Kazanımlar (Bu Hafta)", h2))
E.append(action_table(QUICK))
E.append(Spacer(1, 0.12 * inch))
E.append(Paragraph("Orta Vade (1–4 Hafta)", h2))
E.append(action_table(MEDIUM))
E.append(Spacer(1, 0.12 * inch))
E.append(Paragraph("Stratejik (1–3 Ay)", h2))
E.append(action_table(STRAT))
E.append(PageBreak())

# Gelir/etki tablosu
E.append(Paragraph("Gelir / Etki Özeti", h1))
E.append(Paragraph("Mutlak dolar rakamları, bu ortamdan canlı trafik/dönüşüm verisi alınamadığı için "
                   "verilmedi; etki seviyeleri paylaşım odaklı self-servis araçlardaki tipik artışları yansıtır.", small))
irows = [["Öneri", "Tahmini Etki", "Güven", "Süre"]]
for a, b, c, d in IMPACT:
    irows.append([Paragraph(esc(a), bullet), Paragraph(esc(b), bullet), c, d])
it = Table(irows, colWidths=[175, 165, 55, 75])
it.setStyle(th([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (2, 0), (-1, -1), "CENTER")]))
E.append(it)
E.append(Spacer(1, 0.2 * inch))

# Rakip karşılaştırma
E.append(Paragraph("Rekabet Manzarası (nitel — canlı doğrulanmalı)", h1))
ct = Table(COMPET, colWidths=[120, 80, 88, 80, 100])
ct.setStyle(th([("ALIGN", (1, 0), (-1, -1), "CENTER"), ("FONTNAME", (0, 1), (0, -1), BOLD)]))
E.append(ct)
E.append(Paragraph("ARVision'ın avantajı: sürtünmesiz ücretsiz dönüşüm + yerleşik AI üretimi. "
                   "Zayıflığı: rakiplerin standart kabul ettiği güven, SEO ve link-önizleme altyapısı.", small))
E.append(PageBreak())

# Sonraki adımlar + metodoloji
E.append(Paragraph("Sonraki Adımlar", h1))
E.append(bullets(NEXT))
E.append(Spacer(1, 0.1 * inch))
E.append(Paragraph("Takip komutları: /market copy (landing kopyasını yeniden yaz), /market landing (CRO turu), "
                   "/market competitors (tabloyu canlı doğrula), /market social (paylaşım-döngüsü içerik takvimi).", small))

E.append(Paragraph("Metodoloji", h1))
E.append(Paragraph("Bu denetim, pazarlama etkinliğinin altı boyutunu değerlendirir. Her kategori, sektör en iyi "
                   "uygulamalarına ve rakip kıyaslamalarına göre 0–100 puanlanır. Genel skor ağırlıklı ortalamadır.", body))
mrows = [["Kategori", "Ağırlık", "Ne Ölçülür"],
         ["İçerik & Mesaj", "25%", "Kopya kalitesi, değer vaadi netliği, CTA etkinliği"],
         ["Dönüşüm (CRO)", "20%", "Huni tasarımı, formlar, sosyal kanıt, sürtünme azaltma"],
         ["SEO & Keşfedilebilirlik", "20%", "Sayfa-içi & teknik SEO, içerik yapısı, meta/OG"],
         ["Rekabetçi Konumlanma", "15%", "Farklılaşma, fiyatlama, alternatif stratejisi"],
         ["Marka & Güven", "10%", "Tasarım kalitesi, güven sinyalleri, otorite"],
         ["Büyüme & Strateji", "10%", "Edinim kanalları, retention, büyüme döngüleri"]]
mt = Table(mrows, colWidths=[145, 50, 275])
mt.setStyle(th([]))
E.append(mt)
E.append(Spacer(1, 0.3 * inch))
E.append(Paragraph("AI Marketing Suite (Claude Code) tarafından üretildi · kaynak-tabanlı çalışma", small))

out = "/home/user/web_ar/PAZARLAMA-RAPORU-ARVision.pdf"
SimpleDocTemplate(out, pagesize=A4, rightMargin=42, leftMargin=42, topMargin=46, bottomMargin=42).build(E)
print("OK:", out)
