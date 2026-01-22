# Use the latest Ubuntu LTS (Noble Numbat)
# (libmkl-full-dev package needed for COLMAP requires Ubuntu)
FROM ubuntu:24.04

# --------------------------------------------------
# Setup
# --------------------------------------------------

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV UV_VERSION=0.9.13

# We tell uv where to create the Python installations so they are persistent and predictable
ENV UV_PYTHON_INSTALL_DIR=/usr/local/share/uv-python


# --------------------------------------------------
# System tooling needed by install script
# --------------------------------------------------
# 1. Enable 'multiverse' repository (needed for libmkl-dev)
# 2. Update apt
# 3. Patch the script to use 'libmkl-dev' (Ubuntu name) instead of 'libmkl-full-dev'
RUN apt update && apt install -y software-properties-common && \
    add-apt-repository multiverse && \
    apt update && \
    apt install -y \
    curl \
    ca-certificates \
    git \
    build-essential \
	xvfb \
    && rm -rf /var/lib/apt/lists/*

# --------------------------------------------------
# Install uv
# --------------------------------------------------
ADD https://astral.sh/uv/${UV_VERSION}/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.cargo/bin/:/root/.local/bin/:$PATH"


WORKDIR /app

# --------------------------------------------------
# Install external native software (COLMAP, Brush, ffmpeg)
# --------------------------------------------------
COPY scripts /app/scripts

RUN /app/scripts/install_external_softwares.sh

# Make binaries available to Python
ENV PATH="/app/external/bin:${PATH}"



# --------------------------------------------------
# Application setup
# --------------------------------------------------
COPY uv.lock pyproject.toml /app/
COPY start.sh /app/
COPY api /app/api

# 1. 'uv python install' downloads the standalone python 3.13 binary
# 2. 'uv venv' creates the environment using that binary
# 3. 'uv sync' (or pip install) installs dependencies
RUN uv python install 3.13 && \
    uv venv .venv --python 3.13 && \
    uv pip install --no-cache-dir -e /app
ENV PATH="/app/.venv/bin:$PATH"


ENTRYPOINT ["sh", "start.sh"]
