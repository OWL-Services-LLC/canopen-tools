#!/usr/bin/env bash
#
# Copyright (C) 2025 - OWL Services LLC
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License (version 2) as published by the
# FSF - Free Software Foundation
#

set -euo pipefail

APP_NAME="OpenEDSEditor"
APP_VERSION="0.8"
ZIP_NAME="OpenEDSEditor0.8.zip"

# Installation directories (user-space, no root needed for binaries)
INSTALL_DIR="${HOME}/.local/share/${APP_NAME}-${APP_VERSION}"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/owl-eds-gen"

# Script and zip file location
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ZIP_PATH="${SCRIPT_DIR}/${ZIP_NAME}"

# Output helpers
bold() { echo -e "\033[1m$*\033[0m"; }
ok()   { echo -e "✅ $*"; }
info() { echo -e "ℹ️  $*"; }
warn() { echo -e "⚠️  $*"; }

# Ensure required packages are installed (Debian/Ubuntu only)
ensure_pkg() {
  local pkg="$1"
  if ! dpkg -s "$pkg" >/dev/null 2>&1; then
    info "Installing package: ${pkg}"
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"
    ok "Package installed: ${pkg}"
  else
    ok "Dependency already installed: ${pkg}"
  fi
}

# Ensure ~/.local/bin is in PATH
ensure_path_exported() {
  case ":$PATH:" in
    *":${BIN_DIR}:"*) ;;
    *)
      warn "~/.local/bin is not in PATH. Adding it to ~/.profile"
      mkdir -p "${HOME}"
      { echo ""; echo "# Added by ${APP_NAME} installer"; echo "export PATH=\"\$HOME/.local/bin:\$PATH\""; } >> "${HOME}/.profile"
      ok "Added ~/.local/bin to PATH in ~/.profile (restart session or run: source ~/.profile)"
      ;;
  esac
}

# Find EDSSharp.exe inside install dir
find_eds_exe() {
  if [ -f "${INSTALL_DIR}/EDSSharp.exe" ]; then
    echo "${INSTALL_DIR}/EDSSharp.exe"
    return
  fi
  local found
  found="$(find "${INSTALL_DIR}" -maxdepth 2 -type f -name "EDSSharp.exe" | head -n1 || true)"
  if [ -n "${found:-}" ]; then
    echo "$found"
    return
  fi
  echo ""
}

bold "==> Checking dependencies..."
if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update -y
  ensure_pkg "mono-complete"
  ensure_pkg "unzip"
else
  warn "This script is designed for Debian/Ubuntu. Please install mono-complete and unzip manually if on another distro."
fi

bold "==> Preparing directories..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${BIN_DIR}"
ok "Directories ready: ${INSTALL_DIR}, ${BIN_DIR}"

bold "==> Installing Open EDS Editor..."
if [ ! -f "${ZIP_PATH}" ]; then
  warn "ZIP file not found: ${ZIP_PATH}"
  warn "Place ${ZIP_NAME} in the SAME directory as this script and rerun."
  exit 1
fi

EDS_EXE="$(find_eds_exe || true)"
if [ -n "${EDS_EXE}" ]; then
  ok "Application already installed at: ${EDS_EXE%/*}"
else
  info "Extracting ${ZIP_NAME}..."
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  unzip -q -o "${ZIP_PATH}" -d "${TMP_DIR}"

  ROOT_ENTRIES=( "${TMP_DIR}"/* )
  if [ ${#ROOT_ENTRIES[@]} -eq 1 ] && [ -d "${ROOT_ENTRIES[0]}" ]; then
    rsync -a --delete "${ROOT_ENTRIES[0]}/" "${INSTALL_DIR}/"
  else
    rsync -a --delete "${TMP_DIR}/" "${INSTALL_DIR}/"
  fi

  EDS_EXE="$(find_eds_exe || true)"
  if [ -z "${EDS_EXE}" ]; then
    warn "Could not find EDSSharp.exe after extraction. Check the ZIP file."
    exit 1
  fi
  ok "Installed ZIP content into: ${INSTALL_DIR}"
fi

bold "==> Creating wrapper command..."
if [ -x "${WRAPPER}" ]; then
  ok "Wrapper already exists: ${WRAPPER}"
else
  cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
# Wrapper to run Open EDS Editor with Mono, forwarding all arguments
exec mono "${EDS_EXE}" "\$@"
EOF
  chmod +x "${WRAPPER}"
  ok "Wrapper created: ${WRAPPER}"
fi

ensure_path_exported

bold "==> Final verification..."
if command -v owl-eds-gen >/dev/null 2>&1; then
  ok "Command available in PATH: $(command -v owl-eds-gen)"
else
  warn "Command not in PATH for this session."
  warn "Run manually: ${WRAPPER}"
  warn "Or reload profile: source ~/.profile"
fi

bold "==> Installation complete!"
ok "Done 🎉"
