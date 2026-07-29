#!/bin/sh
set -e

REPO="bybit-exchange/kaas"
INSTALL_DIR="${KAAS_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/kaas}"
BIN_DIR="${KAAS_BIN_DIR:-${HOME}/.kaas}"

# 1. Detect platform
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
ARCH="$(uname -m)"
case "$ARCH" in
    x86_64|amd64) ARCH="amd64" ;;
    arm64|aarch64) ARCH="arm64" ;;
    *) echo "kaas: unsupported architecture: $ARCH" >&2; exit 1 ;;
esac
case "$OS" in
    linux|darwin) ;;
    *) echo "kaas: unsupported OS: $OS" >&2; exit 1 ;;
esac

# 2. Get latest version (or use KAAS_VERSION env var)
if [ -z "$KAAS_VERSION" ]; then
    KAAS_VERSION="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
        | grep '"tag_name"' | sed 's/.*"v\(.*\)".*/\1/')"
fi
if [ -z "$KAAS_VERSION" ]; then
    echo "kaas: failed to detect latest version" >&2; exit 1
fi

# 3. Download and extract
TARBALL="kaas-v${KAAS_VERSION}-${OS}-${ARCH}.tar.gz"
DOWNLOAD_URL="${KAAS_DOWNLOAD_URL:-https://github.com/${REPO}/releases/download}"
URL="${DOWNLOAD_URL}/v${KAAS_VERSION}/${TARBALL}"
echo "Downloading kaas v${KAAS_VERSION} for ${OS}/${ARCH}..."

mkdir -p "$INSTALL_DIR"
curl -fsSL "$URL" | tar --strip-components=1 -xz -C "$INSTALL_DIR"

# 4. Create symlink
mkdir -p "$BIN_DIR"
ln -sf "${INSTALL_DIR}/bin/kaas" "${BIN_DIR}/kaas"

# 5. Initialize data directory
mkdir -p "${INSTALL_DIR}/data/raw" "${INSTALL_DIR}/data/wiki" "${INSTALL_DIR}/data/index"

# 6. PATH hint
case ":$PATH:" in
    *":${BIN_DIR}:"*) ;;
    *)
        echo ""
        echo "Add ${BIN_DIR} to your PATH:"
        echo "  export PATH=\"${BIN_DIR}:\$PATH\""
        echo ""
        echo "To make it permanent:"
        echo "  echo 'export PATH=\"${BIN_DIR}:\$PATH\"' >> ~/.zshrc"
        ;;
esac

# 7. Done
echo ""
echo "kaas v${KAAS_VERSION} installed successfully!"
echo ""
echo "Quick start:"
echo "  export LLM_API_KEY=\"your-api-key\"    # Set LLM API Key"
echo "  kaas serve                            # Start service"
echo "  kaas version                          # Show version"
echo ""
echo "Uninstall:"
echo "  rm -rf ${INSTALL_DIR} ${BIN_DIR}/kaas"
echo ""
echo "Documentation: https://github.com/${REPO}"
