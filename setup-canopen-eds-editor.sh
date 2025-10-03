#!/usr/bin/env bash
#
# Copyright (C) 2025 - OWL Services LLC
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License (version 2) as published by the
# FSF - Free Software Foundation
#
set -euo pipefail

APP_NAME="CANopenEditor"
APP_VERSION="4.2.3"
ZIP_NAME="CANopenEditor-v4.2.3-binary.zip"

# User-space install locations (no root required for the binaries)
INSTALL_DIR="${HOME}/.local/share/${APP_NAME}-${APP_VERSION}"
BIN_DIR="${HOME}/.local/bin"
WRAPPER="${BIN_DIR}/owl-eds-editor"

# Locations relative to the extracted ZIP structure
REL_EXE_PATH="net481/EDSEditor.exe"

# Script and ZIP location
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ZIP_PATH="${SCRIPT_DIR}/${ZIP_NAME}"

# Output helpers
if [ -t 1 ]; then
  bold() { printf "\033[1m%s\033[0m\n" "$*"; }
  ok()   { printf "✅ %s\n" "$*"; }
  info() { printf "ℹ️  %s\n" "$*"; }
  warn() { printf "⚠️  %s\n" "$*"; }
else
  bold() { echo "$*"; }
  ok()   { echo "$*"; }
  info() { echo "$*"; }
  warn() { echo "$*"; }
fi

# Ensure required packages on Debian/Ubuntu (mono-complete, unzip)
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

# Ensure ~/.local/bin is in PATH for future sessions
ensure_path_exported() {
  case ":$PATH:" in
    *":${BIN_DIR}:"*) ;;
    *)
      warn "~/.local/bin is not in PATH. Adding it to ~/.profile"
      mkdir -p "${HOME}"
      { echo ""; echo "# Added by ${APP_NAME} ${APP_VERSION} installer"; echo "export PATH=\"\$HOME/.local/bin:\$PATH\""; } >> "${HOME}/.profile"
      ok "Added ~/.local/bin to PATH in ~/.profile (restart session or run: source ~/.profile)"
      ;;
  esac
}

# Return full path to expected EXE if installed, else empty
find_editor_exe() {
  local candidate="${INSTALL_DIR}/${REL_EXE_PATH}"
  if [ -f "${candidate}" ]; then
    echo "${candidate}"
    return
  fi
  # Fallback: search within INSTALL_DIR just in case structure differs slightly
  local found
  found="$(find "${INSTALL_DIR}" -type f -path "*/${REL_EXE_PATH}" -print -quit 2>/dev/null || true)"
  if [ -n "${found:-}" ]; then
    echo "${found}"
    return
  fi
  echo ""
}

bold "==> Checking dependencies..."
if command -v apt-get >/dev/null 2>&1 && command -v dpkg >/dev/null 2>&1; then
  sudo apt-get update -y
  ensure_pkg "mono-complete"
  ensure_pkg "unzip"
else
  warn "This installer targets Debian/Ubuntu (apt/dpkg)."
  warn "Please ensure 'mono-complete' and 'unzip' are installed if using another distro."
fi

bold "==> Preparing directories..."
mkdir -p "${INSTALL_DIR}"
mkdir -p "${BIN_DIR}"
ok "Directories ready: ${INSTALL_DIR}, ${BIN_DIR}"

bold "==> Installing CANopen EDS Editor payload..."
if [ ! -f "${ZIP_PATH}" ]; then
  warn "ZIP not found at: ${ZIP_PATH}"
  warn "Place ${ZIP_NAME} in the SAME directory as this script and rerun."
  exit 1
fi

EDITOR_EXE="$(find_editor_exe || true)"
if [ -n "${EDITOR_EXE}" ]; then
  ok "Application already installed at: ${EDITOR_EXE%/*}"
else
  info "Extracting ${ZIP_NAME}..."
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT
  unzip -q -o "${ZIP_PATH}" -d "${TMP_DIR}"

  # Copy extracted content into INSTALL_DIR (handle either flat or single-root-dir zips)
  ROOT_ENTRIES=( "${TMP_DIR}"/* )
  if [ ${#ROOT_ENTRIES[@]} -eq 1 ] && [ -d "${ROOT_ENTRIES[0]}" ]; then
    # Single top-level directory inside the ZIP
    cp -a "${ROOT_ENTRIES[0]}/." "${INSTALL_DIR}/"
  else
    # Multiple entries at ZIP root
    cp -a "${TMP_DIR}/." "${INSTALL_DIR}/"
  fi

  EDITOR_EXE="$(find_editor_exe || true)"
  if [ -z "${EDITOR_EXE}" ]; then
    warn "Could not locate ${REL_EXE_PATH} after extraction. Please verify the ZIP contents."
    exit 1
  fi
  ok "Installed ZIP contents into: ${INSTALL_DIR}"
fi

bold "==> Creating wrapper command..."
if [ -x "${WRAPPER}" ]; then
  ok "Wrapper already exists: ${WRAPPER}"
else
  cat > "${WRAPPER}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
# Wrapper to run CANopen EDS Editor with Mono, forwarding all arguments.
exec mono "${EDITOR_EXE}" "\$@"
EOF
  chmod +x "${WRAPPER}"
  ok "Wrapper created: ${WRAPPER}"
fi

ensure_path_exported

bold "==> Final verification..."
if command -v owl-eds-editor >/dev/null 2>&1; then
  ok "Command available in PATH: $(command -v owl-eds-editor)"
else
  warn "Command not yet in PATH for this session."
  warn "Use directly: ${WRAPPER}"
  warn "Or reload your shell profile: source ~/.profile"
fi

bold "==> Installation complete!"
ok "Done 🎉"
