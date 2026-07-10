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

A Flask web app that converts uploaded 3D models (STL / FBX / OBJ → GLB / USDZ)
and serves them as AR experiences via Google `<model-viewer>` (Android Scene
Viewer + iOS Quick Look).

### Stack
- **Backend:** Flask 3 / Python 3.11, SQLAlchemy, Flask-Login, Flask-WTF, Flask-Migrate
- **DB:** PostgreSQL in production (`DATABASE_URL`), SQLite locally
- **Frontend:** Vanilla JS + Jinja2 templates, `<model-viewer>`, Tailwind
- **Conversion:** trimesh, pygltflib, `obj2gltf` (Node), `FBX2glTF` (binary in `tools/`)

### Key files
| Path | Role |
|------|------|
| `app.py` | Flask app, all routes, conversion pipeline (large — search before adding) |
| `config.py` | Config + storage paths (volume-aware) |
| `models.py` | SQLAlchemy models |
| `auth.py` | Login/register/logout blueprint |
| `converters/` | Per-format → GLB converters + `glb_optimizer` / `glb_quality` |
| `glb_modifier.py`, `mesh_slicer.py` | GLB transform / slicing |
| `version_manager.py` | Model version snapshots |
| `worker.py` | Background conversion queue (`JOB_QUEUE=true`) |
| `ai_generator.py` | Meshy AI text/image → 3D client (server-side only) |

### Run & test
- **Dev:** `python app.py` → http://localhost:5000
- **Prod:** gunicorn `app:app` + a `worker.py` process (see `nixpacks.toml`)
- **Tests:** `pytest` (suite in `tests/`)

### Project-specific guardrails
These reflect existing conventions — follow them, don't reinvent them:

- **Storage paths come from `config.py`** (`UPLOAD_FOLDER`, `CONVERTED_FOLDER`, …)
  and respect the Railway volume mount. Never hardcode `dirname`-relative paths.
- **CSRF is enabled app-wide** (Flask-WTF). The global `fetch` wrapper in
  `templates/_security_head.html` adds `X-CSRFToken` automatically; any new
  `<form>` POST needs `{{ csrf_token() }}` and any raw `XMLHttpRequest` needs
  the header set manually.
- **`SECRET_KEY` is required in production** — `config.py` refuses to boot
  without it. Keep it set in the deploy env.
- **Converters ingest untrusted uploads.** Sanitize any file path derived from
  model contents (`safe_join_within` / `assert_safe_obj_references` in
  `converters/`). Never honor absolute or `..` references from a model file.
- **Model mutation endpoints use `check_model_mutation_allowed(model_id)`** for
  the owner guard. Reuse it; don't write ad-hoc auth checks.
- **Escape untrusted strings before `innerHTML`** — use the shared
  `window.escapeHtml` (server-authored labels/comments are not trusted).
- **AI image inputs must be inline `data:` URIs**, never raw URLs (SSRF guard in
  `ai_generator.py`).
- Long-running 3D work belongs in the worker / background threads, not inline in
  a request handler where it can time out under concurrency.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer
rewrites due to overcomplication, and clarifying questions come before
implementation rather than after mistakes.
