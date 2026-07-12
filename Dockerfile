# Mirrors nixpacks.toml (used by Railway) so platforms that build from a
# Dockerfile instead of Nixpacks (e.g. Outplane) get the same runtime:
# Python + Node 20 (obj2gltf/gltfpack) + Blender (USDZ export) + assimp (FBX).
FROM python:3.11-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    blender \
    libassimp-dev \
    assimp-utils \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY package*.json ./
RUN npm ci

COPY . .

RUN chmod +x tools/FBX2glTF

ENV JOB_QUEUE=true

ENV FLASK_APP=app.py

# `exec` on the final gunicorn command replaces this shell as PID 1 so a
# container stop's SIGTERM reaches gunicorn directly (see nixpacks.toml).
# SKIP_DB_BOOTSTRAP=1 is scoped to just the `flask db upgrade` line (matching
# nixpacks.toml) -- it must NOT be a container-wide ENV: that also disabled
# app.py's create_all/stamp-on-boot fallback for the gunicorn process itself
# (breaking fresh/legacy DBs whenever `flask db upgrade` fails) and the
# ADMIN_EMAILS promotion, leaving no admin account on a Dockerfile deploy.
CMD export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:/usr/local/lib:/usr/lib:$(dirname "$(find /usr/lib -name 'libassimp.so*' 2>/dev/null | head -n 1)")" && \
    (python scripts/heal_alembic.py || true) && \
    (SKIP_DB_BOOTSTRAP=1 flask db upgrade || echo "[FATAL] flask db upgrade failed -- deploying anyway on the assumption stamp-on-boot will handle a legacy DB, but if alembic_version already exists this means the schema is now STALE relative to the code. Check logs above for the real error." >&2) && \
    (while true; do python worker.py; echo "worker exited, restarting in 3s"; sleep 3; done &) && \
    exec gunicorn app:app --bind 0.0.0.0:${PORT:-5000} --workers 1 --worker-class gthread --threads 8 --timeout 120 --log-level info
