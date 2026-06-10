#!/usr/bin/env bash
set -euo pipefail
BRUSH_VERSION="f043db463d7534c0a312f632447d19e0dcbad9d1"

# Default logic for ROOT_DIR
DEFAULT_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Use the first argument as EXTERNAL_DIR if provided, else use default
EXTERNAL_DIR="${1:-${DEFAULT_ROOT_DIR}/external}"

BIN_DIR="${EXTERNAL_DIR}/bin"
SRC_DIR="${EXTERNAL_DIR}/src"
BUILD_DIR="${EXTERNAL_DIR}/build"

mkdir -p "${BIN_DIR}" "${SRC_DIR}" "${BUILD_DIR}"


log() {
    echo "[install BRUSH] $1"
}

have() {
    command -v "$1" >/dev/null 2>&1
}


welcome() {
    log "=========== Installing Brush ==========="
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


install_prerequisite_brush() {
    log "Installing Brush prerequisites"
    echo

    if ! have cargo; then
        log "Installing Rust"
        curl https://sh.rustup.rs -sSf | sh -s -- -y
        source "$HOME/.cargo/env"
    fi
}

build_brush() {
    log "Building Brush from source"
    echo

    cd "${SRC_DIR}"
    git clone https://github.com/ArthurBrussee/brush.git || true
    cd brush
	git checkout ${BRUSH_VERSION}
    cargo build --release

    cp target/release/brush "${BIN_DIR}/"
}

post_install_brush() {
    log "Post-install Brush steps"
    echo

    rm -rf "${SRC_DIR}"
    rm -rf "${BUILD_DIR}"
}


welcome
install_prerequisite_brush
build_brush
post_install_brush

log "Brush installation completed successfully!"
