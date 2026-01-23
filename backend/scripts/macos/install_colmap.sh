#!/usr/bin/env bash
set -euo pipefail


# Default logic for ROOT_DIR
DEFAULT_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Use the first argument as EXTERNAL_DIR if provided, else use default
EXTERNAL_DIR="${1:-${DEFAULT_ROOT_DIR}/external}"

BIN_DIR="${EXTERNAL_DIR}/bin"
SRC_DIR="${EXTERNAL_DIR}/src"
BUILD_DIR="${EXTERNAL_DIR}/build"

mkdir -p "${BIN_DIR}" "${SRC_DIR}" "${BUILD_DIR}"


log() {
    echo "[install COLMAP] $1"
}

have() {
    command -v "$1" >/dev/null 2>&1
}


welcome() {
    log "=========== Installing External COLMAP ==========="
    echo

    log "Configured paths:"
    log "  EXTERNAL_DIR: ${EXTERNAL_DIR}"
    log "  BIN_DIR:      ${BIN_DIR}"
    log "  SRC_DIR:      ${SRC_DIR}"
    log "  BUILD_DIR:    ${BUILD_DIR}"
    echo
    echo

    if ! have brew; then
        log "Homebrew not found, please install it first:"
        log "https://brew.sh"
        exit 1
    fi
}


install_prerequisite_colmap() {
    log "Installing COLMAP prerequisites"
    echo

    brew install \
        colmap \
        cmake \
        ninja \
        eigen \
        boost \
        ceres-solver \
        glew
}

build_colmap() {
    log "Nothing to build for COLMAP, using system package"
    echo
}

post_install_colmap() {
    log "Post-install COLMAP steps"
    echo

    ln -sf "$(brew --prefix)/bin/colmap" "${BIN_DIR}/colmap"
}


welcome
install_prerequisite_colmap
build_colmap
post_install_colmap

log "COLMAP installation completed successfully!"
