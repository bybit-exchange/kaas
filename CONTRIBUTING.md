# Contributing to KaaS

Thanks for your interest in improving KaaS! This guide covers how to set up a
dev environment, run the tests, and submit changes.

## Scope

KaaS is the **single-user, self-hosted** edition: you run one instance against
one knowledge base. Multi-tenant auth, admin consoles, cost-approval flows, and
platform-specific integrations are intentionally out of scope — please open an
issue to discuss before building features that assume a multi-user deployment.

Good first contributions: bug fixes, docs, test coverage, additional LLM
provider examples, and UI polish.

## Prerequisites

| Tool | Version | Used for |
|------|---------|----------|
| Go | 1.26+ | Backend (`cmd/`, `internal/`) |
| Python | 3.12+ | AI engine (`py/`) |
| [uv](https://docs.astral.sh/uv/) | latest | Python deps & runner |
| Node | 24+ | Web UI build (`web/`) |
| pnpm | 11.8 (via `corepack enable`) | Web deps |
| Docker | optional | Single-container run |

You also need an OpenAI-compatible LLM endpoint to exercise the compile and chat
paths. Any endpoint works — set `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`
(e.g. point `LLM_BASE_URL` at a local Ollama or LiteLLM proxy).

## Getting started

```bash
git clone https://github.com/bybit-exchange/kaas.git
cd kaas
make init          # create data/ subdirs
```

Fill in your LLM credentials in `etc/kaas-dev.toml` (the `[llm]` section), or
override via environment variables:

```bash
export LLM_API_KEY="sk-xxx"
export LLM_BASE_URL="https://api.openai.com/v1"   # 可选，默认 OpenAI
export LLM_MODEL="gpt-4o-mini"                    # 可选，默认 gpt-4o-mini
```

### Run everything (local dev)

```bash
make dev
```

This starts the Go backend (which auto-spawns the Python AI daemon) and the
Vite dev server. Backend listens on `:8080`; open the URL Vite prints for the UI.

### Run services individually

```bash
# Backend (auto-spawns Python AI daemon via stdin/stdout)
go run ./cmd/kaas -f etc/kaas-dev.toml

# Web UI (hot-reload)
cd web && pnpm install && pnpm dev

# MCP server (stdio — for local agent integration)
cd py && KAAS_KB_DIR=./data uv run kb-ai mcp
```

### Run via Docker (closest to production)

```bash
docker build -t kaas .
docker run -d -p 8080:8080 -v ./data:/app/data \
  -e LLM_API_KEY=$LLM_API_KEY \
  -e LLM_BASE_URL=$LLM_BASE_URL \
  -e LLM_MODEL=$LLM_MODEL \
  kaas
```

A single Docker image bundles Go backend + Python AI engine + Web static files — no sidecar containers needed.

## Running tests

`make test` runs all three suites. Or per layer:

```bash
go test ./... -v -count=1               # Go backend
cd py && uv run pytest tests/ -v        # Python AI engine
cd web && pnpm test                     # Web UI (vitest)
```

Please add or update tests for any behavior change, and make sure the full suite
passes before opening a PR.

## Code style

- **Go**: keep it `gofmt`-clean (`gofmt -w .`); follow the conventions already in
  `internal/`.
- **Python**: 4-space indent, type hints on public functions; match the existing
  style in `py/src/kb_ai/`.
- **Web**: TypeScript strict mode (the build runs `tsc --noEmit`); follow the
  component patterns under `web/src/`.

There is no enforced linter yet — match the surrounding code.

## Commit & PR conventions

Commits follow [Conventional Commits](https://www.conventionalcommits.org/) with
an optional scope, mirroring the existing history:

```
feat(web): add Wiki TOC navigation
fix(worker): recover leases after circuit-breaker trip
docs: clarify Ollama setup
chore: bump go-zero
test(api): cover empty task list
```

Common scopes: `web`, `worker`, `api`, `ai`, `store`, `cli`, `infra`.

For a pull request:

1. Branch from `main`.
2. Keep the PR focused; describe **what** changed and **why**.
3. Ensure `make test` passes and the code is formatted.
4. Link any related issue.

## Automated triage & @claude

This repo uses Anthropic's `claude-code-action` for lightweight automation:

- **Auto-triage**: new issues get labeled and, if a bug report is missing
  reproduction details, a polite follow-up — usually within minutes.
- **`@claude` on demand**: maintainers (write access) can mention `@claude`
  in an issue or PR comment to get help or a draft change as a PR. Claude
  never merges or approves — a human always reviews and merges.

If automated triage mislabels something, just correct the labels — it only
applies existing labels and never closes issues or changes code.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
