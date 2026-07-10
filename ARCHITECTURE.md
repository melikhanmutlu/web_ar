# ARVision Architecture

ARVision is a Flask-based 3D asset preparation, hosting, WebAR, and collaboration platform.

## Runtime

- Python 3.12, Flask, SQLAlchemy and Alembic
- PostgreSQL in production; SQLite for local development and tests
- Vanilla JavaScript and Google model-viewer
- A database-backed conversion queue with a separate worker process
- Node-based obj2gltf, gltfpack and glTF Transform tools
- FBX2glTF, Assimp, Trimesh and Blender conversion helpers

## Main request flow

1. `/upload_model` or the batch endpoint validates and stages the source asset.
2. A `ConversionJob` row is created with an owner or capability token.
3. `worker.py` atomically claims the job and updates its heartbeat and progress.
4. `ConversionService` converts, optimizes, normalizes and validates the GLB.
5. The model and initial version are committed.
6. Thumbnail and USDZ generation are queued as durable follow-up jobs.
7. The client polls the token-protected job endpoint and opens the viewer.

## Security boundaries

- `ModelAccessService` is the shared view and mutation policy.
- Anonymous mutations require an edit capability token.
- Private models require ownership, organization membership, or an active share link.
- Share grants are revalidated against revocation and expiration on every use.
- Browser write requests are protected by same-origin validation.
- Storage paths are resolved under configured roots by `StorageService`.
- Production metrics require a bearer token.

## Core services

- `services/model_access.py`: visibility and mutation authorization
- `services/storage.py`: storage-root containment
- `services/upload_staging.py`: direct and ZIP upload staging
- `services/conversion.py`: format dispatch and GLB post-processing
- `services/conversion_jobs.py`: job state, retry, progress and heartbeat
- `services/asset_quality.py`: model quality and budget reports
- `services/observability.py`: structured logging and optional telemetry

## Data ownership

Models may belong to an individual user and optionally an organization. Organization roles are owner, admin, editor and viewer. Versions, hotspots, share links, analytics, LODs, derived assets, likes and saves are deleted with their parent model.

## Deployment invariants

- `SECRET_KEY` is mandatory when `FLASK_ENV=production`.
- `flask db upgrade` must run before serving traffic.
- Production should set `JOB_QUEUE=true` and run `worker.py` alongside Gunicorn.
- Upload, converted, temporary and QR directories must use persistent storage where required.
- A shared `RATELIMIT_STORAGE_URI` is required when more than one web instance is used.
