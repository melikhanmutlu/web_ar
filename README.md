# ARVision

ARVision converts, optimizes, hosts and presents 3D models in the browser and mobile AR. It includes private sharing, organization roles, version history, annotations, LOD and derivative generation, analytics, API tokens and AI-assisted 3D generation.

## Requirements

- Python 3.12
- Node.js 20 or newer
- PostgreSQL for production
- FBX2glTF, Assimp and Blender for the full conversion feature set

## Local setup

```bash
python -m venv venv
pip install -r requirements.txt
npm ci
flask db upgrade
python app.py
```

Copy `.env.example` to `.env` and provide a development `SECRET_KEY`. Never use the example value in production.

To exercise the durable queue locally:

```bash
set JOB_QUEUE=true
python worker.py
```

Run the web process in a second terminal.

## Quality gates

```bash
python -m pytest -q
npm run lint
npm run security
npm run test:e2e
python -m pip_audit -r requirements.txt
python -m bandit -r services converters auth.py -ll
```

The test suite includes a real GLB upload and conversion happy path, access-policy regression tests, queue retry/heartbeat tests and desktop/mobile browser smoke tests.

## Production

- Set `FLASK_ENV=production` and a strong, unique `SECRET_KEY`.
- Set `DATABASE_URL` to PostgreSQL.
- Mount persistent storage and configure the `WEB_AR_*_DIR` variables.
- Set `JOB_QUEUE=true` and run `worker.py` as a separate process.
- Configure `METRICS_TOKEN` before exposing `/metrics` (enforced in every environment once set).
- Embeds: a model without an `embed_allowed_domains` allowlist is served with `frame-ancestors *` so it can be iframed anywhere — this is the intended default for public embeds. Set the per-model allowlist to restrict which sites may embed it.
- Use Redis through `RATELIMIT_STORAGE_URI` when running multiple web instances.
- Apply `flask db upgrade` before accepting traffic.
- Set `SMTP_HOST` (+ `SMTP_PORT`/`SMTP_USERNAME`/`SMTP_PASSWORD`/`SMTP_FROM_EMAIL`) to enable email notifications (conversion completed, share link created, org invite). Left unset, notifications are silently skipped — no dev/test SMTP server needed.

Railway/Nixpacks and Docker configurations are included. See [ARCHITECTURE.md](ARCHITECTURE.md) and [DEPLOYMENT.md](DEPLOYMENT.md) for additional details.
