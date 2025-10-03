#!/usr/bin/env bash
set -euo pipefail

# setup.sh
# Expected location:
#  - this script is in the same directory as the folder `oze-canopen-viewer/`
#  - ./oze-canopen-viewer contains the source code (Cargo.toml, src/, etc.)
#
# What it does:
#  - checks if the tool is already installed (and exits doing nothing if so)
#  - installs system dependencies (Debian/Ubuntu)
#  - installs rustup if needed
#  - compiles in release mode with cargo
#  - installs the binary into /usr/local/bin
#  - applies setcap so you don’t need sudo to use SocketCAN
#  - cleans the local build artifacts after successful install

REPO_DIR="oze-canopen-viewer"
TARGET_BIN_NAME="oze-canopen-viewer"   # adjust if the binary has a different name
INSTALL_PATH="/usr/local/bin"
INSTALLED_BIN_PATH="${INSTALL_PATH}/${TARGET_BIN_NAME}"

# If already installed, do nothing and show final message
if [ -x "${INSTALLED_BIN_PATH}" ]; then
  cat <<EOF

==========================================================
${TARGET_BIN_NAME} is already installed at: ${INSTALLED_BIN_PATH}
==========================================================
EOF
  exit 0
fi

# Ensure repo directory exists
if [ ! -d "${REPO_DIR}" ]; then
  echo "ERROR: Directory '${REPO_DIR}' not found in $(pwd)."
  echo "Make sure to run this script from the directory containing '${REPO_DIR}/'."
  exit 1
fi

echo "==> 1) Updating APT repos and installing system dependencies (sudo required)..."
sudo apt update
sudo apt install -y \
  curl \
  build-essential \
  pkg-config \
  libssl-dev \
  libglib2.0-dev \
  libgtk-3-dev \
  libx11-dev \
  libxkbcommon-dev \
  ca-certificates \
  clang

echo "==> 2) Installing rustup / toolchain if missing..."
if command -v rustup >/dev/null 2>&1; then
  echo "rustup found. Updating toolchain..."
  rustup update
else
  echo "rustup not found. Installing rustup..."
  curl https://sh.rustup.rs -sSf | sh -s -- -y
fi

# Load cargo into PATH for this session
if [ -f "$HOME/.cargo/env" ]; then
  # shellcheck source=/dev/null
  source "$HOME/.cargo/env"
fi

echo "==> 3) Checking that cargo is available..."
if ! command -v cargo >/dev/null 2>&1; then
  echo "ERROR: cargo not in PATH after rustup install. Run 'source \$HOME/.cargo/env' then rerun this script."
  exit 1
fi

echo "==> 4) Building in release mode (this may take a while)..."
pushd "${REPO_DIR}" >/dev/null

cargo build --release

BIN_PATH="target/release/${TARGET_BIN_NAME}"
if [ ! -x "${BIN_PATH}" ]; then
  echo "ERROR: Binary not found at ${BIN_PATH}."
  echo "Listing target/release/:"
  ls -la target/release/ || true
  popd >/dev/null
  exit 1
fi

echo "==> 5) Installing ${BIN_PATH} binary into ${INSTALL_PATH} (sudo required)..."
sudo cp "${BIN_PATH}" "${INSTALL_PATH}/"
sudo chmod +x "${INSTALLED_BIN_PATH}"

echo "==> 6) Applying capabilities so the binary can access SocketCAN without sudo..."
sudo setcap cap_net_admin,cap_net_raw+ep "${INSTALLED_BIN_PATH}" || {
  echo "Warning: setcap failed. You can still run the app with sudo, or fix libcap and retry."
}

echo "==> 7) Cleaning build artifacts (removing ${REPO_DIR}/target)..."
rm -rf target

popd >/dev/null

cat <<EOF

==========================================================
oze-canopen-viewer INSTALLATION COMPLETED
==========================================================
EOF
