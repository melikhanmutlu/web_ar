FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libstdc++6 \
    libgomp1 \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy package files
COPY requirements.txt package*.json ./
COPY tools ./tools

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Node dependencies
RUN npm ci

# Make FBX2glTF executable
RUN chmod +x tools/FBX2glTF

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Start command
CMD gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 300 --log-level info
