# Deploying ARVision

This is the single source of truth for deployment. The production target is
**Railway with Nixpacks** (`railway.json` + `nixpacks.toml`). A `Dockerfile`
mirrors the same runtime for platforms that build from a Dockerfile; its start
command is equivalent.

## What gets built

- Python 3.12 virtualenv (`/opt/venv`) from the hash-locked `requirements.txt`
  (`pip install -r requirements.txt` verifies hashes automatically). Edit
  `requirements.in` and re-lock; see the README, "Dependencies".
- Node 20: `npm ci --omit=dev` installs the converters used at runtime
  (`obj2gltf`, `gltfpack`, `@gltf-transform/cli`, `fbx2gltf`, `@google/model-viewer`, `three`).
  Dev-only packages (Playwright, Tailwind CLI) are not installed.
- System packages: Blender (USDZ export) and Assimp (FBX).
- The bundled `tools/FBX2glTF` binary.

## Start command (what happens on every deploy)

Defined in `nixpacks.toml` (`[start] cmd`), in this order:

1. `python scripts/heal_alembic.py` (best effort) repairs legacy Alembic state.
2. `flask db upgrade` with `SKIP_DB_BOOTSTRAP=1`. **Migrations fail fast**: if the
   upgrade fails the command prints `[FATAL] ...` and exits 1, so the container
   never serves traffic on a stale schema. Railway keeps the previous deployment
   running because the new one never becomes healthy.
3. `worker.py` is started in the background in a restart loop (`JOB_QUEUE=true`
   is exported for it and for gunicorn). It runs **in the same container** as the web process.
4. `exec gunicorn app:app --workers 1 --worker-class gthread --threads 8 --timeout 120`.
   Keep `--workers 1`: rate-limit counters are in-process (unless
   `RATELIMIT_STORAGE_URI` points to Redis) and background thumbnail/USDZ
   threads assume one process. Scale with threads, or move to Redis before adding workers.
   `exec` makes gunicorn PID 1 so a redeploy's SIGTERM triggers its graceful shutdown.

Worker shutdown and liveness: `worker.py` handles SIGTERM/SIGINT. It stops
claiming jobs and lets the current one finish; if it is still running after
`WORKER_SHUTDOWN_GRACE_SECONDS` (default 25) the job is put straight back in the
queue (the attempt is refunded) and the process exits. While a job runs, a
background thread refreshes the worker heartbeat and the job's
`last_heartbeat_at` every `WORKER_JOB_HEARTBEAT_SECONDS` (default 15), so
`/healthz` stays green on long conversions and the stale sweep does not
double-process them. On startup (and every minute) a `processing` job with no
live owner for `WORKER_ORPHAN_SECONDS` (default 60) is requeued immediately;
`WORKER_STALE_MINUTES` (default 30) remains the fallback. Because the worker
runs in the same container as gunicorn, a SIGTERM that only reaches PID 1 may
not reach it; the orphan sweep covers that case.

### Optional: separate worker service (later)

To scale conversions independently, add a second Railway service from the same
repo/image with start command `python worker.py` and the same environment
variables (`DATABASE_URL`, `SECRET_KEY`, `JOB_QUEUE=true`, storage settings) and
the same volume mounted at the same path (conversion outputs are read by the
web service). Then remove the background worker loop from the web service's
start command. Not required today.

## Health checks

`railway.json` sets `healthcheckPath` to **`/healthz/live`** (process is up,
no database access) with a 300 s timeout and restart on failure (max 10 retries).

| Endpoint | Purpose |
|---|---|
| `/healthz/live` | Liveness; used by Railway's deploy healthcheck. |
| `/healthz` | Readiness: database and storage writability; also worker count when `JOB_QUEUE=true`. 503 when degraded. |
| `/healthz/worker` | Worker heartbeat status. |
| `/metrics` | Prometheus-style gauges. Requires `Authorization: Bearer $METRICS_TOKEN` when the token is set or the deployment is production-like (`FLASK_ENV=production`, `RAILWAY_ENVIRONMENT` or `DATABASE_URL` set). |

## Storage: one volume

Railway allows **one volume per service**. Attach it (for example at `/data`);
Railway injects `RAILWAY_VOLUME_MOUNT_PATH` and the app stores `uploads/`,
`converted/`, `temp/` and `qr_codes/` underneath it (`config.py`).

- Do **not** set `WEB_AR_UPLOAD_DIR`, `WEB_AR_CONVERTED_DIR`, `WEB_AR_TEMP_DIR`,
  `WEB_AR_QR_DIR` or `STORAGE_ROOT` on Railway. They override the volume path, and
  relative values write to the container's ephemeral disk, losing every model on the next deploy.
- After the first deploy, `/healthz` reporting `"storage": "up"` confirms the volume is writable.

## Environment variables

Every variable the code reads is documented in [`.env.example`](../.env.example)
(a test fails if one is missing). The ones a production deploy needs:

| Variable | Notes |
|---|---|
| `SECRET_KEY` | **Required.** The app refuses to boot in production without it. |
| `APP_ENV` | `production`, `development` or `test`. Optional: when unset, production is inferred from `FLASK_ENV=production`, `RAILWAY_ENVIRONMENT` or `DATABASE_URL`, so existing deploys behave as before. When set it wins, e.g. `APP_ENV=development` lets a local checkout use a `DATABASE_URL` without Secure cookies or the `SECRET_KEY` requirement. Set `APP_ENV=production` explicitly on real deploys. |
| `SESSION_COOKIE_SECURE` | Optional override (`true`/`false`) of the Secure flag on session and remember cookies; defaults to on in production. Use `false` only to try a production-mode build over plain `http://localhost`. |
| `DATABASE_URL` | Provided by the Railway Postgres plugin. |
| `ADMIN_EMAILS` | Comma-separated emails promoted to admin on every boot. No built-in default, so without it there is no admin account. |
| `SITE_URL` | Canonical public URL (sitemap, canonical links, emails). |
| `METRICS_TOKEN` | Protects `/metrics`. |
| `PROXY_FIX_X_FOR` | Trusted reverse-proxy hops in front of the app (default `1`, right for Railway). Per-IP rate limits use the client IP from `X-Forwarded-For` that many hops from the right; set `0` when the app is exposed without a proxy, or the number of proxy layers otherwise. |
| `EMBED_DEFAULT_FRAME_ANCESTORS` | CSP `frame-ancestors` for `/embed/<id>` of models without an `embed_allowed_domains` allowlist (default `*`: embeddable anywhere). |
| `VIEW_DEDUPE_SECONDS` | One counted `/view` per visitor per model per this window (default `1800`). |
| `LOG_FORMAT=json` | Structured logs to stdout; Railway collects them. |
| `SENTRY_DSN` | Optional error tracking; release is taken from `RAILWAY_GIT_COMMIT_SHA`. |
| `MESHY_API_KEY`, `SMTP_*`, `PAYTR_*` / `LEMONSQUEEZY_*` | Optional features; see `.env.example`. |

Do not paste `.env.example` wholesale into the Railway "Raw Editor".

## Rollback

Redeploy the previous successful deployment from the Railway dashboard.
Migrations are forward-only: before shipping a migration that is not backward
compatible with the previous code, make it additive first and clean up in a later release.

## Backups

Neither the database nor the volume is backed up by this repository; configure both.

**PostgreSQL**

- Railway Postgres: enable the platform backups (service Backups tab, daily/weekly
  schedules) and test a restore into a scratch service.
- Independent logical backup (run from any machine with `pg_dump` 15+ and the
  public `DATABASE_URL` of the database):

  ```bash
  pg_dump --format=custom --no-owner --file "arvision-$(date +%F).dump" "$DATABASE_URL"
  # restore into an empty database:
  pg_restore --no-owner --dbname "$TARGET_DATABASE_URL" "arvision-YYYY-MM-DD.dump"
  ```

  Run it on a schedule (cron / GitHub Actions) and store the dumps off Railway.

**Volume (uploaded and converted models)**

- Enable Railway volume backups for the service volume if your plan offers them.
- Otherwise sync the volume to object storage on a schedule (for example
  `rclone sync "$RAILWAY_VOLUME_MOUNT_PATH" remote:arvision-backup`, run via a
  cron job or `railway run`). Converted files can be regenerated from the
  originals, so `uploads/` is the priority.
- Database and volume are only consistent together: back them up around the same time.

## Docker / other platforms

`docker build .` produces an image with the same runtime; its `CMD` runs the same
sequence (migrations first, worker loop, single gunicorn worker). Provide
`SECRET_KEY`, `DATABASE_URL` and a persistent volume exposed through
`STORAGE_ROOT` (the `RAILWAY_VOLUME_MOUNT_PATH` equivalent outside Railway).
