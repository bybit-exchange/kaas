# Derive a topic-scoped knowledge base from the catalog

Date: 2026-08-04
Slug: `derive-topic-kb-from-catalog`
Brainstorm: [brainstorm.md](brainstorm.md)

## Background

A KaaS knowledge base compiled from a broad corpus answers across everything it
ingested. There is no way to carve out the part about one topic and hand that
over as a knowledge base in its own right.

Two pieces already exist. The catalog (`index/master-index.md`) holds a one-line
summary per article plus, for reference articles, the key names their tables
define — parsed by `KBStore.existing_articles()` into `ArticleMeta`
(`py/src/kb_ai/storage/store.py:170`). And `_select_relevant`
(`py/src/kb_ai/retrieval/retrieve.py:42`) already asks an LLM which catalog lines
are relevant to a query, though ranked and capped for question answering.

What is missing is turning a filter result into a new, compiled knowledge base.
The chain that makes it possible is `sources:` in each article's frontmatter
(written by `core/merge.py:441`, maintained by `apply_diff` at
`core/merge.py:294-325`): a list of `raw/*.md` paths inside the same KB holding
the un-compiled documents the article was built from.

```
catalog line ──filter(LLM)──▶ wiki/pricing-model.md
                                  │ sources:
                                  ▼
              <kb>/raw/notes__q3-review.md   (un-compiled)
                                  │ copy, deduped
                                  ▼
              <kb>/derived/pricing/raw/ ──▶ compile_kb()
                                  ▼
              <kb>/derived/pricing/{wiki,index}/ + manifest.json
                                  │ second filter pass
                                  ▼
              off-topic articles ──▶ derived/pricing/_offtopic/
```

## Goals

1. Given a source KB and a topic string, produce a new compiled knowledge base
   at `<source-kb>/derived/<slug>/` containing only the documents behind the
   articles that match the topic.
2. Make the derived KB a first-class KB: its own `raw/`, `wiki/`, `index/`,
   readable by the existing retrieval, MCP `ask`, and wiki-browsing paths.
3. Record provenance so a derived KB can be audited: what it came from, what
   matched, what was skipped and why.
4. Expose it on three surfaces: the Python CLI creates derived KBs, MCP `ask`
   reads them, and the HTTP API + web UI do both.

## Non-Goals

- Re-deriving or incrementally refreshing a derived KB when the source changes.
  A derived KB is a snapshot.
- Full multi-KB support in the Go service (registering N independent KBs,
  per-KB worker/queue/session state). Derived KBs are reached through a selector
  on existing read paths.
- Changing the shared compile prompts (`core/extract.py`, `core/merge.py`) to be
  topic-aware.
- Deriving from anything that is not an already-compiled KaaS KB with an
  `index/master-index.md`.
- Deriving from a derived KB (nesting beyond one level).
- Creating a derived KB over MCP. Agents read derived KBs; they do not build
  them.
- Editing a derived KB and pushing changes back to the source.

## User stories / scenarios

**S1 — Operator scopes a KB for a team.** A 200-article KB covers pricing,
compliance and infrastructure. The operator runs
`kb-ai derive "pricing and fee structure" --kb ./.kaas`, gets
`.kaas/derived/pricing-and-fee-structure/` compiled from only the documents
behind pricing articles, and points that team's MCP registration at it.

**S2 — Agent answers from a derived KB over MCP.** An agent asked about
compliance calls `ask` with `kb: "compliance"` and gets an answer grounded only
in that slice, instead of navigating the whole corpus catalog. Creating the
derived KB is the operator's job (CLI or web UI); the agent cannot spend money
by deriving one.

**S3 — Operator inspects what got left out.** After deriving, the operator reads
`manifest.json` and sees three matching articles were skipped because they had
no `sources:`, and four compiled articles were moved to `_offtopic/` because the
documents that carried them were broader than the topic.

**S4 — Operator browses a derived KB in the web UI.** The wiki view has a KB
selector listing the root KB plus each derived KB; picking one shows that KB's
article tree and chatting queries that KB's catalog.

## Acceptance criteria

### A. Topic filter

- A1. `select_by_topic(catalog, topic, model)` returns every catalog path the
  LLM judged relevant, with no top-K cap, filtered to paths present in the
  catalog and de-duplicated preserving order.
- A2. Empty catalog returns `[]` without an LLM call.
- A3. An LLM error propagates as a `DeriveError` — derive must fail loudly
  rather than degrade to `[]` the way retrieval does, because an empty
  selection would silently produce an empty KB.
- A4. Model-invented paths absent from the catalog are dropped, and the count of
  dropped paths is recorded in the report.
- A5. The prompt includes the `| keys:` column when an article has one, so a
  topic naming a specific setting reaches the reference article defining it.
- A6. A catalog whose rendered listing exceeds the prompt budget is split into
  budget-sized batches, each filtered independently, and the results unioned.
  Ordering within a batch is irrelevant — there is no top-K cap, so the filter
  needs the union, not a global ranking.
- A7. Batching is transparent to the caller: one batch and ten batches return
  the same shape. The batch count is recorded in the report so a run's cost is
  explainable.
- A8. A single catalog line too long to fit its own batch is dropped and
  recorded as skipped rather than making the run unschedulable.

### B. Document resolution

- B1. For each selected article, the `sources:` frontmatter list is parsed and
  its entries collected into a de-duplicated union across all selected articles,
  in stable sorted order.
- B2. A selected article with no `sources:` key, an empty list, or unparseable
  frontmatter contributes nothing, and is recorded in the report and manifest
  with `reason` distinguishing those three cases.
- B3. A `sources:` entry that escapes the source KB (absolute path, `../`,
  symlink out) is rejected via `KBStore.read_raw` → `_resolve` and recorded as
  skipped; it must not abort the run.
- B4. A `sources:` entry naming a file that no longer exists is recorded as
  skipped and does not abort the run.
- B5. Zero resolvable documents across all selected articles fails with
  `NO_DOCUMENTS` and creates no derived directory.

### C. Derived KB creation

- C1. The derived KB is created at `<source-kb>/derived/<slug>/` with `raw/`
  populated by the resolved documents, each keeping its source-relative name so
  provenance stays legible.
- C2. `slug` comes from `--slug` when given, else is derived from the topic:
  lower-cased, non-alphanumeric runs collapsed to `-`, trimmed of leading and
  trailing `-`, truncated to 40 characters.
- C3. A slug that is empty after normalisation, or that is not a single path
  segment (contains `/`, or is `.` or `..`), fails with `INVALID_SLUG`.
- C4. An existing `derived/<slug>/` fails with `SLUG_EXISTS` unless `--force` is
  given, in which case it is replaced.
- C5. Deriving from a KB that is itself under a `derived/` directory fails with
  `NESTED_DERIVE`.
- C7. While copying each document, the source KB's
  `.extract-cache/<checksum>.json` entry is copied too when it exists, so the
  derived compile reuses the extraction already paid for. The cache keys on
  content checksum (`store.py:202`) and the copies are byte-identical, so the
  keys match. A missing entry is not an error. Entries are copied, not
  symlinked, so deleting the source KB cannot invalidate the derived one.
- C6. After creation, the source KB's own compile and index are unaffected: a
  subsequent `compile_kb` on the source neither re-compiles the derived
  documents nor lists derived articles in the source catalog. (Verified against
  `KBStore._iter_raw_paths` globbing `<base>/raw/**`, `update_markdown_index`
  globbing `<base>/wiki/**`, the Go wiki walker rooted at `KBDir/wiki`
  (`internal/api/wiki.go:170`), and every Go raw write being
  `filepath.Join(KBDir, "raw", …)`.)

### D. Compile and second filter pass

- D1. The derived KB is compiled by the existing `compile_kb(derived_dir, …)`
  with no change to the pipeline or its prompts.
- D2. After compiling, the same topic filter can run over the *derived* catalog.
  Articles it does not select are moved (not deleted) to
  `derived/<slug>/_offtopic/`, preserving their relative path under `wiki/`.
  **Opt-in, off by default** (`--prune`). The two runs that have measured this
  pass moved 0.83 and then 0.00 of the derived catalog — too strict, then
  selecting nothing at all — so it has no demonstrated working regime and does
  not earn a place in the default output. It stays available as an instrument.
  See issue #24.
- D3. `update_markdown_index` is re-run after the move, so the derived catalog
  lists only on-topic articles.
- D4. `_offtopic/` is excluded from the derived KB's own indexing and retrieval
  (it is outside `wiki/`, so this follows from C6's mechanism).
- D5. If the second pass selects every derived article, no `_offtopic/`
  directory is created.
- D6. If the second pass selects *no* derived article, the run completes with
  every article left in place and a `second_pass_selected_nothing` warning in
  the report — an empty derived wiki is worse than an unfiltered one.
- D7. The documents behind moved articles stay in the derived `raw/`; they are
  what the articles were compiled from and removing them would make the
  derived KB's own re-compile lossy.

### E. Manifest

- E1. `derived/<slug>/manifest.json` is written before compiling, so a run that
  dies mid-compile still records what it intended.
- E2. It contains: `schema_version`, `source_kb` (absolute path), `topic`,
  `slug`, `created_at`, `filter_model`, `selected_articles`
  (`[{path, title, sources}]`), `skipped_articles` (`[{path, reason}]`),
  `documents` (`[{rel_path, checksum}]`), and `dropped_invented_paths`.
- E3. After the second pass it is updated with `offtopic_articles` and
  `compile` (the `compile_kb` result summary, including cost).
- E4. Checksums use the same 16-hex-char SHA-256 prefix as
  `store._compute_checksum`, so a later re-derive feature can compare against
  source-KB state.

### F. Python CLI

- F1. `kb-ai derive <topic> --kb <dir> [--slug s] [--force] [--model m] [--yes]
  [--prune] [--select-from articles|documents]` registered in
  `__main__.COMMANDS` alongside `distill`. `--prune` is the only way to reach the
  D2 pass. `--select-from` picks the catalog to filter and defaults to
  `articles`; `documents` filters `raw/` directly, which is the only mode that
  works on a knowledge base that was never compiled.
- F2. On success responds `ok:true` with `{derived_kb, slug, topic, selected,
  skipped, documents, bytes, offtopic, filter_batches, dropped_invented_paths,
  compiled, compile, cost, warnings, next}`, where `next` is the command to
  register the derived KB over MCP. `selected` counts whichever unit the filter
  ran over, so under `--select-from documents` it counts documents — the article
  list is empty by design in that mode, and reporting it there would always say
  0. Unlike the HTTP path (H5), `offtopic` is live here: `--prune` can make it
  non-zero.
- F3. On every failure above responds `ok:false` with the named error code and a
  message naming what to fix.
- F4. `--kb` defaults to `./.kaas`, matching `distill`.
- F5. **Volume gate.** After resolving documents and before compiling, the CLI
  reports articles matched, documents resolved and their total bytes, then stops
  unless `--yes` was given (or, on a TTY, the operator confirms). No cost figure
  is shown: there is no pre-compile estimator, and a guessed one would be worse
  than none. Declining exits `ok:true` with `compiled:false` and leaves the
  derived `raw/` and `manifest.json` in place, so `--force` re-runs cheaply.
- F6. Actual cost is reported after the run from the existing `CostTracker`
  totals returned by `compile_kb`, and written to the manifest (E3).

### G. MCP

MCP is read-only in this feature: agents can query a derived KB but cannot
create one. Deriving writes files and spends money, so it stays behind the CLI
and the operator-facing HTTP surface. (Was G1/G2 — dropped by decision O2.)

- G3. The `ask` tool gains an optional `kb` parameter naming a derived KB slug;
  omitted means the root KB. An unknown slug is a clear error, not a silent
  fallback to the root KB.
- G4. `kb` is validated as a single path segment against the set of directories
  under `derived/` before use — it reaches the server from an MCP client.

### H. HTTP API and web UI

- H1. `POST /api/derive` `{topic, slug?, model?, select_from?}` records the job
  in a dedicated `derived_jobs` table and returns a job id; it does not block on
  the compile. An unknown `select_from` is rejected with 400; omitting it is
  accepted, and the Python side supplies the default rather than the Go handler
  restating it.
  Not the existing `Task` queue: `Task` is document-shaped (`RawPath`, uniquely
  indexed `ContentHash`) and `Worker.Process` runs one document through
  extract → pipeline, so re-deriving a topic would collide with `ErrDuplicate`.
  See tech-design "The queue problem".
- H1b. `GET /api/derive/{id}` reports the job's status, stage, error and result
  (cost and counts).
- H2. `GET /api/derived` lists derived KBs read from their manifests:
  `[{slug, topic, created_at, article_count}]`.
- H3. `GET /api/wiki`, `GET /api/wiki/file` and the chat path accept
  `?kb=<slug>`; omitted means the root KB. The value is validated by the same
  containment rule as G4 and rejected with 400 when unknown.
- H4. The wiki view has a KB selector listing the root KB plus each derived KB;
  selecting one scopes both the article tree and chat to that KB.
- H5. The derive action in the UI surfaces progress through the existing task
  status mechanism, and reports the run's actual cost on completion. The HTTP
  path has no volume gate — it is async, so there is no prompt to answer; F5's
  gate is a CLI affordance only. It also exposes no `--prune` equivalent, so the
  D2 pass never runs behind the API and the completion summary does not report an
  off-topic count: it could only ever be 0. The response carries no such key
  either, dropped rather than published as a constant (issue #35) — restoring the
  count means restoring the field along with it.
- H6. i18n: every new UI string has both `en` and `zh` entries in
  `web/src/i18n/strings.ts`.

### I. Verification-level criteria

- I1. Every criterion above is covered by a test that does not call a real LLM:
  the filter is injected or monkeypatched, as `retrieval` tests already do.
- I2. One end-to-end test derives from a fixture KB (hand-written catalog,
  articles with `sources:`, raw documents) with a stubbed filter and a stubbed
  compile, asserting the resulting directory layout and manifest.
- I3. A real smoke run against a KB compiled from this repository, with its
  output recorded in the feature's `notes.md`: topic, articles selected,
  documents resolved, articles moved off-topic, and total cost.

## Resolved questions

- **O1 — catalog exceeds the prompt budget.** *Resolved: batch in v1* (A6–A8).
  A catalog line can reach ~800 chars (`SUMMARY_MAX_CHARS=200` +
  `KEYS_MAX_CHARS=500` + path and title), so `MAX_PROMPT_CHARS` (80K, from
  `llm/_infra.py:26`) is reached somewhere near 100 articles — well inside the
  size of a KB worth slicing, and the 48-article self-compile referenced in
  `storage/index.py` is already halfway there. Failing on the motivating case
  was not acceptable. Batching is cheap here because there is no top-K cap: the
  batches only need unioning, not global ranking.
- **O2 — MCP `derive`.** *Resolved: dropped.* MCP stays read-only (G3, G4).
  Removes the config flag, its two-state tests, and the spend surface.
- **O3 — cost control before compiling.** *Resolved: volume gate in the CLI*
  (F5), actual cost reported after (F6, E3). Gating on documents and bytes
  rather than USD, because no pre-compile cost estimator exists —
  `_cost.py:111` `estimate_cost()` prices one call after the fact, and the
  "estimate path" referenced at `commands/compile.py:81` points at a plan
  document absent from this repository. A per-byte constant would have to be
  measured, not guessed. The `raw/_skipped/` approval mechanism was not reused:
  it is built around the root KB's raw dir.
- **O5 — reviewing `_offtopic/`.** *Resolved: manifest only for v1.* The move is
  non-destructive and `offtopic_articles` (E3) names everything moved; a restore
  affordance waits for evidence anyone wants it.

## Open questions

- **O4.** Does the second filter pass (D2) reuse the first pass's prompt
  verbatim? The first pass judges summaries written for a broad corpus; the
  second judges summaries of freshly compiled topic-scoped articles, where
  nearly everything will look topical. Too permissive and the pass does nothing;
  too strict and it strips the KB's periphery. To be settled in the tech design,
  and measured in the smoke run (I3) — D6 is the backstop that keeps a
  mis-tuned pass from emptying the wiki.

## Implementation sequencing

All three surfaces are in scope. The plan orders them so each stage is
verifiable before the next begins:

1. **Python core + CLI** (A–F, I1–I3). Complete and useful on its own; ends with
   a real smoke run against a KB compiled from this repository.
2. **MCP `ask` kb selector** (G3, G4). Read-only, small, depends only on the
   derived-KB layout that stage 1 establishes.
3. **HTTP API + web UI** (H1–H6). Largest stage and the only one spanning Go and
   TypeScript; depends on both stages above.
