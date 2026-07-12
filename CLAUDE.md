# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes, adapted from
[andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills).
The behavioral section is general; the project section grounds it in this
codebase (ARVision — a Flask + model-viewer Web AR platform).

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

## Project: ARVision

A Flask web app that converts uploaded 3D models (STL / FBX / OBJ / STEP → GLB /
USDZ), hosts them, and serves them as AR experiences via Google
`<model-viewer>` (Android Scene Viewer + iOS Quick Look). It also does
AI text/image → 3D (Meshy), model editing, versioning, hotspots, sharing,
organizations, and analytics.

### Stack
- **Backend:** Flask 3 / Python 3.12, SQLAlchemy, Flask-Login, Flask-WTF,
  Flask-Migrate (Alembic), Flask-Limiter.
- **DB:** PostgreSQL in production (`DATABASE_URL`), SQLite locally & in tests.
- **Frontend:** Vanilla JS + Jinja2 templates, `<model-viewer>`, Tailwind
  (prebuilt CSS — see `rebuild_css.py`), some A-Frame for the VR page.
- **Conversion:** trimesh, pygltflib, shapely/scipy/networkx; Node
  `obj2gltf` / `gltfpack` / `@gltf-transform/cli`; `FBX2glTF` (binary in
  `tools/`); Blender & Assimp (via nixpacks) for USDZ / STEP.

### Architecture (this changed — read this before editing `app.py`)
Routes are **not** in `app.py` anymore. `app.py` is the app factory: config,
extensions, ~24 `register_blueprint(...)` calls, `before/after_request` hooks,
error handlers, security headers, and a large body of **shared conversion
helpers** (thumbnail/USDZ/QR/GLB pipeline) that blueprints and `worker.py`
import. When adding an endpoint, add it to the relevant blueprint, not `app.py`.

- **`blueprints/`** — all HTTP routes, one module per domain
  (`upload.py`, `viewer.py`, `models_crud.py`, `model_editing.py`,
  `model_geometry.py`, `versions.py`, `hotspots.py`, `sharing.py`,
  `organizations.py`, `ai_generation.py`, `ai_image.py`,
  `engagement.py`, `discover.py`, `scenes.py`, `webhooks.py`, `seo.py`,
  `health.py`, `api_tokens.py`, `material_presets.py`, `main.py`, …).
- **`services/`** — business logic / policy layer imported by blueprints and the
  worker. Notable: `model_access.py` (`ModelAccessService` — the single view &
  mutation policy), `model_permissions.py` (`check_model_mutation_allowed`),
  `storage.py` (`StorageService` root-containment), `conversion.py`
  (`ConversionService`), `conversion_jobs.py` (job state/retry/heartbeat),
  `upload_staging.py`, `asset_quality.py`, `observability.py` (JSON logging),
  `webhooks.py`, `email.py`, `storage_quota.py`, `plans.py`.
- **`converters/`** — per-format → GLB (`stl_converter`, `obj_converter`,
  `fbx_converter` + `fbx_*` helpers, `step_converter`) plus `glb_optimizer`,
  `glb_quality`, `lod_generator`, `texture_upscale`, `thumbnail_render`, and
  `base_converter` (path-safety helpers).
- **`admin.py`** — admin dashboard blueprint (`/admin`), Jinja + small fetch POSTs.
- **`models.py`** — ~29 SQLAlchemy models (`User`, `UserModel`, `Folder`,
  `Organization*`, `ModelVersion`, `ModelLOD`, `ModelHotspot`, `ModelShareLink`,
  `ConversionJob`, `AIGenerationJob`, `SiteSetting`, …).
- **`worker.py`** — background conversion queue (`JOB_QUEUE=true`): claims
  `ConversionJob` rows, heartbeats, requeues stale jobs, reconciles AI jobs.
- **`glb_modifier.py`, `mesh_slicer.py`, `version_manager.py`** — GLB transform,
  slicing, and version snapshots.
- **`ai_generator.py`** — Meshy AI text/image → 3D client (server-side only).
- **`config.py`** — config + volume-aware storage paths.
- **`auth.py`** — login/register/logout blueprint.

### Run & test
- **Dev:** `python app.py` → http://localhost:5000
- **Prod:** `gunicorn app:app` + a `worker.py` process; migrations run on boot
  (`flask db upgrade`). See `nixpacks.toml` / `Dockerfile` / `RAILWAY_DEPLOYMENT.md`.
- **Tests:** `pytest` (suite in `tests/`, `pytest.ini` sets `pythonpath=.`;
  `conftest.py` points the app at a throwaway SQLite DB). E2E: Playwright
  (`npm run test:e2e`) — Chromium is preinstalled, do not run `playwright install`.
- **Lint/checks:** `npm run lint` (`node --check` on JS + `scripts/check_inline_js.py`),
  `npm run check` (`py_compile`). CI (`.github/workflows/ci.yml`) runs pytest,
  `pip-audit`, `bandit`, and the Playwright job.

### Project-specific guardrails
These reflect existing conventions — follow them, don't reinvent them:

- **Add routes to a blueprint, not `app.py`.** Reuse `services/` for policy and
  the shared conversion helpers in `app.py`; don't duplicate them.
- **Storage paths come from `config.py`** (`UPLOAD_FOLDER`, `CONVERTED_FOLDER`, …)
  and respect the Railway volume mount. Resolve/contain paths via
  `StorageService`. Never hardcode `dirname`-relative paths.
- **CSRF is enabled app-wide** (Flask-WTF). The global `fetch` wrapper in
  `templates/_security_head.html` adds `X-CSRFToken` automatically; any new
  `<form>` POST needs `{{ csrf_token() }}` and any raw `XMLHttpRequest` needs
  the header set manually.
- **`SECRET_KEY` is required in production** — `config.py` refuses to boot
  without it. Keep it set in the deploy env.
- **Converters ingest untrusted uploads.** Sanitize any file path derived from
  model contents (`safe_join_within` / `assert_safe_obj_references` in
  `converters/`). Never honor absolute or `..` references from a model file.
- **Mutation endpoints use `check_model_mutation_allowed(model_id)`**
  (`services/model_permissions.py`); view/access decisions go through
  `ModelAccessService`. Reuse them; don't write ad-hoc auth checks. Anonymous
  mutations require an edit capability token; private models require ownership,
  org membership, or an active (non-revoked, non-expired) share link.
- **Escape untrusted strings before `innerHTML`** — use the shared
  `window.escapeHtml` (server-authored labels/comments are not trusted).
- **AI image inputs must be inline `data:` URIs**, never raw URLs (SSRF guard in
  `ai_generator.py`); webhook targets are also SSRF/DNS-rebinding guarded.
- **Long-running 3D work belongs in the worker / background threads**, not inline
  in a request handler where it can time out under concurrency.
- **DB schema changes need an Alembic migration** in `migrations/versions/`
  (`flask db migrate`); migrations apply on deploy before traffic is served.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer
rewrites due to overcomplication, and clarifying questions come before
implementation rather than after mistakes.
