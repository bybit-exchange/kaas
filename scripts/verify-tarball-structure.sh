#!/bin/bash
set -euo pipefail

# verify-tarball-structure.sh
# Validate tarball artifact structure: required files, size limit, shebang sanity.
# Usage: bash scripts/verify-tarball-structure.sh /path/to/kaas-v*.tar.gz

TARBALL="${1:-}"

if [[ -z "$TARBALL" ]]; then
  echo "Usage: $0 <tarball-path>"
  exit 1
fi

if [[ ! -f "$TARBALL" ]]; then
  echo "FAIL: file not found: $TARBALL"
  exit 1
fi

ERRORS=0

# --- 1. Size check (<500MB = 524288000 bytes) ---
MAX_SIZE=524288000
FILE_SIZE=$(wc -c < "$TARBALL" | tr -d ' ')

if [[ "$FILE_SIZE" -gt "$MAX_SIZE" ]]; then
  echo "FAIL: tarball size ${FILE_SIZE} bytes exceeds 500MB limit"
  ERRORS=$((ERRORS + 1))
fi

# --- 2. Required files existence ---
REQUIRED_FILES=(
  "kaas/bin/kaas"
  "kaas/py/.venv/bin/python3"
  "kaas/web/dist/index.html"
  "kaas/etc/kaas.toml"
  "kaas/README.md"
)

FILE_LIST_FILE=$(mktemp "${TMPDIR:-/tmp}/kaas-filelist-XXXXXX")
tar -tzf "$TARBALL" > "$FILE_LIST_FILE"

for f in "${REQUIRED_FILES[@]}"; do
  if ! grep -qx "$f" "$FILE_LIST_FILE"; then
    echo "FAIL: missing required file: $f"
    ERRORS=$((ERRORS + 1))
  fi
done

# --- 2b. Bundled Python interpreter must exist (not just a broken symlink) ---
if ! grep -q "kaas/py/.python/.*/bin/python3.12" "$FILE_LIST_FILE"; then
  echo "FAIL: bundled Python interpreter not found (kaas/py/.python/*/bin/python3.12)"
  echo "  The venv's python symlink will be broken without the bundled interpreter."
  ERRORS=$((ERRORS + 1))
fi

# --- 2c. Venv python symlink must be relative (not absolute to build machine) ---
PYTHON_LINK_TMP=$(mktemp -d "${TMPDIR:-/tmp}/kaas-pylink-XXXXXX")
if grep -qx "kaas/py/.venv/bin/python" "$FILE_LIST_FILE"; then
  tar -xzf "$TARBALL" -C "$PYTHON_LINK_TMP" "kaas/py/.venv/bin/python" 2>/dev/null || true
  if [ -L "$PYTHON_LINK_TMP/kaas/py/.venv/bin/python" ]; then
    LINK_TARGET=$(readlink "$PYTHON_LINK_TMP/kaas/py/.venv/bin/python")
    if echo "$LINK_TARGET" | grep -q "^/"; then
      echo "FAIL: py/.venv/bin/python is an absolute symlink: $LINK_TARGET"
      echo "  This will break on the user's machine. Must be relative."
      ERRORS=$((ERRORS + 1))
    fi
  fi
fi
rm -rf "$PYTHON_LINK_TMP"

# --- 3. Shebang check on kaas/py/.venv/bin/kb-ai ---
SHEBANG_TMP=$(mktemp -d "${TMPDIR:-/tmp}/kaas-shebang-XXXXXX")
trap 'rm -rf "$SHEBANG_TMP" "$FILE_LIST_FILE"' EXIT

if grep -qx "kaas/py/.venv/bin/kb-ai" "$FILE_LIST_FILE"; then
  tar -xzf "$TARBALL" -C "$SHEBANG_TMP" "kaas/py/.venv/bin/kb-ai"
  SHEBANG=$(head -1 "$SHEBANG_TMP/kaas/py/.venv/bin/kb-ai")
  if echo "$SHEBANG" | grep -qE '/Users/|/home/'; then
    echo "FAIL: shebang contains build-machine absolute path: $SHEBANG"
    ERRORS=$((ERRORS + 1))
  fi
else
  echo "FAIL: missing required file for shebang check: kaas/py/.venv/bin/kb-ai"
  ERRORS=$((ERRORS + 1))
fi

# --- Result ---
if [[ "$ERRORS" -gt 0 ]]; then
  echo "FAIL: $ERRORS error(s) found"
  exit 1
fi

echo "PASS"
exit 0
