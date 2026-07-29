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

# --- Step 3: Python venv (relocatable) ---
echo "[3/4] Building Python venv (relocatable)..."
uv python install 3.12
VENV_TARGET="${BUILD_DIR}/py/.venv"
uv venv --relocatable --python 3.12 "${VENV_TARGET}"
(cd "${ROOT_DIR}/py" && UV_PROJECT_ENVIRONMENT="${VENV_TARGET}" \
    uv sync --frozen --python 3.12)

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
