#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${VERSION:-0.0.0-verify}"

# --- Temporary resource tracking ---
INSTALL_DIR=""
BIN_DIR=""
SERVE_DIR=""
HTTP_PID=""

cleanup() {
    echo ""
    echo "[cleanup] Stopping HTTP server and removing temporary directories..."
    [ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null || true
    [ -n "$INSTALL_DIR" ] && rm -rf "$INSTALL_DIR"
    [ -n "$BIN_DIR" ] && rm -rf "$BIN_DIR"
    [ -n "$SERVE_DIR" ] && rm -rf "$SERVE_DIR"
}
trap cleanup EXIT

echo "=== KaaS Install Verification (v${VERSION}) ==="
echo ""

# Step 1: Build tarball
echo "[1/6] Building tarball..."
VERSION="$VERSION" bash "$ROOT_DIR/scripts/build-tarball.sh"

TARBALL=$(ls "$ROOT_DIR/dist/"kaas-v${VERSION}-*.tar.gz 2>/dev/null | head -1)
if [ -z "$TARBALL" ]; then
    echo "ERROR: No tarball found in dist/" >&2
    exit 1
fi
echo "  Tarball: $TARBALL"

# Step 2: Verify structure
echo ""
echo "[2/6] Verifying tarball structure..."
bash "$ROOT_DIR/scripts/verify-tarball-structure.sh" "$TARBALL"

# Step 3: Start local HTTP server
echo ""
echo "[3/6] Starting local file server..."

# Create serve directory matching install.sh URL pattern: ${DOWNLOAD_URL}/v${VERSION}/${TARBALL_NAME}
SERVE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kaas-serve-XXXXXX")"
mkdir -p "${SERVE_DIR}/v${VERSION}"
cp "$TARBALL" "${SERVE_DIR}/v${VERSION}/"

# Use Python to start HTTP server, write port to file
PORT_FILE="$(mktemp "${TMPDIR:-/tmp}/kaas-port-XXXXXX")"
python3 -c "
import http.server, socket, os

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(('127.0.0.1', 0))
port = sock.getsockname()[1]
sock.close()

with open('${PORT_FILE}', 'w') as f:
    f.write(str(port))

os.chdir('${SERVE_DIR}')
handler = http.server.SimpleHTTPRequestHandler
handler.log_message = lambda *a: None
httpd = http.server.HTTPServer(('127.0.0.1', port), handler)
httpd.serve_forever()
" &
HTTP_PID=$!

# Wait for port file
for i in $(seq 1 50); do [ -s "$PORT_FILE" ] && break; sleep 0.1; done
HTTP_PORT=$(cat "$PORT_FILE")
rm -f "$PORT_FILE"

echo "  Serving at http://127.0.0.1:${HTTP_PORT}/"

# Step 4: Run REAL install.sh
echo ""
echo "[4/6] Running install.sh (with env var overrides)..."

INSTALL_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kaas-install-XXXXXX")"
BIN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/kaas-bin-XXXXXX")"

echo "  KAAS_INSTALL_DIR=$INSTALL_DIR"
echo "  KAAS_BIN_DIR=$BIN_DIR"
echo "  KAAS_DOWNLOAD_URL=http://127.0.0.1:${HTTP_PORT}"
echo "  KAAS_VERSION=$VERSION"

KAAS_INSTALL_DIR="$INSTALL_DIR" \
KAAS_BIN_DIR="$BIN_DIR" \
KAAS_DOWNLOAD_URL="http://127.0.0.1:${HTTP_PORT}" \
KAAS_VERSION="$VERSION" \
    bash "$ROOT_DIR/install.sh"

# Verify install result
echo ""
echo "  Verifying install result..."
test -x "$INSTALL_DIR/bin/kaas" || { echo "FAIL: binary not found"; exit 1; }
test -L "$BIN_DIR/kaas" || { echo "FAIL: symlink not found"; exit 1; }
test -x "$INSTALL_DIR/py/.venv/bin/python3" || { echo "FAIL: python3 not found"; exit 1; }
test -d "$INSTALL_DIR/data/raw" || { echo "FAIL: data directory not created"; exit 1; }
echo "  Install result: OK"

# Step 4b: Cross-machine portability checks
# These catch issues that only manifest when the tarball is built on one machine
# and installed on another (e.g. CI → user). On the same machine, absolute paths
# resolve fine, masking broken symlinks and .pth files.
echo ""
echo "  Verifying cross-machine portability..."
PORTABILITY_ERRORS=0

# Check: no absolute symlinks under py/ that point outside the install dir
while IFS= read -r link; do
    target=$(readlink "$link")
    if echo "$target" | grep -q "^/" && ! echo "$target" | grep -q "^$INSTALL_DIR"; then
        echo "  FAIL: absolute symlink escapes install dir: $link → $target"
        PORTABILITY_ERRORS=$((PORTABILITY_ERRORS + 1))
    fi
done < <(find "$INSTALL_DIR/py" -type l 2>/dev/null)

# Check: no .pth files with absolute paths (editable installs)
while IFS= read -r pth; do
    if grep -q "^/" "$pth" 2>/dev/null; then
        PTH_CONTENT=$(cat "$pth")
        echo "  FAIL: .pth file contains absolute path: $pth → $PTH_CONTENT"
        PORTABILITY_ERRORS=$((PORTABILITY_ERRORS + 1))
    fi
done < <(find "$INSTALL_DIR/py/.venv" -name "*.pth" 2>/dev/null)

# Check: pyvenv.cfg home is not an absolute path to a foreign location
PYVENV_HOME=$(grep "^home = " "$INSTALL_DIR/py/.venv/pyvenv.cfg" 2>/dev/null | sed 's/^home = //')
if echo "$PYVENV_HOME" | grep -q "^/" && ! echo "$PYVENV_HOME" | grep -q "^$INSTALL_DIR"; then
    echo "  FAIL: pyvenv.cfg home points outside install dir: $PYVENV_HOME"
    PORTABILITY_ERRORS=$((PORTABILITY_ERRORS + 1))
fi

# Check: kb_ai is importable
if ! "$INSTALL_DIR/py/.venv/bin/python3" -c "import kb_ai" 2>/dev/null; then
    echo "  FAIL: python3 -c 'import kb_ai' failed"
    PORTABILITY_ERRORS=$((PORTABILITY_ERRORS + 1))
fi

if [ "$PORTABILITY_ERRORS" -gt 0 ]; then
    echo "  FAIL: $PORTABILITY_ERRORS portability error(s) found"
    echo "  These will cause failures when installed on a different machine."
    exit 1
fi
echo "  Portability checks: OK"

# Step 5: Smoke test
echo ""
echo "[5/6] Running smoke tests..."
KAAS_BIN="$BIN_DIR/kaas" bash "$ROOT_DIR/scripts/smoke-test.sh"

# Step 6: Uninstall verification
echo ""
echo "[6/6] Verifying uninstall..."
echo "  Running: rm -rf $INSTALL_DIR $BIN_DIR/kaas"
rm -rf "$INSTALL_DIR" "$BIN_DIR/kaas"

# Verify
if [ -e "$INSTALL_DIR" ]; then
    echo "FAIL: INSTALL_DIR still exists after uninstall"
    exit 1
fi
if [ -e "$BIN_DIR/kaas" ] || [ -L "$BIN_DIR/kaas" ]; then
    echo "FAIL: kaas symlink still exists after uninstall"
    exit 1
fi
if [ ! -d "$BIN_DIR" ]; then
    echo "FAIL: BIN_DIR was entirely removed (should only remove kaas)"
    exit 1
fi
echo "  Uninstall verification: OK"

# Clear already-deleted paths so cleanup doesn't warn
INSTALL_DIR=""

echo ""
echo "=== All checks passed! ==="
