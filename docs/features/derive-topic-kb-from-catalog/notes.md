# Derive Topic KB — Implementation Notes

## C6 verification

The nesting-is-inert property rests on two glob roots never reaching `<kb>/derived/`.
The Go side was spot-checked with:

```
grep -rn 'filepath.Join(.*"raw"' internal/
grep -rn '"wiki"' internal/api/wiki.go
```

The output of both greps, and what it proves, is under "Raw writes" and
"Wiki walker" below.

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

### Wiki walker — rooted at `filepath.Join(kbDir, "wiki")`

As of Task 17 both walk roots take the KB directory from `resolveKB`, not from
the config:

```
internal/api/wiki.go:222:  wikiDir := filepath.Join(kbDir, "wiki")
internal/api/wiki.go:319:  wikiDir := filepath.Join(kbDir, "wiki")
```

This section originally read that a derived KB at `<kb>/derived/<slug>/wiki/` is
"unreachable". That is no longer true, and putting it that way confused what C6
actually claims. After Task 17 a derived KB is deliberately reachable, but only
through an explicit `?kb=<slug>`. What C6 needs is narrower and still holds: a
request that does not carry `?kb=` walks `<kb>/wiki`, never `<kb>`, so a nested
derived KB stays invisible to the source KB's own tree.

The same isolation holds for the Python side: `KBStore._iter_raw_paths` globs
`self.raw_dir` (`<base>/raw/`), and `update_markdown_index` globs
`store.wiki_dir` (`<base>/wiki/`) — both are locked to the KB they are given.
The regression tests in `py/tests/test_derive_nesting.py` prove this for the
Python layer.

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
than a duplicate error.

**Qualification added after code review:** that last observation held only
because this particular run failed at the *topic filter*, before `create()`. A
failure after directory creation leaves a `manifest.json` behind, and the
original code then refused the slug forever — `kbpath.Resolve` succeeded, so
every retry got 409 and the only escape was `rm -rf` or the CLI's `--force`. The
post-`create()` window was untested on every surface. It is now closed: an
uncompiled derived KB is replaceable (the runner sets `Force` when the target
exists with `compiled: false`) and is excluded from `GET /api/derived`, so it can
no longer be selected into an empty corpus either.

**Not verified end to end:** a successful HTTP derive, and therefore the cost
figure `GET /api/derive/{id}` reports on success. That needs a working LLM
gateway; the success payload is covered by tests (`internal/api/derive_test.go`,
`internal/derive/runner_test.go`, `DeriveDialog.test.tsx`) but not by a live run.

## Known gaps at merge

Raised in the end-of-branch code review and accepted rather than fixed. Item 1
started as a gap and is now a measurement; the result it produced is itself the
open question.

### 1. The move ratio is now measured, and it says the design needs work

The Stage 1 checkpoint was finally met on 2026-08-05, after a working gateway
turned up (`litellm-de.yijin.io`, model `us.claude-sonnet-4-6`). Superseded
reading: the earlier smoke run reported 0/0 and this section previously said the
number did not exist.

Corpus: this repository's own docs distilled into a fresh KB
(`kb-ai distill docs + the root markdown`), 16 source documents, 8 articles.
Topic: `the compile pipeline and retrieval`, run with `--yes` over the CLI.

| Figure | Value | Where it came from |
|---|---|---|
| Source articles in catalog | 8 | `index/master-index.md` |
| Articles selected by RECALL | 5 | `data.selected` |
| Invented paths dropped | 0 | `data.dropped_invented_paths` |
| Documents resolved | 14 of 16 | `data.documents` |
| Bytes recompiled | 384,825 of ~408,000 | `data.bytes` |
| Articles in derived catalog | 6 | derived `wiki/` before the PRECISION pass |
| Articles moved off-topic | 5 | `data.offtopic` |
| **Move ratio** | **5/6 = 0.83** | derived from the two rows above |
| Total cost | 0.770637 USD | `data.cost.total_cost_usd` |
| Filter cost (RECALL + PRECISION) | ~0.007 USD | total minus the compile phases |
| Recompile cost | 0.764 USD | `data.compile.timing.phases` |
| Extract cache hits | 14 of 14, 0.00 USD | compile log, phase 1 |
| Wall clock | 1046s | `data.compile.timing.total_seconds` |

Reading, against the tech design's own rule that near 0 means too permissive and
near 1 means too strict: 0.83 says **too strict**, and inspecting the moved
articles confirms at least one outright false negative.
`concept/kaas-non-determinism.md` — "classify-phase cascading LLM variance
causes identical 88-file input to produce 48 vs 98 articles, root cause in
`_phase_classify.py`" — is entirely about the compile pipeline and was moved
aside. `decision/kaas-derive-topic-kb.md` is borderline for the same reason. The
three genuinely off-topic moves (backlog, contributing guide, bootstrap guide)
were correct.

The more important finding is structural, and it is about RECALL rather than
PRECISION. Filtering at the article level and then resolving to source documents
amplifies scope badly, because articles merge several sources and sources are
shared between articles: 5 of 8 articles resolved to 14 of 16 documents, which is
94% of the corpus by bytes. So the run paid to recompile almost the entire corpus
in order to keep one article out of six. The filter itself was nearly free
(~0.007 USD of 0.77); essentially all the money went to the recompile the
amplification caused. That is the trade-off brainstorm decision 1 chose, and
`tech-design.md` says to revisit that decision if the ratio came out bad. It did.

Sample size, stated plainly: one topic, one corpus, six derived articles. This is
directional evidence that PRECISION is too strict and that article-level RECALL
over-resolves. It is not a distribution, and a 6-article catalog can misrepresent
even the sign of an effect. Before changing the design, run several topics across
a corpus large enough that the derived catalog is tens of articles, not six.

Two operational observations from the same run:

- One write-phase call stalled for 901s, hit the client timeout, and was retried
  successfully (`[LLM-WARN] api_timeout_error ... elapsed=901.3s`). It alone was
  most of the 1046s wall clock. A 14-document recompile taking 17 minutes is
  worth knowing before anyone points derive at a large KB.
- C7's extract-cache copy works as designed: all 14 documents hit the cache, so
  extract cost 0.00 USD. Without it this run would have cost several times more.

Still outstanding:

- Task 12 Step 7 — a grounded answer from a derived KB *through MCP*. The
  retrieval path underneath it is now proven (see the HTTP section below), so
  what is left unexercised is the MCP `kb` selector end to end, which has Go
  unit coverage but no live run.

Closed since: Task 10 Step 3 (the declined-volume-gate path, exercised eight
times by the sweep below) and Task 20 Step 7 (a successful derive over HTTP).

#### Re-measured on a larger corpus, 2026-08-05: PRECISION is now off by default

The section above asked for "several topics across a corpus large enough that the
derived catalog is tens of articles, not six" before changing the design. That was
run. Source KB: this repository's own source distilled fresh, 88 documents,
428,646 bytes, 52 articles. Model `us.claude-sonnet-4-6` through the same gateway,
`temperature=0`.

The volume gate makes the RECALL half measurable without paying for a recompile:
with no TTY and no `--yes` it reports articles matched, documents resolved and
bytes, then stops. Eight topics at roughly 0.02 USD each:

| topic | articles | documents | corpus bytes | amplification |
|---|---|---|---|---|
| retrieval and chat answer path | 24/52 | 59/88 | 56.2% | 1.22x |
| circuit breaker and failure handling | 10/52 | 26/88 | 34.4% | 1.79x |
| configuration and environment variables | 16/52 | 51/88 | 55.6% | 1.81x |
| the web user interface | 18/52 | 33/88 | 42.2% | 1.22x |
| Go task queue and worker lease | 12/52 | 27/88 | 39.7% | 1.72x |
| MCP server integration | 18/52 | 51/88 | 57.3% | 1.66x |
| classify phase and article taxonomy | 17/52 | 45/88 | 54.0% | 1.65x |
| cost tracking and pricing | 14/52 | 45/88 | 52.8% | 1.96x |

Mean amplification 1.63x, median 1.69x, range 1.22-1.96x. 1 filter batch and 0
invented paths every time.

This corrects the reading above. The amplification *factor* replicated — 1.50x
there sits inside 1.22-1.96x here — but the 94%-of-corpus figure did not, and it
was the alarming part. An 8-article catalog forced a topic to select 62.5% of
articles; a 52-article catalog selects 31% and resolves 49% of bytes. So "the run
paid to recompile almost the entire corpus" is a small-corpus artefact rather than
a property of article-level filtering, and the case for revisiting brainstorm
decision 1 is weaker than this section concluded.

PRECISION is the half that did not survive. One paid run, topic
`the web user interface`, 33 documents, 22 derived articles, 2.011101 USD:

```
offtopic: 0
warnings: ["second_pass_selected_nothing"]
```

Move ratio 0.00 against 0.83 in the run above — too strict, then selecting
nothing at all. The `_offtopic.py:43-45` guard is right to refuse to act on an
empty selection ("An empty derived wiki is worse than an unfiltered one"), but the
pass was paid for and contributed nothing. Two runs, two degenerate extremes, no
useful middle observed.

So the pass now ships off, reachable with `kb-ai derive --prune`, and the default
output is RECALL-only. It is kept rather than deleted because it is also the
instrument needed to decide whether a working regime exists. Tracked in issue #24.

Two further findings from the same run, both filed:

- The derived compile did not inherit the source KB's frozen category set, so a
  KB built with `--categories` got a derived KB under the defaults (issue #25,
  fixed here).
- Another 901.7s write-phase stall, timed out and retried, dominating wall clock
  at 967.75s of 1127.55s total. Two derive runs, two stalls (issue #26).

Worth knowing even when the category sets match: a derived KB is recompiled from
an empty existing-articles context, so its distribution does not resemble its
source's. Same run — source `concept 36, reference 8, decision 6, guide 2` against
derived `reference 12, decision 9, project 1, concept 0`.

#### Task 20 Step 7 — derive over HTTP, 2026-08-06

The last unproven path. Backend built from this branch, SQLite store, `kb_dir`
pointed at a copy of the 52-article KB above, Python daemon spawned by the
backend (`[multiplex-stream] process ready`), LLM credentials by environment.

```
POST /api/derive {"topic":"the circuit breaker and failure handling","slug":"cb-http"}
  -> 202 {"job_id":"ee5d4bda-...","slug":"cb-http"}
GET  /api/derive/ee5d4bda-...
  -> running, stage=compile
  -> succeeded, stage=done
GET  /api/derived
  -> [{"slug":"cb-http", "topic":"...", "article_count":27}]
```

| Figure | Value |
|---|---|
| Articles selected by RECALL | 11 of 52 |
| Documents resolved | 30 of 88 |
| Bytes recompiled | 183,524 |
| Articles in the derived KB | 27 |
| Moved off-topic | 0 (pruning off by default) |
| Errors | 0 |
| Total cost | 3.007176 USD, 81 calls |
| extract | 0.0s, 0.00 USD (cache hit) |
| classify | 136.53s, 0.2533 USD |
| write | 986.65s, 2.7332 USD |
| Wall clock | 1123.2s |

Four things this pins down.

The job lifecycle works: 202 with a job id, `stage` advancing through `compile`
to `done`, and `GET /api/derived` reporting the finished KB with its article
count. Nothing sat at "pending".

The new default holds over HTTP. `offtopic: 0` with no `_offtopic/` directory —
and this time because pruning is off, not because the PRECISION pass selected
nothing. The daemon takes no `prune` switch, so the API cannot reach the pass.

The category set was inherited: the derived `kaas.json` carries the source's six
rather than re-freezing the default. That is the #25 fix on the path that
motivated it.

The stall recurred, making it three derive runs and three stalls: 901.2s,
`prompt_chars=6219`, timed out and retried successfully. One detail for issue #26
— it appears only in the backend's daemon-stderr passthrough, not in the derived
KB's own `.compile.log`, so the obvious place to look for it is the wrong one.

Two observations that are not defects but affect how the numbers above should be
read.

A grounded answer out of the derived KB, asked directly of the retrieval layer:
"What is the circuit breaker failure threshold and cooldown, and what happens to
calls while it is open?" returned 5 consecutive failures and 30 seconds with the
correct open-state behaviour, 6 articles retrieved, 3 cited, 0.057897 USD. So a
derived KB is answerable, which is the point of deriving one.

RECALL selection is not reproducible run to run. The same topic over the same
catalog at `temperature=0` selected 10 articles and 26 documents during the sweep
above and 11 articles and 30 documents here. One comparison only, so treat the
sweep's figures as accurate to about one article rather than exact — the
amplification conclusion is unaffected at that resolution, but this is worth
knowing before anyone quotes a single row of that table as a fixed number.

### 2. A long derive cannot be cancelled

`internal/bridge/daemon_protocol.go`'s `call` returns on `ctx.Done()` without
sending a `cancel` request — unlike `stream`, which does — and the Python daemon
only registers cancel events for `STREAMING_COMMANDS` (`chat`,
`pipeline-stream`). `derive` is neither, so there is nothing to cancel even if
Go asked.

Consequence: on the runner's 2-hour ceiling, or on a SIGTERM (the bridge call
context deliberately derives from the run context, so shutdown aborts a paid
derive rather than blocking), Go marks the job `failed` while Python keeps
deriving — continuing to spend LLM budget invisibly and holding one of the
daemon's 8 worker slots until it finishes on its own.

The wedged-slug half of this trap is fixed (see the qualification under Task 20).
What remains is the wasted spend on an abandoned run. Closing it properly means
registering a cancel event for non-streaming commands and checking it between
derive phases, on both sides of the protocol — deliberately out of scope for this
branch.

### 3. Single-instance assumption

`RecoverRunningDerivedJobs` fails every row with `status='running'` at startup,
with no owner id and no lease, unlike the `tasks` table in the same package. Two
`kaas` processes sharing one SQLite file would therefore fight: the second's
startup recovery marks the first's in-flight derive failed, and the claim hands
the slug out again. Single-instance is an assumption, now stated in the doc
comments on `RecoverRunningDerivedJobs` and `Runner`, not an enforced invariant.

## Errata — where the design docs no longer match the code

`spec.md` and `tech-design.md` are historical records and have been left as
written. Where the shipped behaviour differs, the code is right and the doc is
stale:

- **`spec.md` H5** says the UI surfaces progress "through the existing task
  status mechanism". It uses a dedicated `derived_jobs` table and
  `GET /api/derive/{id}` polling instead — which is exactly what
  `tech-design.md` later decided (Option A). The spec is the stale document.
- **`spec.md` F5** says `--force` "re-runs cheaply". There is no resume path:
  `--force` deletes `derived/<slug>/` and starts over, so the topic filter runs
  again at real cost and documents are re-resolved and re-copied. Only the source
  KB's extract cache is reused. The CLI string that repeated this claim has been
  corrected.
- **`tech-design.md`** describes the Go slug check as lexical, with symlink
  resolution only on the Python side. `kbpath.Resolve` does both: `filepath.Abs`,
  `filepath.EvalSymlinks`, then a boundary-aware containment check. The two
  layers now agree, which is what made the Python read path's weaker
  `is_relative_to` check (fixed in review) visible as a divergence.
- **`tech-design.md`** promises a fixed reason vocabulary for machine
  readability. `_offtopic.prune` adds `path_escapes_derived_dir`,
  `dest_escapes_derived_dir` and `dest_already_exists`, so the `warnings`
  vocabulary is open rather than closed.
- **`tech-design.md`'s skip-reason table** lacks `not_a_raw_document`, added in
  review. A `sources:` entry that resolves inside the KB but outside `raw/` is
  now skipped rather than copied: `sources: wiki/pricing.md` would otherwise
  inject an article the derived compile never wrote, and
  `sources: .compile-state.json` would hand the derived KB the source KB's
  compile state and leave it silently empty. `sources:` is LLM-written
  frontmatter, so it is the one input in this pipeline that must be treated as
  hostile.
- **`spec.md` E2** lists fewer manifest fields than are written. The manifest
  also carries `skipped_documents`, `compiled`, `cost` and `warnings` — a
  superset, and `compiled` is now load-bearing for the Go listing and retry
  paths.
