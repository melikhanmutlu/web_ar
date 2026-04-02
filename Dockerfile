# Use an official Python 3.11 runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# Set work directory
WORKDIR /app

# Install system dependencies
# blender, libassimp-dev, nodejs, npm
RUN apt-get update && apt-get install -y --no-install-recommends \
    blender \
    libassimp-dev \
    curl \
    && curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for caching
COPY requirements.txt .
RUN python -m venv /opt/venv
RUN /opt/venv/bin/pip install --upgrade pip
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Install Node.js dependencies
COPY package*.json ./
RUN npm ci --only=production

# Copy project files
COPY . .

# Ensure tools are executable
RUN chmod +x /app/tools/FBX2glTF

# Set Environment Variables for runtime
ENV PATH="/opt/venv/bin:$PATH"
# Standard location for libassimp on debian-slim is /usr/lib/x86_64-linux-gnu/
ENV LD_LIBRARY_PATH="/usr/lib/x86_64-linux-gnu:$LD_LIBRARY_PATH"

# Default port
EXPOSE 8080

# Start command
# We use the find command for assimp just in case, but usually static path works. 
# Re-using the logic from nixpacks for reliability
CMD chmod +x /app/tools/FBX2glTF && \
    export ASSIMP_PATH=$(find /usr/lib -name libassimp.so* | head -n 1 | xargs dirname) && \
    export LD_LIBRARY_PATH="$LD_LIBRARY_PATH:$ASSIMP_PATH" && \
    gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 300 --log-level info
