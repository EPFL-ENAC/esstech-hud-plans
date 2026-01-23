# Use the latest Ubuntu LTS (Noble Numbat)
# (libmkl-full-dev package needed for COLMAP requires Ubuntu)
FROM ubuntu:24.04

# --------------------------------------------------
# Setup
# --------------------------------------------------

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive
ENV UV_VERSION=0.9.13
ENV UV_PYTHON_INSTALL_DIR=/usr/local/share/uv-python
ENV PYTHON_VERSION=3.13.11

WORKDIR /app

# --------------------------------------------------
# System tooling needed by install script
# --------------------------------------------------
# Enable 'multiverse' repository (needed for libmkl-dev)
RUN apt update && \
	apt install -y software-properties-common && \
    add-apt-repository multiverse && \
    apt update && \
    apt install -y \
    curl \
    ca-certificates \
    git \
    build-essential \
	xvfb

# --------------------------------------------------
# Install external native software (COLMAP, Brush, ffmpeg)
# --------------------------------------------------
COPY scripts/linux/install_ffmpeg.sh /app/scripts/install_ffmpeg.sh
RUN /app/scripts/install_ffmpeg.sh

COPY scripts/linux/install_colmap.sh /app/scripts/install_colmap.sh
RUN /app/scripts/install_colmap.sh

COPY scripts/linux/install_brush.sh /app/scripts/install_brush.sh
RUN /app/scripts/install_brush.sh

COPY scripts/linux/remove_build_dependencies.sh /app/scripts/remove_build_dependencies.sh
RUN /app/scripts/remove_build_dependencies.sh

# Make binaries available to Python
ENV PATH="/app/external/bin:${PATH}"

# --------------------------------------------------
# Install uv
# --------------------------------------------------
ADD https://astral.sh/uv/${UV_VERSION}/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.cargo/bin/:/root/.local/bin/:$PATH"

# --------------------------------------------------
# Application setup
# --------------------------------------------------
COPY uv.lock pyproject.toml /app/

RUN uv python install ${PYTHON_VERSION} && \
    uv venv .venv --python ${PYTHON_VERSION} && \
    uv pip install --no-cache-dir -e /app

COPY start.sh /app/
COPY api /app/api

ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["sh", "start.sh"]
