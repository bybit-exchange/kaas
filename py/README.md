# kb-ai — KaaS AI Engine

The Python AI engine behind KaaS: a four-stage LLM compile pipeline
(**Extract → Classify → Write → Index**), iterative LLM retrieval over the
compiled wiki, and streaming RAG chat. It runs as a long-lived daemon that talks
to the Go backend over a stdin/stdout JSON-line protocol. It also ships an MCP
server and a few one-shot CLI commands.

## Install

```bash
uv sync
```

## Running the daemon

```bash
uv run kb-ai daemon
```

The daemon prints `__READY__` to stderr once it is ready, then reads JSON-line
requests from stdin.

### JSON-line protocol

**Requests** (one JSON object per line, written to stdin):

```json
{"id": "1", "cmd": "ping"}
{"id": "2", "cmd": "init", "payload": {"llm": {"api_key": "...", "base_url": "...", "model": "..."}}}
{"id": "3", "cmd": "shutdown"}
```

**Responses** (one JSON object per line, written to stdout):

```json
{"id": "1", "ok": true, "data": {"uptime_sec": 0.01}}
{"id": "1", "ok": false, "error": {"code": "UNKNOWN_CMD", "message": "..."}}
```

**Streaming responses** (streaming commands: `chat`, `pipeline-stream`):

```json
{"id": "3", "stream": true, "event": {...}}
{"id": "3", "stream": true, "event": {...}, "final": true}
```

### Supported commands

| Command | Purpose |
|------|------|
| `ping` | Liveness check; returns uptime |
| `init` | Initialize the OpenAI client (api_key / base_url / model) |
| `shutdown` | Graceful shutdown |
| `extract` | Extract knowledge from raw content |
| `pipeline` | Run the classify → write pipeline |
| `pipeline-stream` | The same, streaming per-article SSE events |
| `rewrite` | Rewrite a query for better retrieval |
| `suggest` | Generate follow-up question suggestions |
| `index` | Rebuild the markdown indexes (master-index / topic-index) and people stubs |
| `chat` | Streaming RAG chat, with citations |
| `fetch-url` | Fetch a URL and extract its readable content |
| `cancel` | Cancel an in-flight streaming request |
| `derive` | Derive a topic-scoped KB from the article catalog into `derived/<slug>/` |

## MCP Server

```bash
# stdio mode (the default; the client spawns the process directly)
uv run kb-ai mcp

# streamable-http mode
uv run kb-ai mcp --http --host 127.0.0.1 --port 8082
```

Exposes one `ask` tool: iterative LLM retrieval over the compiled KaaS wiki,
answering in markdown with citations.

Signature: `ask(query, paths?, model?, kb?)`. `kb` selects a derived,
topic-scoped knowledge base by slug (see `kb-ai derive`); omit it to search the
whole wiki. An unknown slug is rejected rather than silently falling back to the
full wiki.

| Flag | Meaning |
|------|------|
| `--stdio` | stdio transport (default) |
| `--http` | streamable-http transport |
| `--host` | HTTP listen address (default `127.0.0.1`) |
| `--port` | HTTP port (default `8082`) |
| `--kb-dir` | Override the knowledge-base directory |

In HTTP mode, setting the `KAAS_MCP_TOKEN` environment variable enables Bearer
authentication.

## CLI commands

```bash
uv run kb-ai compile       # read JSON from stdin, run the full compile pipeline
uv run kb-ai fetch-url     # read JSON from stdin, fetch a URL as markdown
uv run kb-ai chat          # read JSON from stdin, run a RAG chat turn
uv run kb-ai rewrite       # read JSON from stdin, rewrite a retrieval query
uv run kb-ai distill <paths...> [--kb .kaas]  # ingest files/directories into a KB and compile
uv run kb-ai derive <topic> [--kb .kaas] [--slug s] [--force] [--model m] [--yes]
```

Every command except `distill` and `derive` reads a JSON request from stdin and
writes `{"ok": ..., "data"|"error": ...}` to stdout.

`derive` builds a topic-scoped knowledge base at `<kb>/derived/<slug>/` from the
source KB's article catalog, leaving the source KB untouched. It prompts before
compiling unless `--yes` is given, and prints the resolved document count and the
run's cost. `--force` replaces an existing `derived/<slug>/` from a previous run.

## Environment variables

| Variable | Default | Purpose |
|------|--------|------|
| `LLM_BASE_URL` / `OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible LLM endpoint |
| `LLM_API_KEY` / `OPENAI_API_KEY` | — | API key for that endpoint |
| `LLM_MODEL` | — | Default model name |
| `LLM_SUMMARIZE_MODEL` | — | Model used by the summarize stage |
| `KAAS_PROMPTS_DIR` | built-in `prompts/defaults/` | Directory of custom prompt templates |
| `KB_AI_MAX_PROMPT_CHARS` | `80000` | Prompt character limit; longer prompts are truncated |
| `KB_AI_PRICING` | — | JSON object of `{model: {"input": per-1M-USD, "output": per-1M-USD}}`. Prices models the built-in table lacks; unpriced models report 0.00 USD and warn once. Example: `{"gpt-4o": {"input": 2.5, "output": 10.0}}` |
| `KB_WORKERS` | `16` | Compile-pipeline worker concurrency, read at two levels: `kb-ai compile`'s document pool, and (in both routes) each phase's per-chunk fan-out in `core/extract.py`. A document over 16,000 chars splits, so the concurrent-call ceiling is documents x chunk workers, which for the queue route is 12 x 16 = 192; the queue route takes its document count from `worker.extract_workers` and reads this only for the fan-out. Real loads sit far below that ceiling, since the fan-out is `min(chunks, KB_WORKERS)` and a 108-document reference corpus averaged 2.8 chunks. |
| `KAAS_DAEMON_MAX_WORKERS` | `8` | Daemon thread-pool size. The 8 applies to a standalone `kb-ai daemon`; when the Go backend spawns it, `ai.daemon.concurrency` is passed here instead (16 by default, and refused at startup if below `worker.extract_workers`). |
| `KAAS_KB_DIR` | `./data` | Knowledge-base root for the MCP server |
| `KAAS_MCP_TOKEN` | — | Bearer token for MCP HTTP mode |

## Prompts

Prompt templates live in `src/kb_ai/prompts/defaults/` in either `.md` (plain
text) or `.yaml` (structured) form. Edit them in place, or point
`KAAS_PROMPTS_DIR` at your own directory to override the behaviour.

## Tests

```bash
uv run pytest tests/ -v
```
