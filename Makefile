.PHONY: dev build test clean tarball verify-install verify-tarball release

VERSION   ?= $(shell git describe --tags --always --dirty 2>/dev/null || echo dev)
GIT_COMMIT = $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
BUILD_TIME = $(shell date -u '+%Y-%m-%dT%H:%M:%SZ')
LDFLAGS    = -X github.com/bybit-exchange/kaas/internal/version.Version=$(VERSION) \
             -X github.com/bybit-exchange/kaas/internal/version.GitCommit=$(GIT_COMMIT) \
             -X github.com/bybit-exchange/kaas/internal/version.BuildTime=$(BUILD_TIME)

# Start all services for local development
dev:
	@bash scripts/dev.sh

# Build all
build:
	@go build -ldflags "$(LDFLAGS)" -o bin/kaas ./cmd/kaas
	@cd web && pnpm build

# Run all tests
test:
	@go test ./... -v -count=1
	@cd py && uv run pytest tests/ -v
	@cd web && pnpm test

# Initialize data directory
init:
	@mkdir -p data/raw data/wiki data/index

clean:
	@rm -rf bin/ web/dist/

# Build tarball for current platform
tarball:
	@VERSION=$(VERSION) bash scripts/build-tarball.sh

# Full install verification flow
verify-install:
	@VERSION=0.0.0-verify bash scripts/verify-install.sh

# Build tarball then verify its structure
verify-tarball: tarball
	@bash scripts/verify-tarball-structure.sh dist/*.tar.gz

# Push a clean release branch and tag (usage: make release TAG=v0.1.0)
release:
	@bash scripts/release.sh $(TAG)
