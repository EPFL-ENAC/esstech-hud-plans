#!/usr/bin/env bash
set -euo pipefail

log() {
    echo "[remove_build_deps] $1"
}

log "=========== Removing build dependencies ==========="

# Remove packages only needed for build, not runtime
apt-get purge -y \
    build-essential \
    cmake \
    ninja-build \
    pkg-config \
    git \
    software-properties-common \
    libboost-program-options-dev \
    libboost-graph-dev \
    libboost-system-dev \
    libeigen3-dev \
    libfreeimage-dev \
    libmetis-dev \
    libgoogle-glog-dev \
    libgtest-dev \
    libgmock-dev \
    libsqlite3-dev \
    libglew-dev \
    qt6-base-dev \
    libqt6opengl6-dev \
    libcgal-dev \
    libceres-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libblas-dev \
    liblapack-dev \
    libmkl-full-dev \
    libopenblas-openmp-dev \
    libopenblas-dev \
    libopenimageio-dev \
    openimageio-tools \
    libopenexr-dev \
    libopencv-dev

# Remove Rust toolchain (installed by Brush script)
if command -v rustup >/dev/null 2>&1; then
    log "Uninstalling Rust toolchain"
    rustup self uninstall -y || true
fi

# Remove unused dependencies and clean up
apt-get autoremove -y
apt-get clean
rm -rf /var/lib/apt/lists/*

log "Build dependencies removed."
