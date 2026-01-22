FROM python:3.13.6-bookworm
ENV UV_VERSION=0.9.13

# --------------------------------------------------
# System tooling needed by install script
# --------------------------------------------------
RUN apt-get update && apt-get install -y \
    curl \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------
# Python tooling
# --------------------------------------------------
RUN pip install "uv==$UV_VERSION"

WORKDIR /app

# --------------------------------------------------
# Install external native software (COLMAP, Brush, ffmpeg)
# --------------------------------------------------
COPY scripts /app/scripts
RUN chmod +x /app/scripts/install_external_softwares.sh && \
    /app/scripts/install_external_softwares.sh

# Make binaries available to Python
ENV PATH="/app/external/bin:${PATH}"

COPY uv.lock pyproject.toml /app/
COPY start.sh /app/
COPY api /app/api
COPY data /app/data

RUN uv pip install --system --no-cache-dir -e /app

ENTRYPOINT ["sh", "start.sh"]
