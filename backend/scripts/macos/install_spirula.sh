#!/usr/bin/env bash
SPIRULA_VERSION="v2026.10.16"
SPIRULA_ASSET="spirula-2026.10.16-macos-vulkan-arm64.dmg"

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

have curl || { log "curl is required"; exit 1; }
have hdiutil || { log "hdiutil is required"; exit 1; }

log "=========== Installing spirula ${SPIRULA_VERSION} ==========="
log "  BIN_DIR: ${BIN_DIR}"

download_dir="$(mktemp -d)"
trap 'rm -rf "${download_dir}"' EXIT

url="https://github.com/harry7557558/spirula-studio/releases/download/${SPIRULA_VERSION}/${SPIRULA_ASSET}"
log "Downloading ${url}"
curl -fsSL -o "${download_dir}/${SPIRULA_ASSET}" "${url}"

mount_dir="$(mktemp -d)"
hdiutil attach -nobrowse -readonly -mountpoint "${mount_dir}" "${download_dir}/${SPIRULA_ASSET}"
trap 'hdiutil detach "${mount_dir}" -force >/dev/null 2>&1 || true; rm -rf "${download_dir}"' EXIT

app_binary="$(find "${mount_dir}" -path "*.app/Contents/MacOS/spirula" -type f | head -n 1)"
if [ -z "${app_binary}" ]; then
    log "Could not find the spirula binary inside the disk image"
    exit 1
fi

install -m 755 "${app_binary}" "${BIN_DIR}/spirula"

log "Installed ${BIN_DIR}/spirula"
