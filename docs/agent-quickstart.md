# KaaS — Agent Bootstrap Guide

You are an AI coding agent. A user pasted a one-liner asking you to set up
KaaS. Follow these steps **in order**. Stop and ask the user where indicated.

## 1. Install `kb-ai`

Try these in order until one succeeds:

```bash
uv tool install "git+https://github.com/bybit-exchange/kaas.git#subdirectory=py"
```
```bash
pipx install "git+https://github.com/bybit-exchange/kaas.git#subdirectory=py"
```
```bash
pip install "git+https://github.com/bybit-exchange/kaas.git#subdirectory=py"
```

Verify: `kb-ai` is on PATH.

## 2. Ensure LLM credentials

Check the environment for `LLM_API_KEY` or `OPENAI_API_KEY`. If neither is
set, **ask the user** for an API key, and optionally a base URL and model.
Export them before running `kb-ai`:

```bash
export LLM_API_KEY=...          # required
export LLM_BASE_URL=...         # optional (defaults to OpenAI)
export LLM_MODEL=...            # model for your endpoint (defaults to gpt-4o-mini)
```

Do NOT proceed without a key.

## 3. Ask the user which sources to distill

**Stop and ask:**

> Do you want to distill just the current directory, or add other sources?
> - just this directory
> - other local directories (give paths)
> - URLs (I'll fetch them)
> - text you paste

For URLs, extract each page's readable markdown (kb-ai uses trafilatura to pull the article content, which lives in the JSON envelope's `data.content`):

```bash
echo '{"url":"https://example.com/page"}' | kb-ai fetch-url \
  | python3 -c "import sys, json; print(json.load(sys.stdin)['data']['content'])" \
  > /tmp/page.md
```

Save pasted text to a `.md` file. Collect all local paths (the current dir,
extra dirs, and any files you created from URLs/pasted text).

## 4. Distill

```bash
kb-ai distill <path> [<path2> ...] --kb ./.kaas
```

This wraps readable text files into the KB's `raw/`, compiles them into a
wiki, and prints a JSON summary (`ingested`, `skipped`, `compile`). Report
the skipped files to the user (binaries/PDFs are not converted in this flow).

## 5. Wire up MCP so later sessions can query

**Claude Code:**
```bash
claude mcp add kaas -- env KAAS_KB_DIR=$(pwd)/.kaas LLM_API_KEY=$LLM_API_KEY kb-ai mcp
```

**Codex / openclaw:** add a stdio MCP server with command `kb-ai mcp` and env
`KAAS_KB_DIR=<abs path to .kaas>` plus `LLM_API_KEY` (and `LLM_BASE_URL` /
`LLM_MODEL` if used).

## 6. Close out

Tell the user:

> Done. Open a new agent session and just ask questions about the content you
> distilled — I'll answer from the KaaS wiki via the `ask` tool.
