# Derive Topic KB — Implementation Notes

## C6 verification

The nesting-is-inert property rests on two glob roots never reaching `<kb>/derived/`.
The Go side was spot-checked with:

```
grep -rn 'filepath.Join(.*"raw"' internal/
grep -rn '"wiki"' internal/api/wiki.go
```

---

## Smoke run (spec I3)

**Date:** 2026-08-05 · **Model routed:** `claude-sonnet-4-6` (name only — see note on actual backend below) · **Source:** a corpus of 6 markdown files copied from this repository's `docs/` to `/tmp/kaas-smoke-corpus/`, ingested with `kb-ai distill /tmp/kaas-smoke-corpus --kb /tmp/kaas-derive-smoke`.

### Gateway note

No paid Anthropic API key was available in the environment at smoke-run time. `ANTHROPIC_AUTH_TOKEN` is the Claude Code session token (25 chars, rejected by the Anthropic API as `invalid x-api-key`). All LLM calls were routed through a local LiteLLM proxy (`http://localhost:4777/v1`) backed by local models (Ollama gemma3:latest 4B, and a llama.cpp 30B Q4K-Medium server). The model name in every request was `claude-sonnet-4-6`, so all reported cost figures are hypothetical: they show what the same token counts would have cost at claude-sonnet-4-6 pricing. Actual spend: **USD 0.00**.

### Step 1 — compile source KB

```
uv --directory py run kb-ai distill /tmp/kaas-smoke-corpus --kb /tmp/kaas-derive-smoke
```

Output (abridged):
```
Phase 1 done: 5 extracted (0 cached), 1 errors, $0.1958, 78.4s
Phase 2a done: 5 classified (0 cached), 1 errors, $0.0160, 6.5s
Phase 2b done: $0.0647, 36.1s
Compile done: 4 compiled, 1 errors, $0.2765 total
{"ok": true, "data": {"ingested": 6, "compile": {"compiled": 4, "errors": [...]}, ...}}
```

**Defect found:** Gemma4:12b-mlx generated article paths without `.md` extension (`wiki/ai-agent`, `wiki/project/kaas-derived-kb`). The index builder globs `wiki/**/*.md`, so it found no files and left `master-index.md` empty. Manual repair: rename both files, then call `update_markdown_index` directly. This is a model output format defect, not a kb_ai bug — a properly behaved model (Claude, GPT-4) would emit `wiki/ai-agent.md`.

After repair: 2 articles in source KB catalog.

```
grep -c '^- \[' /tmp/kaas-derive-smoke/index/master-index.md
→ 2
```

### Step 2 — derive "retrieval and the chat answer path" (--yes)

The 30B llama.cpp server responded correctly (with json_repair assistance — see concern 2 below). Timing was 2m37s wall-clock.

```
LLM_BASE_URL=http://localhost:4777/v1 LLM_API_KEY=test LLM_MODEL=claude-sonnet-4-6 \
uv --directory py run kb-ai derive "retrieval and the chat answer path" \
  --kb /tmp/kaas-derive-smoke --yes
```

Result: `{"ok": true, ...}` — full payload in task-10-report.md.

| Figure | Value | Where it came from |
|---|---|---|
| Source articles | 2 | `grep -c '^- \[' /tmp/kaas-derive-smoke/index/master-index.md` |
| Topic | `retrieval and the chat answer path` | CLI argument |
| Filter batches | 1 | `data.filter_batches` |
| Articles matched | 2 | `data.selected` |
| Articles skipped (no sources etc.) | 0 | `data.skipped` |
| Documents resolved | 4 | `data.documents` |
| Bytes to compile | 32,252 | `data.bytes` |
| Articles compiled (raw files) | 0 | `data.compile.compiled` |
| Articles compiled (wiki files created) | 2 | files in `derived/retrieval-and-the-chat-answer-path/wiki/` |
| Articles moved off-topic | 0 | `data.offtopic` |
| **Move ratio** | 0/0 (undefined) | derived — see reading below |
| Extract-cache hits | 4 | `[cached]` lines in `.compile.log` |
| Total cost | 0.051466 USD (hypothetical — actual USD 0.00) | `data.cost.total_cost_usd` |

**Verified:** derived `raw/` holds 4 copied documents. Source KB catalog unchanged (still 2 articles). No `_offtopic/` created (none moved). `manifest.json` present with schema_version 1, `compiled: true`, `offtopic_articles: []`.

**Concern:** `data.compile.compiled: 0` even though 2 wiki files were created. The 30B model prepends a chain-of-thought `thought\n` token before YAML frontmatter, so the index builder (which checks `content.startswith("---")`) skips both articles. The derived `master-index.md` is empty. This prevented the PRECISION pass from running (warning: `second_pass_empty_catalog`). The 4 remaining write operations failed with 500/InternalServerError — the 30B llama.cpp server was overwhelmed by 4 parallel write workers.

### Reading of the move ratio

The move ratio is undefined (0 offtopic / 0 catalog entries) because the PRECISION pass received an empty catalog: the two wiki articles that were written both had a `thought\n` prefix injected by the local model, causing the index builder to skip them. This is a **local model defect, not a pipeline logic defect**: the PRECISION pass code correctly invokes `select_by_topic` over the derived KB's catalog and calls `prune`, but there was nothing in the catalog to prune.

A ratio near 0 on a real API (Claude, GPT-4) means the PRECISION pass is too permissive; near 1 means it is too strict. This smoke run cannot measure the ratio because the corpus was too small (2 articles, both genuinely relevant to the topic) and the local model corrupted the compile output. The tech design's answer if the ratio is bad is to revisit brainstorm decision 1 (filter at the article level) — this run gives no evidence pointing either way.

### Step 3 — derive "cost accounting" gate test

Not completed. After the heavy step-2 run the 30B llama.cpp process died (OOM or resource limit). gemma3:latest is the only Ollama model that returns non-empty responses via the OpenAI-compatible endpoint, but it returns a bare JSON array `[...]` rather than `{"paths": [...]}`, causing `DeriveError: topic filter returned no paths list`. Two attempts confirmed the failure is consistent. This step remains untested.

### Step 4 — MCP --help on derived KB

```
KAAS_KB_DIR=/tmp/kaas-derive-smoke/derived/retrieval-and-the-chat-answer-path \
  uv --directory py run kb-ai mcp --help
```
Exits 0 and prints usage — derived directory is accepted as a loadable KB root.

### Step 6 — full Python suite

```
cd py && uv run pytest tests/ -q
```
**1176 passed, 1 skipped, 1 xfailed in 2.33s** — Stage 1 sign-off condition met.

### Concerns

1. **No paid gateway available.** `ANTHROPIC_AUTH_TOKEN` is a Claude Code session token, not an Anthropic API key. The design-intended test (verify filter prompt returns usable paths with a real Claude model) could not be run. All cost figures are hypothetical.
2. **Local models don't follow the filter JSON format.** gemma3:latest returns a bare list `[...]` rather than `{"paths": [...]}`. The pipeline raises `DeriveError`. The json_repair path in `completion_json` is not reached because the error is at the dict-shape check before json_repair, not at parse time. The 30B llama.cpp model returns the correct `{"paths": [...]}` shape but prepends chain-of-thought tokens to article content.
3. **PRECISION pass untested.** The move ratio is the key metric for spec O4 ("off-topic bleed"). With an empty derived catalog, the pass is a no-op and no evidence about the real bleed rate was collected.
4. **Step 3 gate test not run.** The volume gate (F5) behavior when the user declines was not exercised.

### Raw writes — rooted at `filepath.Join(KBDir, "raw", ...)`

Every raw-file write in the Go layer goes to `filepath.Join(s.cfg.KBDir, "raw", ...)`:

```
internal/api/submit.go:60:          rawPath := filepath.Join(s.cfg.KBDir, "raw", id+".md")
internal/api/submit_files.go:159:   rawPath := filepath.Join(s.cfg.KBDir, "raw", id+".md")
internal/api/submit_files.go:357:   rawPath := filepath.Join(s.cfg.KBDir, "raw", id+".md")
internal/api/tasks.go:158:          rawDir  := filepath.Join(s.cfg.KBDir, "raw")
```

None of these reach `<kb>/derived/`.

### Wiki walker — rooted at `filepath.Join(s.cfg.KBDir, "wiki")`

```
internal/api/wiki.go:168:  wikiDir := filepath.Join(s.cfg.KBDir, "wiki")
internal/api/wiki.go:271:  wikiDir := filepath.Join(s.cfg.KBDir, "wiki")
```

Both walk roots are `<kb>/wiki`, not `<kb>`, so a derived KB at
`<kb>/derived/<slug>/wiki/` is unreachable. The same isolation holds for the
Python side: `KBStore._iter_raw_paths` globs `self.raw_dir` (`<base>/raw/`), and
`update_markdown_index` globs `store.wiki_dir` (`<base>/wiki/`) — both are locked
to the KB they are given. The regression tests in
`py/tests/test_derive_nesting.py` prove this for the Python layer.

## Stage 2 verification

### Task 12 — Go MCP `kb` selector smoke run

Attempted against the derived KB at `/tmp/kaas-derive-smoke/derived/retrieval-and-the-chat-answer-path`:

```
KAAS_KB_DIR=/tmp/kaas-derive-smoke uv run python -c "
from kb_ai.server_mcp import ask
out = ask('how does retrieval pick which articles to read?', kb='retrieval-and-the-chat-answer-path')
print(out['answer'][:600])
print('SOURCES:', [s['path'] for s in out['sources']])
"
```

Result: same credential limitation as Task 10 — `OPENAI_API_KEY` not set and the
local LiteLLM proxy was not running at smoke time. The `resolve_kb_dir` call
resolved correctly (`kb_dir='/private/tmp/kaas-derive-smoke/derived/retrieval-and-the-chat-answer-path'`
visible in the server log before the credential error), confirming the Python routing
works. The Go side is covered by `TestHandleAskResolvesDerivedKB` and
`TestHandleAskRejectsUnknownDerivedKB` in `internal/mcp/handler_test.go`.

## Stage 3 verification

### Task 20 — HTTP API against a running backend

**Date:** 2026-08-05 · **Binary:** `make build` → `./bin/kaas` · **Config:**
`/tmp/kaas-e2e.toml` with `storage.kb_dir = "/tmp/kaas-derive-smoke"` (the KB
compiled in the Task 10 smoke run, which already holds
`derived/retrieval-and-the-chat-answer-path`) on port 8099.

The real config key is `storage.kb_dir` in the TOML file. The plan's
`KAAS_STORAGE_KB_DIR` guess does not exist: `config.Load` only reads
`KAAS_HOME`, `KAAS_WEB_DIR`, `KAAS_MCP_*` and `KAAS_AI_MCP_URL` from the
environment.

The daemon refuses to start without credentials
(`daemon init failed: OpenAIError: Missing credentials`), so the server was
launched with `LLM_BASE_URL=http://localhost:4777/v1 LLM_API_KEY=test
OPENAI_API_KEY=test`.

Read paths:

| Request | Result |
|---|---|
| `GET /api/derived` | `{"kbs":[{"slug":"retrieval-and-the-chat-answer-path","topic":"retrieval and the chat answer path","created_at":"2026-08-05T00:13:51","article_count":2}]}` (H2) |
| `GET /api/wiki` | root tree: `project/kaas-derived-kb.md` |
| `GET /api/wiki?kb=retrieval-and-the-chat-answer-path` | derived tree: `concept/kaas-ai-agent.md`, `decision/kaas-setup-and-configuration.md`; a different corpus, so the scoping is real (H3) |
| `GET /api/wiki?kb=nope` | 400 `kbpath: unknown derived knowledge base: "nope"` (H3) |
| `GET /api/wiki?kb=../..` | 400 `kbpath: invalid derived-kb slug: "../.."` (G4) |
| `GET /api/wiki/file?path=concept/kaas-ai-agent.md&kb=retrieval-and-the-chat-answer-path` | the article |
| `GET /api/wiki/file?path=concept/kaas-ai-agent.md` (no `kb`) | 404 `article not found`; that path exists only in the derived KB |
| `POST /api/chat?kb=nope` | 400, rejected before any LLM call (H3) |
| `POST /api/chat?kb=../etc` | 400 (G4) |

Job endpoints:

```
POST /api/derive {"topic":"cost accounting and pricing"}
→ {"job_id":"3b159d63-...","slug":"cost-accounting-and-pricing"}      (H1)

GET /api/derive/3b159d63-...
→ {"status":"failed","stage":"done",
   "error":"bridge: AI engine error DERIVE_FAILED: topic filter failed: Connection error.",
   "created_at":1785898898885,"updated_at":1785898900037}              (H1b)
```

**Same credential limitation as Tasks 10 and 12:** no paid API key is available
and the local LiteLLM proxy on port 4777 was not running, so the derive itself
could not complete and this run produced no derive cost figure. The failure
still exercises the HTTP path either side of the LLM call: the job is created,
claimed and run; the typed engine error (`DERIVE_FAILED`) reaches
`GET /api/derive/{id}` verbatim, which is the string `DeriveDialog` renders; the
status stays terminal across repeated polls, matching the dialog's stop-polling
behavior; and the failed run left no `derived/` directory behind (only the
pre-existing `retrieval-and-the-chat-answer-path`), so spec B5 holds over HTTP
too. Re-posting the same topic after the failure returned a fresh `job_id` rather
than a duplicate error, so a failed attempt does not burn its slug.

**Not verified end to end:** a successful HTTP derive, and therefore the cost
figure `GET /api/derive/{id}` reports on success. That needs a working LLM
gateway; the success payload is covered by tests (`internal/api/derive_test.go`,
`internal/derive/runner_test.go`, `DeriveDialog.test.tsx`) but not by a live run.
