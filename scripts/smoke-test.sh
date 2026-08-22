#!/bin/bash
# smoke-test.sh — post-install smoke test
# Usage: KAAS_BIN=/path/to/bin_dir/kaas bash scripts/smoke-test.sh
#
# KAAS_BIN should point to the symlink in BIN_DIR (not the real binary path)
# Tests:
#   T1: kaas version — exits 0, output contains "kaas"
#   T2: kaas help — exits 0, output contains "serve"
#   T3: KAAS_HOME detection — symlink resolves correctly + marker file exists

set -uo pipefail

PASS=0
FAIL=0

pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "FAIL: $1"
  FAIL=$((FAIL + 1))
}

# Check KAAS_BIN is set
if [[ -z "${KAAS_BIN:-}" ]]; then
  echo "error: KAAS_BIN is not set"
  exit 1
fi

# T1: kaas version — exits 0, output contains "kaas"
echo "--- T1: kaas version ---"
if output=$("$KAAS_BIN" version 2>&1); then
  if echo "$output" | grep -qi "kaas"; then
    pass "T1: kaas version exits 0 and output contains 'kaas'"
  else
    fail "T1: kaas version exits 0 but output does not contain 'kaas': $output"
  fi
else
  fail "T1: kaas version exited with non-zero code"
fi

# T2: kaas help — exits 0, output contains "serve"
echo "--- T2: kaas help ---"
if output=$("$KAAS_BIN" help 2>&1); then
  if echo "$output" | grep -q "serve"; then
    pass "T2: kaas help exits 0 and output contains 'serve'"
  else
    fail "T2: kaas help exits 0 but output does not contain 'serve': $output"
  fi
else
  fail "T2: kaas help exited with non-zero code"
fi

# T3: KAAS_HOME detection — symlink resolves + marker file exists
echo "--- T3: KAAS_HOME detection ---"
T3_PASSED=true

REAL_PATH=$(readlink "$KAAS_BIN" 2>/dev/null || true)
if [[ -z "$REAL_PATH" ]]; then
  fail "T3: KAAS_BIN is not a symlink or readlink failed"
else
  if [[ ! -x "$REAL_PATH" ]]; then
    fail "T3: resolved path is not executable: $REAL_PATH"
    T3_PASSED=false
  fi

  INSTALL_DIR_FROM_BINARY="$(dirname "$(dirname "$REAL_PATH")")"
  MARKER="$INSTALL_DIR_FROM_BINARY/py/.venv/bin/python3"

  if [[ ! -x "$MARKER" ]]; then
    fail "T3: marker file not found or not executable: $MARKER"
    T3_PASSED=false
  fi

  # End-to-end invocation via symlink
  if ! "$KAAS_BIN" version >/dev/null 2>&1; then
    fail "T3: end-to-end invocation via symlink failed"
    T3_PASSED=false
  fi

  if [[ "$T3_PASSED" == "true" ]]; then
    pass "T3: KAAS_HOME detection via symlink works correctly"
  fi
fi

# Summary
echo ""
echo "=== Results: $PASS PASS, $FAIL FAIL ==="

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi

exit 0
