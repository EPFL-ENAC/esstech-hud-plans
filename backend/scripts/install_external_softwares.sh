#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTERNAL_DIR="${ROOT_DIR}/external"
BIN_DIR="${EXTERNAL_DIR}/bin"
SRC_DIR="${EXTERNAL_DIR}/src"
BUILD_DIR="${EXTERNAL_DIR}/build"

if command -v sudo >/dev/null 2>&1 && [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
else
  SUDO=""
fi

mkdir -p "${BIN_DIR}" "${SRC_DIR}" "${BUILD_DIR}"

log() {
    echo "[install] $1"
}

have() {
    command -v "$1" >/dev/null 2>&1
}

OS="$(uname -s)"

# --------------------------------------------------
# Linux
# --------------------------------------------------
install_linux() {
    log "Detected Linux"

    $SUDO apt-get update
    $SUDO apt-get install -y \
        git cmake ninja-build build-essential pkg-config curl \
        ffmpeg \
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
        libmkl-full-dev \
        libopenimageio-dev \
        openimageio-tools \
        libopenexr-dev \
		libopencv-dev

    # ---- COLMAP ----
    if [ ! -x "${BIN_DIR}/colmap" ]; then
        log "Building COLMAP from source"
        cd "${SRC_DIR}"
        git clone https://github.com/colmap/colmap.git || true
        mkdir -p "${BUILD_DIR}/colmap"
        cd "${BUILD_DIR}/colmap"
        cmake "${SRC_DIR}/colmap" \
            -GNinja \
            -DCMAKE_BUILD_TYPE=Release \
            -DBLA_VENDOR=Intel10_64lp \
            -DCMAKE_INSTALL_PREFIX="${EXTERNAL_DIR}"
        ninja
        ninja install
    fi
}

# --------------------------------------------------
# macOS
# --------------------------------------------------
install_macos() {
    log "Detected macOS"

    if ! have brew; then
        log "Homebrew not found, please install it first:"
        log "https://brew.sh"
        exit 1
    fi

    brew install \
        colmap \
        ffmpeg \
        cmake \
        ninja \
        eigen \
        boost \
        ceres-solver \
        glew

    ln -sf "$(brew --prefix)/bin/colmap" "${BIN_DIR}/colmap"
    ln -sf "$(brew --prefix)/bin/ffmpeg" "${BIN_DIR}/ffmpeg"
}

# --------------------------------------------------
# Windows (Git Bash / MSYS2 / WSL)
# --------------------------------------------------
install_windows() {
    log "Detected Windows"

    # ffmpeg
    if [ ! -x "${BIN_DIR}/ffmpeg.exe" ]; then
        log "Downloading ffmpeg"
        curl -L \
            https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip \
            -o ffmpeg.zip
        unzip ffmpeg.zip
        cp ffmpeg-*/bin/ffmpeg.exe "${BIN_DIR}"
    fi

    # COLMAP
    if [ ! -x "${BIN_DIR}/colmap.exe" ]; then
        log "Downloading COLMAP"
        curl -L \
            https://github.com/colmap/colmap/releases/latest/download/COLMAP-windows.zip \
            -o colmap.zip
        unzip colmap.zip
        cp COLMAP*/bin/colmap.exe "${BIN_DIR}"
    fi
}

# --------------------------------------------------
# Brush (Rust, all platforms)
# --------------------------------------------------
install_brush() {
    if have brush; then
        log "Brush already installed"
        return
    fi

    if ! have cargo; then
        log "Installing Rust"
        curl https://sh.rustup.rs -sSf | sh -s -- -y
        source "$HOME/.cargo/env"
    fi

    cd "${SRC_DIR}"
    git clone https://github.com/ArthurBrussee/brush.git || true
    cd brush
    cargo build --release

    # copy brush.exe if it exists, otherwise copy brush
    if [ -x "target/release/brush.exe" ]; then
        cp target/release/brush.exe "${BIN_DIR}/"
    else
        cp target/release/brush "${BIN_DIR}/"
    fi
}

# --------------------------------------------------
# Cleanup
# --------------------------------------------------
cleanup() {
    rm -rf "${SRC_DIR}"
    rm -rf "${BUILD_DIR}"
}

# --------------------------------------------------
# Dispatch
# --------------------------------------------------
case "${OS}" in
    Linux*) install_linux ;;
    Darwin*) install_macos ;;
    MINGW*|MSYS*|CYGWIN*) install_windows ;;
    *)
        log "Unsupported OS: ${OS}"
        exit 1
    ;;
esac

install_brush
cleanup

log "✅ External software installed"
