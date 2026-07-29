# syntax=docker/dockerfile:1
#
# KaaS Go+Python 联合镜像：Go binary 提供 REST/SSE API 和 Web UI（单源，端口
# 8080），同时通过 daemon 模式在进程内驱动 Python AI 引擎（uv run）。不再需要
# 独立的 AI HTTP 容器。

# --- Stage 1: build the Web UI (React + Vite) ---
# Node 24: the pinned pnpm@11.8.0 relies on builtins absent from Node 20.
FROM node:24-alpine AS web-builder
WORKDIR /web
RUN corepack enable
# pnpm-workspace.yaml carries the onlyBuiltDependencies allowlist (esbuild);
# without it pnpm 11 blocks esbuild's postinstall and `vite build` fails.
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# --- Stage 2: build a static Go binary (CGO-free via modernc.org/sqlite) ---
FROM golang:1.26-alpine AS go-builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY cmd/ cmd/
COPY internal/ internal/
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/kaas ./cmd/kaas

# --- Stage 3: install Python dependencies via uv ---
FROM python:3.12-slim AS py-builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/py/.venv
WORKDIR /app/py
COPY py/pyproject.toml py/uv.lock py/README.md ./
RUN uv sync --frozen --no-install-project
COPY py/src/ src/
RUN uv sync --frozen

# --- Stage 4: runtime (python:3.12-slim for the .venv to work) ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/py/.venv \
    KAAS_WEB_DIR=/app/web/dist \
    HOME=/tmp \
    USER=kaas \
    LOGNAME=kaas
WORKDIR /app

RUN useradd -u 10001 -m kaas && mkdir -p /app/data && chown -R kaas:kaas /app

# Copy uv binary (daemon uses `uv run` to start Python).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy artifacts from builder stages.
COPY --from=py-builder /app/py /app/py
COPY --from=go-builder /out/kaas /app/kaas
COPY --from=web-builder /web/dist /app/web/dist
COPY etc/ /app/etc/

RUN chown -R kaas:kaas /app
USER kaas

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz').getcode()==200 else 1)" || exit 1

CMD ["/app/kaas", "-f", "/app/etc/kaas.toml"]
