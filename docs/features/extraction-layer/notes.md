# Extraction layer — implementation notes

Date: 2026-08-07, Stage 4 run 2026-08-08
Spec: [spec.md](spec.md) · Plan: [plan.md](plan.md) · Alignment:
[alignment-questions.md](alignment-questions.md)

Stages 1–3 are implemented and verified offline. Stage 4 — the real extraction run
over `data/kb-2026-06` — was approved and ran on 2026-08-08; its outcome is
recorded at the end of this file.

## Verification

| Suite | Result |
|---|---|
| `cd py && uv run pytest tests/ -q` | 1407 passed, 1 skipped, 1 xfailed |
| `go test ./... -count=1` | all packages ok, `go vet ./...` clean |
| `cd web && pnpm test` | 454 passed (38 files) |
| Python coverage | 99% overall; `storage/extraction.py` 100%, `derive/_status.py` 100%, `commands/compile.py` 99% |

No test calls a real LLM.

## Measurements taken during implementation

All against the reference KB at `data/kb-2026-06`, which still held its
pre-change `.extract-cache/` when these were taken. The Stage 4 run re-measured
the round-trip, the layer size and the gate cost against real files rather than
replayed cache payloads; where the two differ, the Stage 4 figure is the one to
quote.

**The serializer round-trips every real extraction.** All 108 cache entries were
parsed into `ExtractionResult`, serialized through `storage.extraction.serialize`
and parsed back: **0 round-trip failures**, field for field. This is the check the
hand-written H2 fixtures cannot give — real LLM output, CJK-dense, with whatever
punctuation the model actually emitted.

**The layer is slightly smaller than the cache it replaces**: 2.14 MB of markdown
against 2.54 MB of JSON for the same 108 payloads.

**The `rstrip()` change to `split_frontmatter` (B6a) changes no existing verdict.**
Compared old (`strip()`) against new (`rstrip()`) over every file with
frontmatter in the reference KB and its seven derived KBs — 353 files, wiki
articles and raw documents: **0 differences**. So the change is a strict
improvement on the malformed case and a no-op on everything on disk.

**The extraction gate costs 1.05 s over 108 documents** (full parse), against
0.12 s for a frontmatter-only read. The full parse is deliberate: it is what makes
a count-mismatched body count as absent (B9) and re-extract, where a header-only
gate would leave such a file permanently unusable — the gate would call it fresh
and the write phase would then refuse it, forever. Scales linearly, so budget
~10 s at 1000 documents against an extraction phase measured at 720 s for 108.

## Decisions made while implementing, beyond what the spec fixed

1. **`current_prompt_version()` wraps `extract_prompt_version()`** in the
   extraction layer, and the compile gate calls the wrapper rather than importing
   the hashing function directly. Two module-level bindings for the same value
   would have to agree by convention; one binding cannot drift.
2. **`load_header()` exists alongside `load()`** (B7). The document catalog and
   derive's copy check read the frontmatter only; the counts guard protects the
   write phase's payload, which neither of them touches.
3. **`copy_documents()` returns `(copied, warnings)`** and derive folds the
   warnings into `report.warnings`, so an F3 mismatch surfaces in the manifest and
   over HTTP instead of only on stderr.
4. **A document whose extraction just failed is not reported twice.** The write
   gate would otherwise add "no usable extraction" on top of the extract error
   for the same document.
5. **B17 (sorting) versus H2 (round-trip equality).** H2 asks for field-for-field
   equality with the original, but `topics` and `connections` are sorted at
   serialisation, so equality can only hold against a sorted expectation. The
   tests compare against `sorted(..., key=str)`; `key=str` rather than plain
   `sorted` because LLM output is untyped and a mixed-type list would otherwise
   raise `TypeError`.
6. **A5 needed no code.** Extraction paths are derived from the raw scan, so a
   document under `_skipped/` or a dotfile is never handed to the layer. Asserted
   with a test rather than assumed, because the rejected alternative — folding
   over `extraction/` — would not have inherited it.

## Known gaps, recorded so they are not read as oversights

1. **`extract_strategy` can diverge between the two routes the way `extract_model`
   used to.** C4 added `model` to `ExtractRequest` because otherwise the daemon
   recorded its own literal default and every UI-ingested extraction was stale on
   the next CLI compile. The same shape exists for the strategy: the CLI always
   extracts `chunked`, while `_handle_extract` accepts `chunked`, `summarize` and
   `auto`. Today they agree, because the Go worker never sets `Strategy` and the
   daemon defaults to `chunked` — verified in `internal/worker/worker.go`. The
   moment a deployment sends a non-chunked strategy, each UI-ingested document is
   re-extracted once as `chunked` by the next CLI compile. Fix when it matters:
   either carry the strategy on `ExtractRequest` from config, symmetrically with
   `model`, or let the CLI honour a KB-configured strategy.
2. **`schema_version` is recorded but never compared.** B10's comparison set does
   not include it, so a future v2 file read by v1 code would parse as v1 and be
   judged fresh. Harmless at one version. The cheap fix when the format changes is
   for `parse()` to reject an unknown `schema_version`, which makes a bump behave
   like B9's "absent" and re-extract.
3. **The F3 and F5 checks have no operator entry point.** `derive/_status.py`
   exposes them as pure functions, which is what F5 asks for, but nothing in the
   CLI or the HTTP API calls them — they are reachable only from tests and from a
   `python -c`. A check nobody can run will rot; worth a `kb-ai derive --check`
   or folding the F3 result into the derive response.
4. **`bridge.ExtractResponse.Extraction` is now unused on the Go side.** The
   engine still returns the extraction and the field documents the response, but
   the worker no longer forwards it (D1 dropped `PipelineItem.Extraction`). Kept
   as a protocol mirror rather than deleted.
5. **The wiki-lag count folds over `.compile-state.json`, which is never
   garbage-collected**, so a document deleted from `raw/` still contributes to it.
   Report-only, and orphan cleanup is a stated non-goal.
6. **The write phase still has no provenance of its own** — spec's own known gap.
   Editing `merge-rewrite.md` or `merge-diff.md` invalidates nothing.
7. **`compile_kb` still calls `list_raw_files()`**, so all raw content is loaded
   into memory. G2 notes the two-gate split unblocks the migration to
   `iter_raw_file_meta()` plus a lazy `read_raw()`, since only the documents the
   extraction gate selects need content now. Left out as beyond this spec; the
   TODO at `commands/compile.py` records it.

## Stage 4 — run on 2026-08-08

Spec G8, H7 and H8. Approved and executed. Model `claude-sonnet-4-6` through the
LiteLLM proxy (`LLM_BASE_URL=…/v1`), `workers=12`. Same model and worker count as
the baseline run, so the cost figures are comparable.

Total spend 17.6931 USD: 17.4280 for the 108-document run, 0.2213 for a
two-document smoke run beforehand, 0.0438 for the derive topic filter.

### 1. Backup

`cp -R data/kb-2026-06 data/kb-2026-06.bak-pre-extraction-layer` (28 MB),
verified with `diff -rq` against the original: identical, 108 raw documents and
108 `.extract-cache/` entries. `.extract-cache/` is still on disk in both copies
as the recoverable pre-change state; nothing reads it any more.

### 2. Extraction from scratch — the cost figure reproduces

A two-document smoke run went first, to avoid discovering a write-path defect
17 USD in: 2 extracted, 0.2213 USD, correct provenance header on disk, and a
second run over the same KB extracted nothing, which is the freshness gate
working against real files.

Then all 108, `--extract-only`, wiki untouched:

| | Baseline (`.compile.log`, 2026-08-06) | Stage 4 (2026-08-08) | Delta |
|---|---|---|---|
| Documents | 108 extracted, 0 errors | 108 extracted, 0 revised, 0 errors | — |
| Cost | 17.4541 USD | **17.4280 USD** | −0.0261 USD (−0.15%) |
| Wall clock | 720.5 s | 500.4 s | −220.1 s (−30.5%) |
| LLM calls | not recorded | 302 | — |
| Tokens | not recorded | 2,146,991 prompt + 732,471 completion, 0 cached | — |

The cost lands within 0.15% of the baseline. That is what this step was for:
17.5 USD is the real number for this corpus at this model, and one run was not a
fluke.

Nothing in this change explains the 30% speedup. The extraction phase does the
same work; only where the result gets written moved. Proxy latency or contention
on the baseline day is the likely cause, and it should not be read as a
performance claim.

Two caveats on the baseline for anyone re-running this:

- `.compile.log` predates the `.md.md` rename (`eba18d0`) — its filenames carry
  the doubled suffix. Only names changed, and cost follows content, so the
  comparison holds.
- That log records a 30.2286 USD full compile, of which extract was 17.4541 and
  the write phase 10.7246. Stage 4 deliberately paid only the extract part.

### 3. Round-trip and header consistency over the real layer

All 108 freshly written files were parsed and re-serialized: **0 parse failures
and 0 differences, byte for byte**. That is stronger than the field-for-field
check taken during implementation, which replayed cache payloads rather than
reading what the new code actually wrote. Every file agrees on `prompt_version`
(`69f137466914`), `extract_model` (`claude-sonnet-4-6`), `extract_strategy`
(`chunked`) and `schema_version` (`1`).

Measured on those real files, the layer is smaller than the cache it replaces:
2.05 MB of markdown in 108 files against 2.42 MB of JSON in 108 cache entries
(2.27 MB vs 2.63 MB of allocated blocks).

The gate is cheap. A no-op re-run over all 108 documents, full parse, every file
fresh, completes in 1.26–1.54 s wall clock *including* interpreter startup and
reports `nothing to compile` at zero cost.

G5's wiki-lag report fired with the first-run reason:
`wiki_lag: {"articles": 108, "first_run": true}`, logged as *"108 articles were
written from an older extraction — expected on the first run after the extraction
layer landed, since no existing compile-state entry records a prompt_version"*.

### 4. `index/document-index.md` — no baseline existed to compare against

The plan asked for a selection comparison against the current file. There is no
current file: the reference KB was compiled on 2026-08-06, and the document
catalog only landed on 2026-08-07 (`c46d88a`). So this run *created*
`index/document-index.md` for the first time — 108 entries, and no
`[document-index] N of M documents without extraction` line, meaning every
document resolved to an extraction. The comparison is available to the next run,
not to this one.

`update_markdown_index` also rewrote `master-index.md`, `topic-index.md` and
`topic-index-longtail.md`. Expected: Phase 3 sits outside the write-phase guard,
and `wiki/` was untouched, so they regenerate from the same articles.

### 5. Derive — the selection reproduces and the extract phase is free

Derived the topic behind the existing `ai-coding-cost-governance` KB into a fresh
slug, so the existing seven were left alone. The topic filter **reproduced that
manifest exactly, 37 articles matched and 53 documents resolved**, in 1 batch,
0 dropped invented paths, 0 warnings, 0.0438 USD. No TTY and no `--yes`, so it
stopped before the compile by design.

The copy carries 53 extraction files and no `.extract-cache/`, and F3 over the
derived KB reports 53 match, 0 missing, 0 mismatched. B10 holds against the
copied documents.

Then `compile --extract-only` over the derived KB: **0 extracted, 0 cost, 0.73 s**.
That is the economic claim of the whole change, measured. The precise reading:
under `extract_only` the composition gate is skipped, so `nothing to compile` here
means the extraction gate found nothing stale. The write phase was not run. The
derived KB has no `.compile-state.json` and no `wiki/`, so all 53 documents would
still have to be composed, at the roughly 10 USD that costs.

### 6. F3 and F5 over the parent and the seven existing derived KBs

F3 over the parent: **108 match, 0 missing, 0 mismatched.**

F5 over each derived KB, all `in_sync`:

| Derived KB | In sync | Changed in parent | Gone |
|---|---|---|---|
| `ai-coding-cost-governance` | 53 | 0 | 0 |
| `bybit-ai-phase1` | 30 | 0 | 0 |
| `cloud-cost-optimization` | 20 | 0 | 0 |
| `kb-distillation` | 24 | 0 | 0 |
| `multi-site-launch` | 24 | 0 | 0 |
| `reliability-drills` | 23 | 0 | 0 |
| `supply-chain-ai-security` | 25 | 0 | 0 |

`ai-coding-cost-governance` matches the predicted known-good baseline of 53 / 0 / 0.

F3 over those same seven reports every document missing — 53, 30, 20, 24, 24, 23
and 25 respectively, all with reason `missing`. Expected under F7: they hold
`.extract-cache/` and no `extraction/`. They will keep reporting that until each
is re-derived or recompiled.

### Artefacts this run left behind

- `data/kb-2026-06.bak-pre-extraction-layer/` — the pre-run state, kept.
- `data/kb-2026-06/derived/stage4-extraction-check/` — the derive check above.
  Not one of the seven documented derived KBs, so it will show up as an eighth in
  any later F5 sweep. Costs 0.0438 USD to recreate; remove it if that is noise.
