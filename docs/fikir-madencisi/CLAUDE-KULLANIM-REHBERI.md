# ARVision Growth OS'u Claude ile Calistirma

Bu rehber ayni Product Growth, Account Research ve Sales Ops sistemini Claude
Code, Claude web veya Claude Code GitHub Action ile calistirmak icindir.

## Ortak kural

Claude her gorevde repo kokundeki `CLAUDE.md` ve `AGENTS.md` dosyalarini,
ardindan ilgili Growth OS agent dosyasini okumali. Ciktilar mevcut ARVision
urunune dayanir; genel SaaS fikri uretilmez.

## Secenek A: Claude Code

1. Repoyu ac:

   ```bash
   git clone https://github.com/melikhanmutlu/web_ar.git
   cd web_ar
   git checkout main
   claude
   ```

2. Gunluk hesap arastirmasi icin:

   ```text
   .github/prompts/webar-sales-radar.md dosyasindaki gorevi calistir.
   Resmi ve guncel web kaynaklarini kullan. Yeni bulgulari once rapor olarak
   goster; onay almadan disariya mesaj gonderme veya dosya yayinlama.
   ```

3. Haftalik product-growth icin:

   ```text
   .github/prompts/webar-product-growth.md dosyasindaki gorevi calistir.
   Once kodu inceleyerek mevcut yetenekleri dogrula. En fazla uc feature sec.
   Kod yazma asamasina gecmeden once puan tablosunu ve MVP kapsamlarini goster.
   ```

4. Onaylanan feature'i gelistirmek icin:

   ```text
   Onaylanan feature: <feature>.
   Hedef hesaplar: <hesaplar>.
   Satis engeli: <engel>.
   Iki haftalik MVP ve kabul kriterleri icin Growth OS raporunu oku.
   Mevcut kod kaliplarina uyarak uygula, testleri ekle ve calistir.
   Ilgisiz degisiklik yapma. Commit veya push yapmadan once diff'i ozetle.
   ```

## Secenek B: Claude web

1. Bir Claude Project olustur.
2. Su dosyalari project knowledge olarak ekle:

   - `AGENTS.md`
   - `CLAUDE.md`
   - `docs/fikir-madencisi/README-WEBAR.md`
   - `docs/fikir-madencisi/hafiza/urun-envanteri-v38.md`
   - `docs/fikir-madencisi/sen/01-profil.md`
   - `docs/fikir-madencisi/sen/02-kaynaklar.md`
   - `docs/fikir-madencisi/format/kriterler.md`
   - `docs/fikir-madencisi/agents/` altindaki uc dosya

3. Project instruction:

   ```text
   You are the ARVision Growth OS. Improve and sell the existing ARVision
   product. Follow AGENTS.md and CLAUDE.md. Use current official web sources,
   separate evidence from inference, never fabricate contacts, and never send
   outreach without explicit approval. Score features and accounts with the
   repository criteria. Keep recommendations tied to a target account, sales
   blocker, two-week MVP and measurable outcome.
   ```

4. Gunluk ve haftalik promptlar icin `.github/prompts/` dosyalarini kullan.

Claude web repo kodunu her zaman guncel ve calistirilabilir bir checkout olarak
tutmaz. Kod degisikligi icin Claude Code veya GitHub Action tercih edilir.

## Secenek C: Claude Code GitHub Action

Resmi `anthropics/claude-code-action@v1` kullanilabilir.

### Bir kerelik kurulum

1. Repository admin hesabi ile Claude Code'da `/install-github-app` calistir
   veya GitHub'da resmi Claude app'i kur.
2. Repository secret olarak su seceneklerden birini ekle:
   - `ANTHROPIC_API_KEY`
   - `CLAUDE_CODE_OAUTH_TOKEN`
3. Daha ileri kurulumda Anthropic Workload Identity Federation kullanilarak
   statik API key yerine GitHub OIDC tercih edilebilir.

### Onerilen otomasyonlar

- Hafta ici cron: sales-radar promptunu calistir ve sonucu issue veya artifact
  olarak yaz.
- Pazartesi cron: product-growth promptunu calistir.
- Issue etiketi `claude-ready`: onaylanan feature icin branch ve degisiklik
  hazirla.
- Pull request: odakli test ve review calistir.

### Guvenlik

- Workflow permissions'i minimumda tut.
- Arastirma job'u icin `contents: read` yeterlidir.
- Branch/PR ureten job'a yalnizca gerekli yazma izinlerini ver.
- Fork PR'larinda secret bulunan workflow ile guvenilmeyen ref'i checkout etme.
- Claude'nun hazirladigi branch veya PR insan tarafindan incelenmeden merge
  edilmez.

## Claude icin hazir agent promptlari

### Account Research Agent

```text
Read AGENTS.md, CLAUDE.md and
docs/fikir-madencisi/agents/02-account-research-agent.md. Run the daily sales
radar from .github/prompts/webar-sales-radar.md. Use current official sources.
Return no more than ten qualified accounts with evidence, verification date,
pilot concept, target role, public corporate channel, score and next action.
Do not invent people or contact details. Do not send outreach.
```

### Product Growth Agent

```text
Read AGENTS.md, CLAUDE.md and
docs/fikir-madencisi/agents/01-product-growth-agent.md. Run
.github/prompts/webar-product-growth.md. Verify existing features in code.
Select no more than three revenue-adjacent features and define the target
accounts, blocker, current foundation, two-week MVP, acceptance criteria and
metric. Do not implement until the user approves the selected scope.
```

### Sales Ops Agent

```text
Read AGENTS.md, CLAUDE.md and
docs/fikir-madencisi/agents/03-sales-ops-agent.md. Use only qualified accounts.
For the top ten, prepare one evidence-based message angle, a five-product pilot,
the target role, public channel, discovery questions and two follow-ups. Do not
send messages or submit forms.
```

## Kaynaklar

- Claude Code Action: https://github.com/anthropics/claude-code-action
- Setup: https://github.com/anthropics/claude-code-action/blob/main/docs/setup.md
- Scheduled maintenance examples:
  https://github.com/anthropics/claude-code-action/blob/main/docs/solutions.md
