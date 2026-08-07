# Extraction layer — implementation notes

Date: 2026-08-07
Spec: [spec.md](spec.md) · Plan: [plan.md](plan.md) · Alignment:
[alignment-questions.md](alignment-questions.md)

Stages 1–3 are implemented and verified offline. Stage 4 (the real extraction run
over `data/kb-2026-06`, about 17.5 USD) is not started: it spends real money and
needs approval first.

## Verification

| Suite | Result |
|---|---|
| `cd py && uv run pytest tests/ -q` | 1407 passed, 1 skipped, 1 xfailed |
| `go test ./... -count=1` | all packages ok, `go vet ./...` clean |
| `cd web && pnpm test` | 454 passed (38 files) |
| Python coverage | 99% overall; `storage/extraction.py` 100%, `derive/_status.py` 100%, `commands/compile.py` 99% |

No test calls a real LLM.

## Measurements taken during implementation

All against the reference KB at `data/kb-2026-06`, which still holds its
pre-change `.extract-cache/`.

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

## Stage 4 — not run (needs approval)

Spec G8, H7 and H8. What it involves, in order:

1. `cp -R data/kb-2026-06 data/kb-2026-06.bak-pre-extraction-layer` — the
   repository already has `data/kb-2026-06.bak-pre-md-rename` as precedent.
   `.extract-cache/` is left untouched on disk either way, as the recoverable
   pre-change state.
2. Extract all 108 documents from scratch, `--extract-only` first so the wiki is
   untouched. **Real spend: about 17.5 USD**, from the reference KB's own
   `.compile.log` (`Phase 1 done: 108 extracted (0 cached), 0 errors, $17.4541`).
   This run is the second measurement of that figure.
3. Rebuild `index/document-index.md` and compare selection against the current
   file.
4. Derive one existing topic and confirm the copied extractions satisfy B10
   against the copied documents, so the derived compile pays nothing for extract.
5. Run the F5 check over the seven existing derived KBs. Known-good baseline:
   `ai-coding-cost-governance` should report 53 documents in sync, 0 changed in
   the parent, 0 gone. F3 will report every document missing there, which is
   expected — they hold `.extract-cache/` and no `extraction/` (F7).
6. Record the outcome here: documents extracted, measured cost against 17.5 USD,
   the first-run wiki-lag report G5 predicts (it will name every article, with
   the first-run reason), and any selection differences.
