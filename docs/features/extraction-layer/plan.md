# Make extraction a first-class layer — implementation plan

Date: 2026-08-07
Slug: `extraction-layer`
Spec: [spec.md](spec.md) · Alignment: [alignment-questions.md](alignment-questions.md)

**Goal:** give the per-document extraction a named directory (`extraction/`), a
path-mirrored filename, a provenance header, one serializer used by both
ingestion routes, and two independent gates in `compile` so a prompt edit costs
one extraction pass instead of a full recompile.

**Architecture:** one new Python module `storage/extraction.py` owns the file
format (serialize / parse / persist / load / staleness). `core/extract.py` gains
the prompt-set hash and the `EXTRACT_STAGE_PROMPTS` guard, because that is where
`load_prompt` and the type-split renderer already live. `KBStore` gains the
single path mapping. `commands/compile.py` splits into two gates.
`server_daemon._handle_extract` persists through the same module. Go carries
three new `ExtractRequest` fields and stops carrying the extraction blob.

## Global constraints

- **English only** in every artifact (see CLAUDE.md). Subagent prompts must
  repeat the rule.
- **No new dependency** in Python or Go. PyYAML and `_frontmatter` already exist.
- **No test may call a real LLM.** The only real run is Task 16.
- One `persist()`/`serialize()` pair, no second serializer anywhere (C1, C3).
- Test commands: `cd py && uv run pytest tests/ -q` · `go test ./... -count=1`.

## Stage 1 — the layer itself (A, B, C1–C2, C10–C11, G1–G6, H1–H5)

- [x] **T1. `KBStore.extraction_rel_path()` + `extraction_path()`** (A1–A6).
  Maps `raw/<rel>` → `extraction/<rel>` by replacing the first path segment, with
  no suffix arithmetic; rejects a rel that is not under `raw/`. No iterator: A5
  falls out of the mapping, since a document the raw scan skips is never handed to
  the layer. → verify: unit tests for nested paths, a `.md` name containing dots,
  a rejected non-`raw/` input, and a compile-level `_skipped/`/dotfile assertion.
- [x] **T2. `EXTRACT_STAGE_PROMPTS` + `extract_prompt_version()`** in
  `core/extract.py` (B11–B14). `load_prompt` asserts membership. The hash covers
  `extract`, `merge-summaries`, `summarize` and the five rendered `extract-types`
  variants enumerated from `TYPE_SPLIT_GROUPS_K2/K3`, NUL-and-length framed,
  truncated to 12 hex, memoized per process. → verify: H4's prompt-content case,
  a `TYPE_SPLIT_GROUPS_*` mutation case, H5's assert case, memoization.
- [x] **T3. `storage/extraction.py` serialize/parse round-trip** (B1–B7, C2).
  Frontmatter via `safe_dump`, five body sections in pinned order, `counts`
  guard, column-0 heading detection. → verify: H2's fixture matrix, including the
  `\n## Entities\n` value and the `---`-only summary line.
- [x] **T4. `split_frontmatter` closes on `rstrip()`** (B6a). → verify: existing
  `test_frontmatter.py` green plus one indented-`---` case.
- [x] **T5. `persist()` + `load()` + `is_stale()`** (B8–B10, B15–B17, C1).
  Atomic temp+`os.replace`; `load` returns `(parsed, reason)` and never
  invents an empty result; `_now_iso()` is UTC with `timespec="seconds"`.
  → verify: atomicity (no temp left behind), B9's three absent reasons, H4's
  staleness matrix including both `summarize_model` cases.
- [x] **T6. `extract_knowledge_summarized` raises when every chunk fails**
  (C10). → verify: a stubbed all-fail run raises; a partial failure still
  degrades; `if not chunks` still returns empty.
- [x] **T7. Two-gate `compile_kb`** (G1, G2, D1's CLI half). Extraction gate =
  missing-or-stale; write gate = `.compile-state.json`. Classify and write read
  `extraction/<rel>` off disk. → verify: a prompt-version change re-extracts and
  writes nothing; an unchanged KB does neither; the `completed_ops` resume branch
  still works.
- [x] **T8. `extract_only`** (G6): `compile_kb(extract_only=False)`,
  `run_compile` reads it from the payload, `distill` gains `--extract-only`.
  → verify: extraction runs, write phase does not, indexes still rebuild.
- [x] **T9. Wiki-lag report** (G5) — per-file `prompt_version` in the compile
  state, and a first-run explanation instead of a bare count. → verify: a state
  entry without `prompt_version` reports the first-run reason; a stale one
  reports the count.
- [x] **T10. Revised-document report** (C11) — extraction distinguishes a first
  write from an overwrite, and the write phase names the articles those documents
  merged into. → verify: a revised document lists its articles; a new one does
  not appear.

## Stage 2 — write-path parity (C3–C9, D1's worker half, H3, H6)

- [x] **T11. `ExtractRequest` gains `kb_dir`, `source`, `model`; worker sends a
  relative `source_ref`** (C4, C5). One `filepath.Rel` feeding both requests.
  → verify: Go table test on the request fields; `SourceRef` is relative.
- [x] **T12. `_handle_extract` normalises newlines, reads before extracting,
  persists, fails on write error** (C3, C6–C9). → verify: H6's two CRLF tests,
  a fresh-file no-LLM-call test, a write-failure error response.
- [x] **T13. `PipelineItem.Extraction` dropped; the pipeline loads
  `extraction/<rel>` from `source_ref`** (D1). → verify: pipeline integration
  test with an on-disk extraction; a missing one is an item error.
- [x] **T14. H3 parity test** — both routes in one process, `_now_iso`
  monkeypatched, byte-identical files.

## Stage 3 — reads get simpler (E, F)

- [x] **T15. Catalog reads `extraction/<rel>`; derive copies it; the old cache
  API is deleted** (E1–E4, F1–F8). Includes `derive/_status.py` with the F3 and
  F5 checks and the `commands/derive.py` copy fix. → verify: catalog summary
  from an extraction file; a never-compiled KB still builds a catalog; copy skips
  a checksum mismatch and reports it; F5 classifies in-sync/changed/gone/unknown.

## Stage 4 — smoke run and notes (G8, H7, H8)

- [x] **T16. Real run** — done 2026-08-08, 17.6931 USD spent. `cp -R` backup
  first, then extract `data/kb-2026-06` from scratch, rebuild the document index,
  derive one topic, run the F5 check over the seven existing derived KBs, and
  record everything in `notes.md`. Extract cost 17.4280 USD against the 17.4541
  baseline (−0.15%); the document-index comparison had no baseline to run
  against. See [notes.md](notes.md#stage-4--run-on-2026-08-08).
