#!/usr/bin/env bash
set -euo pipefail

# Default logic for ROOT_DIR
DEFAULT_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Use the first argument as EXTERNAL_DIR if provided, else use default
EXTERNAL_DIR="${1:-${DEFAULT_ROOT_DIR}/external}"

BIN_DIR="${EXTERNAL_DIR}/bin"
SRC_DIR="${EXTERNAL_DIR}/src"
BUILD_DIR="${EXTERNAL_DIR}/build"

if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
else
  SUDO=""
fi

# Detect Architecture
ARCH="$(uname -m)"

mkdir -p "${BIN_DIR}" "${SRC_DIR}" "${BUILD_DIR}"


log() {
    echo "[install COLMAP] $1"
}

welcome() {
    log "=========== Installing COLMAP ==========="
    echo

    log "Configured paths:"
    log "  EXTERNAL_DIR: ${EXTERNAL_DIR}"
    log "  BIN_DIR:      ${BIN_DIR}"
    log "  SRC_DIR:      ${SRC_DIR}"
    log "  BUILD_DIR:    ${BUILD_DIR}"
    echo
    echo
}

install_prerequisite_colmap() {
    log "Installing COLMAP prerequisites"
    echo

    # Define architecture-specific BLAS library
    if [ "$ARCH" = "x86_64" ]; then
        log "Architecture is x86_64: Using Intel MKL"
        BLAS_DEV="libmkl-full-dev"
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
        log "Architecture is ARM64: Using OpenBLAS"
        BLAS_DEV="libopenblas-openmp-dev" # see : https://github.com/facebookresearch/faiss/wiki/Troubleshooting#surprising-faiss-openmp-and-openblas-interaction and https://github.com/colmap/colmap/issues/3928
    else
        log "Unknown architecture: Defaulting to OpenBLAS"
        BLAS_DEV="libopenblas-dev"
    fi

    $SUDO apt install -y \
        git cmake ninja-build build-essential pkg-config curl \
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
        libqt6openglwidgets6 \
        libcgal-dev \
        libceres-dev \
        libcurl4-openssl-dev \
        libssl-dev \
        libblas-dev \
        liblapack-dev \
        "$BLAS_DEV" \
        libopenimageio-dev \
        openimageio-tools \
        libopenexr-dev \
		libopencv-dev
        # libsuitesparse-dev \
        # suitesparse-mongoose \
}

build_colmap() {
    log "Building COLMAP from source"
    echo

    if [ "$ARCH" = "x86_64" ]; then
        BLAS_CMAKE_FLAG="-DBLA_VENDOR=Intel10_64lp"
    else
        # ARM/OpenBLAS
        BLAS_CMAKE_FLAG="-DBLA_VENDOR=OpenBLAS"
    fi

    cd "${SRC_DIR}"
    git clone https://github.com/colmap/colmap.git || true
    mkdir -p "${BUILD_DIR}/colmap"
    cd "${BUILD_DIR}/colmap"

    log "Configuring COLMAP with CMake"
    cmake "${SRC_DIR}/colmap" \
        -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        "${BLAS_CMAKE_FLAG}" \
        -DCMAKE_INSTALL_PREFIX="${EXTERNAL_DIR}"

    log "Building and installing COLMAP with ninja"
    ninja -j 4 -v

    log "Installing COLMAP to ${EXTERNAL_DIR} with ninja install"
    ninja install
}

post_install_colmap() {
    log "Post-install COLMAP steps"
    echo

    rm -rf "${SRC_DIR}"
    rm -rf "${BUILD_DIR}"
}

welcome
install_prerequisite_colmap
build_colmap
post_install_colmap

log "COLMAP installation completed successfully!"
