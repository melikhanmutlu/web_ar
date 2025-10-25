#!/bin/bash
# Railway startup script

# Set default port if not provided
PORT=${PORT:-8080}

echo "Starting ARVision on port $PORT..."

# Start gunicorn
exec gunicorn app:app \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --threads 4 \
    --timeout 300 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
