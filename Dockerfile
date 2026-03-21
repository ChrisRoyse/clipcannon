FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu22.04

LABEL maintainer="ClipCannon Team"
LABEL description="ClipCannon AI-native video editing MCP server"

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV HF_HOME=/root/.cache/huggingface

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    ffmpeg \
    libsm6 \
    libxext6 \
    libgl1 \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Use python3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

WORKDIR /app

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ src/
COPY config/ config/
COPY assets/ assets/

# Install core dependencies
RUN pip install --no-cache-dir -e .

# Install ML dependencies (separate layer for caching)
RUN pip install --no-cache-dir -e ".[ml]" || echo "ML deps install had issues - some models may not be available"

# Create clipcannon directories
RUN mkdir -p /root/.clipcannon/projects \
    /root/.clipcannon/models \
    /root/.clipcannon/tmp

# Copy default config
RUN cp config/default_config.json /root/.clipcannon/config.json

# Expose ports
# 3366 - MCP server (stdio, not a network port)
# 3100 - License server
# 3200 - Dashboard
EXPOSE 3100 3200

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:3200/health || exit 1

# Default: run all 3 services
COPY scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh || true

CMD ["python", "-m", "clipcannon.dashboard.app"]
