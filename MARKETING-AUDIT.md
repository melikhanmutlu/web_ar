# Marketing Audit: ARVision

**URL:** https://webar.up.railway.app (current; will change)
**Date:** 2026-06-13
**Business Type:** SaaS / Self-serve tool (3D→AR converter + AI 3D generation)
**Scope note:** This audit was run against the **frontend source** (`templates/`,
routes in `app.py`) because the live host is not reachable from the build
environment (egress allowlist). It therefore covers messaging, copy, CTAs,
SEO/meta, social-share readiness, and structure with high confidence, but does
**not** include live page-speed / Core Web Vitals / rendered-DOM metrics. Re-run
`/market audit` from a machine with open network for those.

**Overall Marketing Score: 48/100 (Grade: D — below average, fixable fast)**

---

## Executive Summary

ARVision has a **genuinely good product story trapped behind almost no marketing
surface.** The hero — *"Upload a model. Get an AR-ready link."* — is one of the
clearest value propositions a tool can have: concrete, outcome-focused, five-word
clarity. The AI path (*"Describe it or show it — get a 3D model"*) is a strong
second hook. The fundamentals of *what* and *for whom* are better than most
early-stage SaaS.

The score is dragged down almost entirely by **discoverability and shareability**,
not by the product or the core copy. There is no meta description, no Open Graph
or Twitter card, no structured data, no `robots.txt`, no sitemap, and the page
title is a generic *"Home — arvision."* Most damaging: ARVision's core growth loop
is **sharing AR model links**, yet shared model pages (`/view/<id>`) carry **zero
social preview** — paste a link in WhatsApp, iMessage, LinkedIn or X and it renders
as a bare URL with no image, no title, no thumbnail. The product literally
manufactures shareable links and then strips them of every reason to click. That
single gap is the highest-leverage fix in this report.

**Top 3 moves that would move the needle most:**
1. **Add Open Graph + Twitter cards to `/view/<id>` and `/embed/<id>`**, using the
   model thumbnail that the app *already generates* (`serve_thumbnail`). Turns every
   shared link into a rich preview → directly amplifies the existing viral loop.
2. **Add real SEO basics** — a descriptive `<title>`, meta description, OG tags on
   the homepage, `robots.txt` + a sitemap. Today the site is nearly invisible to
   search and link unfurlers.
3. **Add trust + outcome layer to the landing page** — one line of social proof
   ("X models converted"), 2–3 concrete use cases (e-commerce product, architecture,
   education), and surface the AI feature without forcing login before the value is
   shown.

Estimated impact of implementing the full list: **high relative lift** on a small
base (rich-preview share links + indexability typically lift top-of-funnel 20–50%
for share-driven tools), low absolute dollars until traffic grows — so treat these
as **foundation-laying**, not revenue-this-week.

---

## Score Breakdown

| Category | Score | Weight | Weighted | Key Finding |
|----------|-------|--------|----------|-------------|
| Content & Messaging | 62/100 | 25% | 15.5 | Excellent hero clarity; thin on benefits/proof/use-cases |
| Conversion Optimization | 58/100 | 20% | 11.6 | One clear primary CTA; AI value gated behind login, no trust signals |
| SEO & Discoverability | 28/100 | 20% | 5.6 | No meta description, OG, structured data, robots, or sitemap |
| Competitive Positioning | 45/100 | 15% | 6.75 | No differentiation/"vs"/category framing; identity split across 3 jobs |
| Brand & Trust | 40/100 | 10% | 4.0 | No about/testimonials/team; minimal brand expression |
| Growth & Strategy | 48/100 | 10% | 4.8 | Strong share-loop *potential*, crippled by missing link previews |
| **TOTAL** | | **100%** | **48/100** | |

---

## Quick Wins (This Week)

1. **Rich previews on shared model links** — add `<meta property="og:title|og:description|og:image">`
   and `twitter:card` to `templates/view.html` and `templates/embed.html`. Use the
   model's existing thumbnail (`/thumbnail/<id>`) as `og:image`. *Where:* `<head>` of
   both templates, populated from the model record. *Why:* the product's whole loop is
   link-sharing; previews are the difference between a click and a skip. *Impact: High.*
2. **Homepage `<title>` + meta description** — change `"Home — arvision"` to something
   like `"ARVision — Turn 3D models into shareable AR links"` and add a 150-char meta
   description with the value prop. *Where:* `templates/index.html` `<head>`. *Impact: Med.*
3. **Add `robots.txt` + `sitemap.xml` routes** — two tiny Flask routes. Without them,
   search engines have no crawl guidance and public model pages aren't discoverable.
   *Impact: Med (compounding).*
4. **OG image for the homepage** — a single branded share image (you already installed
   the `web-asset-generator` skill — use it). *Impact: Med.*
5. **Surface social proof** — even a simple live counter ("12,480 models converted")
   near the hero. The data is in the DB already. *Impact: Med.*
6. **Add 2–3 use-case lines under the hero** — "For e-commerce product pages · for
   architecture & furniture · for classrooms." Tells visitors *who it's for*. *Impact: Med.*
7. **Show the AI feature's output before the login wall** — currently "Sign in to
   start / Login to generate" gates the wow-moment. Show an example result first.
   *Impact: Med.*

## Strategic Recommendations (This Month)

1. **Pick and own a category.** The page currently reads as three tools at once
   (format converter + AR host + AI generator). Lead with one job ("the fastest way
   to put your product in AR") and frame the others as how, not what.
2. **Build a public gallery / showcase** of AR models (opt-in). It doubles as SEO
   surface area (indexable pages), social proof, and a referral surface — each shared
   model is an ad. Ties directly into the share-loop fix above.
3. **Email onboarding sequence** (you installed `market-emails` — use it): welcome →
   "upload your first model" → "share your AR link" → "try AI generation." Registered
   users already persist history; nurture them toward the aha moment.
4. **Landing-page CRO pass** (`/market landing`): add trust signals near the upload
   CTA, clarify "AR-ready link" with a 10-second demo GIF, reduce the perceived
   complexity of the format/size options for first-timers.

## Long-Term Initiatives (This Quarter)

1. **Content/SEO play around the format pain** — "how to view an STL/FBX/OBJ in AR",
   "convert OBJ to GLB", "USDZ for iPhone AR". High-intent, low-competition queries that
   match exactly what ARVision does. Each becomes an indexable landing page → the
   share-link gallery feeds the same engine.
2. **Productize the share loop** — embeddable AR viewer (`/embed` already exists) with a
   subtle "Powered by ARVision" → every embed on a customer site is a growth channel.
3. **Segment-specific landing pages** — /for-ecommerce, /for-architecture, /for-education
   with tailored copy and examples, driven off the same converter.

---

## Detailed Analysis by Category

### Content & Messaging — 62/100
**Strengths:** Hero passes the 5-second test cold: *"Upload a model. Get an AR-ready
link."* states the action and the payoff. The AI section's *"Describe it or show it —
get a 3D model"* is a clean parallel hook. Microcopy is thoughtful ("STL/OBJ files are
unitless — choose how to interpret the source size", "a single object on a clean
background works best") — it reduces real user friction.
**Gaps:** No outcome/benefit layer (what does an AR link *do* for the user's
business?). No social proof anywhere. Feature cards ("Multiple Formats", "Fast
Conversion") are feature-led, not benefit-led. No use-case framing → visitor must
self-qualify.

### Conversion Optimization — 58/100
**Strengths:** Single, obvious primary action (drag-drop upload). Format/size guidance
inline. Progressive AI flow (image preview → pick → build) is well-staged.
**Gaps:** The AI value is gated ("Login to generate") *before* showing what it
produces — the wow happens after the wall. No trust signals near the upload CTA (no
"your files are private", no count, no guarantee). No demo/GIF of the end result, so
"AR-ready link" is abstract until you complete the whole flow. No urgency or
secondary CTA for not-ready visitors (e.g., "see an example").

### SEO & Discoverability — 28/100  ⚠️ biggest gap
**Findings:** No meta description on any template. No Open Graph or Twitter card
anywhere (confirmed across all templates). No JSON-LD / structured data. No
`robots.txt` route, no `sitemap.xml` route. Homepage title is generic ("Home —
arvision"). Public model pages are not optimized for indexing or unfurling. Net: the
site is close to invisible to both search engines and social link previews — a
critical miss for a share-driven product.

### Competitive Positioning — 45/100
**Findings:** No differentiation messaging, no comparison/"vs" framing, no stated
category. The identity is split across converter / AR host / AI generator without a
unifying spine. Likely competitors (model-viewer-based hosts, <echoAR/Vectary-style
tools, Sketchfab for sharing) own clearer single-sentence positions. ARVision's real
wedge — "upload anything, get a working AR link in seconds, free" — is present in the
hero but never defended or contrasted.

### Brand & Trust — 40/100
**Findings:** Minimal brand expression (lowercase "arvision", no logo/mission/story).
No about page, no team, no testimonials, no logos. For a tool asking users to upload
their (sometimes proprietary) 3D assets, the absence of any privacy/trust statement is
a conversion drag. Registered-user history is mentioned but not framed as a benefit.

### Growth & Strategy — 48/100
**Findings:** The architecture *contains* a strong viral loop — every converted model
is a shareable link and an embeddable viewer — but it's not weaponized: shared links
have no preview, there's no public gallery, no referral, no embed attribution, no
email nurture. The AI generation feature is a strong acquisition hook but is hidden
behind login. Fixing previews + gallery + embed attribution would convert latent loop
potential into actual distribution.

---

## Competitor Comparison (qualitative — verify live)

| Factor | ARVision | Sketchfab | Vectary | model-viewer DIY |
|--------|----------|-----------|---------|------------------|
| Headline Clarity | 8/10 | 7/10 | 7/10 | n/a |
| Value Prop Strength | 7/10 | 8/10 | 7/10 | n/a |
| Trust Signals | 3/10 | 9/10 | 8/10 | n/a |
| Share Link Previews | 1/10 | 9/10 | 8/10 | 2/10 |
| SEO Foundation | 2/10 | 9/10 | 8/10 | n/a |
| AI Generation | 7/10 | 4/10 | 6/10 | 0/10 |
| Free / Frictionless | 8/10 | 6/10 | 5/10 | n/a |

*ARVision's edges: frictionless free conversion + built-in AI generation. Its
liabilities: trust, SEO, and share-preview infrastructure that competitors treat as
table stakes.*

---

## Revenue Impact Summary

| Recommendation | Est. Impact | Confidence | Timeline |
|---------------|-------------|------------|----------|
| OG/Twitter previews on shared links | High (amplifies existing share loop) | High | 1–2 days |
| Homepage title + meta description + OG | Medium (indexability/CTR) | High | 1 day |
| robots.txt + sitemap | Medium (compounding crawl) | Med | 1 day |
| Social proof + use-cases on landing | Medium (conversion) | Med | 2–3 days |
| Show AI output before login wall | Medium (activation) | Med | 2–4 days |
| Public model gallery (SEO + loop) | High (long-term) | Med | 2–4 weeks |
| Email onboarding sequence | Medium (activation/retention) | Med | 1–2 weeks |

*Absolute dollar figures omitted: no live traffic/conversion data is available from
this environment. Percentages reflect typical lifts for share-driven self-serve tools.*

---

## Next Steps

1. **Ship rich link previews** (OG/Twitter on `/view` + `/embed`, using the existing
   thumbnail) — single highest-leverage change.
2. **Lay the SEO foundation** (title, meta description, homepage OG, robots, sitemap).
3. **Add the trust + use-case layer** to the landing page, and reveal the AI result
   before the login wall.

Follow-up commands for deeper dives: `/market copy https://webar.up.railway.app`
(rewrite the landing copy), `/market landing` (CRO pass), `/market competitors`
(verify the table above live), `/market social` (build the share-loop content calendar).

*Generated by AI Marketing Suite — `/market audit` (source-based run)*
