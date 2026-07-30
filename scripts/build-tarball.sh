#!/bin/bash
set -euo pipefail

# Accepts GOOS/GOARCH env vars. Builds a self-contained tarball for the target platform.
# NOTE: Python venv cannot be cross-compiled — this script must run on the target platform.

GOOS="${GOOS:-$(go env GOOS)}"
GOARCH="${GOARCH:-$(go env GOARCH)}"
VERSION="${VERSION:-$(git describe --tags --always --dirty 2>/dev/null || echo "dev")}"
VERSION="${VERSION#v}"
GIT_COMMIT="${GIT_COMMIT:-$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")}"
BUILD_TIME="${BUILD_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build/kaas"
VERSION_PKG="github.com/bybit-exchange/kaas/internal/version"

echo "=== Building kaas v${VERSION} for ${GOOS}/${GOARCH} ==="

# Clean
rm -rf "${BUILD_DIR}" "${DIST_DIR}"
mkdir -p "${BUILD_DIR}/bin" "${BUILD_DIR}/py" "${BUILD_DIR}/etc" "${BUILD_DIR}/web"

# --- Step 1: Go binary ---
echo "[1/4] Building Go binary..."
CGO_ENABLED=0 GOOS="${GOOS}" GOARCH="${GOARCH}" go build \
    -trimpath \
    -ldflags="-s -w \
        -X ${VERSION_PKG}.Version=${VERSION} \
        -X ${VERSION_PKG}.GitCommit=${GIT_COMMIT} \
        -X ${VERSION_PKG}.BuildTime=${BUILD_TIME}" \
    -o "${BUILD_DIR}/bin/kaas" \
    ./cmd/kaas

# --- Step 2: Web frontend ---
echo "[2/4] Building web frontend..."
(cd "${ROOT_DIR}/web" && pnpm install --frozen-lockfile && pnpm build)
cp -r "${ROOT_DIR}/web/dist" "${BUILD_DIR}/web/dist"

# --- Step 3: Python venv (self-contained) ---
echo "[3/4] Building Python venv (self-contained)..."

# Install Python INTO the build directory so it ships with the tarball.
# Without this, the venv's python symlink points to the build machine's path
# (e.g. /Users/runner/.local/share/uv/python/...) which breaks on the user's machine.
PYTHON_INSTALL_DIR="${BUILD_DIR}/py/.python"
UV_PYTHON_INSTALL_DIR="$PYTHON_INSTALL_DIR" uv python install 3.12
BUNDLED_PYTHON=$(find "$PYTHON_INSTALL_DIR" -name "python3.12" -type f -path "*/bin/*" | head -1)
if [ -z "$BUNDLED_PYTHON" ]; then
    echo "ERROR: Could not find bundled python3.12 binary" >&2
    exit 1
fi
PYTHON_INSTALL_NAME=$(basename "$(dirname "$(dirname "$BUNDLED_PYTHON")")")

VENV_TARGET="${BUILD_DIR}/py/.venv"
uv venv --relocatable --python "$BUNDLED_PYTHON" "${VENV_TARGET}"
(cd "${ROOT_DIR}/py" && UV_PROJECT_ENVIRONMENT="${VENV_TARGET}" \
    uv sync --frozen --python "$BUNDLED_PYTHON")

# Fix the venv's python symlink: replace the absolute path (pointing to the build
# machine) with a relative path to the bundled Python interpreter.
# From py/.venv/bin/python → py/.python/<install-name>/bin/python3.12
rm -f "${VENV_TARGET}/bin/python"
ln -s "../../.python/${PYTHON_INSTALL_NAME}/bin/python3.12" "${VENV_TARGET}/bin/python"

# Fix pyvenv.cfg home path to be relative as well.
if grep -q "^home = /" "${VENV_TARGET}/pyvenv.cfg"; then
    sed -i.bak "s|^home = .*|home = ../../.python/${PYTHON_INSTALL_NAME}/bin|" "${VENV_TARGET}/pyvenv.cfg"
    rm -f "${VENV_TARGET}/pyvenv.cfg.bak"
fi

# Clean up uv metadata and fix any absolute symlinks in the Python install dir.
rm -rf "${PYTHON_INSTALL_DIR}/.temp" "${PYTHON_INSTALL_DIR}/.lock" "${PYTHON_INSTALL_DIR}/.gitignore"
# uv creates a short-name symlink (e.g. cpython-3.12-...) as an absolute link;
# replace with relative or remove since we reference the versioned dir directly.
find "${PYTHON_INSTALL_DIR}" -maxdepth 1 -type l | while read -r link; do
    target=$(readlink "$link")
    if echo "$target" | grep -q "^/"; then
        basename_target=$(basename "$target")
        rm "$link"
        ln -s "$basename_target" "$link"
    fi
done

# Strip unnecessary files from bundled Python to reduce tarball size.
rm -rf "${PYTHON_INSTALL_DIR}/${PYTHON_INSTALL_NAME}/include"
rm -rf "${PYTHON_INSTALL_DIR}/${PYTHON_INSTALL_NAME}/share"
find "${PYTHON_INSTALL_DIR}" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "${PYTHON_INSTALL_DIR}" -name "*.pyc" -delete 2>/dev/null || true
find "${PYTHON_INSTALL_DIR}" -name "test" -type d -exec rm -rf {} + 2>/dev/null || true
find "${PYTHON_INSTALL_DIR}" -name "tests" -type d -exec rm -rf {} + 2>/dev/null || true

# Verify shebang is not absolute to build machine
if [ -f "${VENV_TARGET}/bin/kb-ai" ]; then
    SHEBANG=$(head -1 "${VENV_TARGET}/bin/kb-ai")
    if echo "$SHEBANG" | grep -q "${HOME}"; then
        echo "WARNING: venv shebang contains absolute path: ${SHEBANG}"
        echo "Applying sed fix..."
        find "${VENV_TARGET}/bin" -type f -exec \
            sed -i.bak "1s|#!.*python.*|#!/usr/bin/env python3|" {} \;
        find "${VENV_TARGET}/bin" -name "*.bak" -delete
    fi
fi

# --- Step 4: Package ---
echo "[4/4] Packaging..."
cp "${ROOT_DIR}/etc/kaas.toml" "${BUILD_DIR}/etc/kaas.toml"

cat > "${BUILD_DIR}/README.md" << 'EOF'
# KaaS - Knowledge as a Service

## 快速开始

```bash
# 设置 LLM API Key
export LLM_API_KEY="your-api-key"

# 启动服务
kaas serve

# 查看版本
kaas version
```

## 目录结构

- `bin/kaas` — 主程序
- `py/.venv/` — Python AI 引擎运行时
- `web/dist/` — Web UI 静态文件
- `etc/kaas.toml` — 配置文件模板
- `data/` — 运行时数据目录（自动创建）

## 卸载

```bash
rm -rf ~/.local/share/kaas ~/.local/bin/kaas
```

## 文档

https://github.com/bybit-exchange/kaas
EOF

# Create tarball
mkdir -p "${DIST_DIR}"
TARBALL_NAME="kaas-v${VERSION}-${GOOS}-${GOARCH}.tar.gz"
tar -czf "${DIST_DIR}/${TARBALL_NAME}" -C "${ROOT_DIR}/build" kaas

echo ""
echo "=== Done: ${DIST_DIR}/${TARBALL_NAME} ==="
ls -lh "${DIST_DIR}/${TARBALL_NAME}"
