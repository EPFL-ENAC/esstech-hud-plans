#!/usr/bin/env bash
SPIRULA_VERSION="v2026.10.16"
SPIRULA_ASSET="spirula-2026.10.16-ubuntu-vulkan-x86_64.zip"

set -euo pipefail

# Default logic for ROOT_DIR
DEFAULT_ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Use the first argument as EXTERNAL_DIR if provided, else use default
EXTERNAL_DIR="${1:-${DEFAULT_ROOT_DIR}/external}"

BIN_DIR="${EXTERNAL_DIR}/bin"

mkdir -p "${BIN_DIR}"

log() {
    echo "[install spirula] $1"
}

have() {
    command -v "$1" >/dev/null 2>&1
}

have curl || { log "curl is required"; exit 1; }
have unzip || { log "unzip is required"; exit 1; }

log "=========== Installing spirula ${SPIRULA_VERSION} ==========="
log "  BIN_DIR: ${BIN_DIR}"

download_dir="$(mktemp -d)"
trap 'rm -rf "${download_dir}"' EXIT

url="https://github.com/harry7557558/spirula-studio/releases/download/${SPIRULA_VERSION}/${SPIRULA_ASSET}"
log "Downloading ${url}"
curl -fsSL -o "${download_dir}/${SPIRULA_ASSET}" "${url}"

unzip -o -q "${download_dir}/${SPIRULA_ASSET}" -d "${download_dir}"
install -m 755 "${download_dir}/spirula" "${BIN_DIR}/spirula"

log "Installed ${BIN_DIR}/spirula"
log "spirula needs a Vulkan driver; on a headless NVIDIA machine the container image provides one."
