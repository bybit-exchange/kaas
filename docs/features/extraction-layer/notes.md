# Extraction layer — implementation notes

Date: 2026-08-07, Stage 4 run 2026-08-08, gap follow-up 2026-08-08,
`connections` dropped 2026-08-08
Spec: [spec.md](spec.md) · Plan: [plan.md](plan.md) · Alignment:
[alignment-questions.md](alignment-questions.md)

Stages 1–3 are implemented and verified offline. Stage 4 — the real extraction run
over `data/kb-2026-06` — was approved and ran on 2026-08-08; its outcome is
recorded further down. The seven gaps this file recorded afterwards were then
worked through one at a time; what happened to each is in "The seven recorded
gaps" below.

## Verification

| Suite | Result |
|---|---|
| `cd py && uv run pytest tests/ -q` | 1477 passed, 1 skipped, 1 xfailed |
| `go test ./... -count=1` | all packages ok, `go vet ./...` clean |
| `cd web && pnpm test` | 454 passed (38 files) |
| Python coverage | 99% overall; `storage/extraction.py`, `storage/lag.py`, `commands/check.py`, `core/merge.py` and `derive/_status.py` all 100%, `commands/compile.py` 99% |

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

## The seven recorded gaps

Each one was reproduced before it was touched — six turned out to be real and were
fixed; one did not survive its own verification and the code was left alone. The
numbering is the original.

**1. `extract_strategy` diverged between the two routes the way `extract_model`
used to. Fixed.** Confirmed by reading the two sides: the CLI gate passed a literal
`STRATEGY_CHUNKED`, while `_handle_extract` recorded whichever strategy it routed
to. So a deployment configured for `summarize` had every UI-ingested extraction
read as stale on the next CLI compile — re-extracted once per document and
silently downgraded. Latent only because the Go worker never set `Strategy`.

The two strategies are not coarse and fine settings of one thing, which is what
made a silent downgrade worse than a wasted call. `chunked` sends the document
text to the structured extractor, splitting only past a 16,000-character window
(`core/extract.py`); `summarize` summarizes each chunk first and extracts from the
joined summaries, so the structured pass never sees the original words. Measured
over the reference corpus: 31 of 108 documents are a single chunk and are
extracted whole, the median is 24,534 characters, and the largest splits into 9
chunks — so `auto`, which switches at three chunks, would route 42 of them through
summaries.

The fix is one configured value both routes read. `plan_extraction` and
`run_planned_extraction` in `core/extract.py` are now the only router; the daemon
and `compile_kb` both call them, so the strategy the gate compares against and the
one that runs cannot disagree. `compile_kb` takes `extract_strategy` and
`summarize_model`; `llm.extract_strategy` (env `LLM_EXTRACT_STRATEGY`) reaches the
worker and `ExtractRequest.Strategy`, symmetrically with `model`; `kb-ai distill`
takes `--extract-strategy`. Under `chunked` or `summarize` the gate compares a
constant and reads nothing, so the gate stays as cheap as it was; only `auto`
resolves per document, at one streaming read and a chunk count and no LLM call.

There is a third route, and a review pass caught that the first fix had missed it:
`derive` compiles the KB it just built, and `derive_kb` was calling `compile_fn`
without a strategy, so that compile ran on the default. Since derive copies
extraction files byte-for-byte precisely so the derived compile pays nothing, a
`summarize` deployment would have had every copied extraction re-extracted — about
8.5 USD for a 53-document derive at the measured 0.16 USD per document — and
re-recorded as `chunked`, which the next compile of the source would then find
stale in turn, ping-ponging between the two. `derive_kb` now takes the strategy;
both entry points supply it (`commands/derive.py` from the environment,
`_handle_derive` from what `init` put there), and `extract_strategy` was added to
`bridge.LLMConfig` and `sendInit` so the daemon route has a value to pass at all.

An unrecognised strategy is now refused rather than treated as `chunked`, at four
points: `validate_strategy` for the CLI, argparse's `type=` so an environment
value cannot slip past `choices`, `INVALID_STRATEGY` from the daemon, and `Load`
on the Go side so a typo fails at startup instead of once per document. Falling
back silently is what made this class of bug invisible — the recorded provenance
would have agreed with itself. A non-chunked strategy with no `summarize_model` is
refused the same way, before the run starts, since that path calls a second model
once per chunk.

**2. `schema_version` was recorded but never compared. Fixed.** Reproduced first:
a file whose header said `schema_version: 99` parsed into a fully populated v1
`StoredExtraction`, and `staleness()` called it fresh. `parse()` now refuses any
value but `SCHEMA_VERSION`, which routes a format bump into `load()`'s absent
branch and re-extracts (B9) instead of composing an article from a payload the
code does not understand. Absent counts as unknown too; every file this package
writes records the field.

**3. F3 and F5 had no operator entry point. Fixed.** Confirmed by search: both are
exported from `derive/__init__.py` and have no non-test caller. `kb-ai check --kb
<dir>` is the entry point. One command rather than two: F3 applies to any KB, and
F5 already degrades to `unknown` with a reason when there is no derive manifest,
so a parent KB gets an honest "not derived from anything" instead of a special
case in the CLI.

Run against the reference KB it reproduces the Stage 4 figures through a new code
path — 108 match / 0 missing / 0 mismatched on the parent, and 53 in sync / 0
changed / 0 gone with all 53 reported missing under F3 on
`ai-coding-cost-governance`, exactly as recorded below.

**4. `bridge.ExtractResponse.Extraction` is unused on the Go side. Verified as not
a defect; code unchanged.** The unused part is real: `buildResult` reads only
`ext.Cost`, and no non-test code reads `.Extraction`. It is not a problem, on the
evidence. The payload is ~19 KB per document (2.05 MB over 108 files) against the
8 MB response buffer at `internal/bridge/daemon.go`, three orders of magnitude of
headroom, so it cannot push a response past the framing limit. Deleting the Go
field would not stop the daemon sending the payload either — it would only remove
the type-level record that the response carries it. Left as the protocol mirror it
was documented to be.

**5. The wiki-lag count folded over never-collected state entries. Fixed.**
Reproduced: with one of two documents deleted from `raw/`, the log still read
`wiki lag: 2 articles`. The fold is now restricted to documents still present. The
orphan entry itself stays — cleanup remains a stated non-goal — and a test asserts
it is still there, so the fix is not read as garbage collection.

**6. The write phase had no provenance of its own. Fixed, report-only.** Confirmed
by reading `extract_prompt_version()`: it hashes `extract`, `merge-summaries`,
`summarize` and `extract-types` only, and that is the value compile-state records,
so editing `merge-rewrite.md` or `merge-diff.md` invalidated nothing.

`write_prompt_version()` in `core/merge.py` is the counterpart, recorded per
document in compile-state. It covers three *system*-prompt surfaces, not two: the
article creator's was an f-string inside `create_new_article` and therefore
unhashable, so it was factored out into `_create_system(article_type)` and a test
pins the production call to the text that gets hashed. A version that silently
omitted a third of the write prompts would have been worse than none. The user
messages are out, deliberately and on the record: `extract_prompt_version` draws
the same line, hashing the extract prompts rather than the `<document>` wrapper
around them, so editing either side's scaffolding moves no hash.

Reported, never gated, which was the explicit decision. Both merge paths are
additive — `merge-diff.md` offers only `append_to_section` and `new_section`, and
`merge-rewrite.md` says nothing about supersession — so feeding this into the
composition gate would layer new content on top of old rather than replace it,
inflating every article and paying the full write phase (~10 USD on this corpus)
to do it. A supersession path would have to exist first.

The count is surfaced by `kb-ai check`, not only by compile. Compile can report a
lag only on a run that had other work, and a write-prompt edit changes no document
and no extraction — so the next compile returns "nothing to compile" before any
report, which is precisely the moment an operator wants the number. Compile still
logs it when it does have work.

`storage/lag.py` holds the comparison for both callers rather than a copy in each,
and reports "cannot tell" rather than "everything is behind" when a prompt set is
unreadable. The "first run" caption is per gate, not shared — a review pass caught
that a single flag would have captioned a *real* extract lag as expected noise for
every KB compiled between the extraction layer landing and this change, which is
exactly the state that describes: `prompt_version` recorded,
`write_prompt_version` absent.

**7. `compile_kb` preloaded every document's content. Fixed.** Measured before
changing anything: `list_raw_files()` retained 6.79 MB over the 108-document
reference KB (peak 7.11 MB) against 0.05 MB for `iter_raw_file_meta()` — about
62 KB retained per document, which is noise at 108 and roughly 63 MB at 1,000. The
scan is now metadata-only and `store.read_raw()` is called for the documents the
extraction gate selected, finishing the migration the TODO recorded.

The risk in this one was the checksum, not the memory: a byte-different hash would
have marked all 108 documents stale and re-extracted the corpus at ~17 USD. The two
methods were compared over every file of `data/kb-2026-06` first — 0 differences —
and afterwards a real `--extract-only` run over that KB reported `nothing to
compile` at zero cost, with the gate's own footprint down to 0.11 MB retained.

The split does cost one property the single read had for free, which a review pass
named: the scan's checksum and the extracted text are now two reads of the same
file, and both ingestion routes write into `raw/`. A document rewritten between
them and then reverted would have left an extraction whose recorded checksum
matches the document while its payload describes text that is no longer there —
fresh forever, which the previous code could not produce. `persist` is now handed
the hash of the text the extraction was actually made from, so the provenance is
true by construction rather than by timing.

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
  Kept, decided 2026-08-08: it is the only derived KB in the corpus that holds an
  `extraction/` directory rather than an `.extract-cache/`, so it is the one place
  the F5 path can be exercised against post-layer copies without paying to derive
  again. 3.2 MB, gitignored, 0.0438 USD to recreate. The cost of keeping it is
  that any F5 sweep reports eight derived KBs where the table above lists seven —
  read the eighth as this artefact, not as an undocumented KB.

## What a re-run should expect after the gap follow-up

The reference KB was left extracted and its wiki untouched, so `kb-ai check --kb
data/kb-2026-06` reports 108 match / 0 missing / 0 mismatched and
`108 behind the extract prompt, 108 behind the write prompt (first run)`. Both lag
counts are expected rather than a defect: the compile-state entries predate both
version fields, which is what `first_run` says. They clear the next time each
document is composed. The extraction files themselves are current — a
`--extract-only` run costs nothing and extracts nothing.

## `connections` dropped on 2026-08-08

The eighth payload field is gone. `connections` held LLM-suggested wiki article
titles this document "should link to", and Question 5 of the extract prompt asked
for them, but nothing ever turned one into a link: the single consumer was one
line of the classify user message (`- Connections (suggested links): ...`), a free
text hint next to `Topics` that no code validated against the article set. Compare
`topics`, which drives four real paths — the `Tags:` line of a new article, the
relevance sort that decides which existing articles reach the classify prompt, the
section scoring that decides what survives merge truncation, and the union-find
clustering in `_phase_classify`. If suggested links turn out to be worth having,
they come back as a field that actually emits links.

Removing it costs classify one hint and buys back a field in every extraction
file, a question in two prompts, a slot in two type-split groups
(`TYPE_SPLIT_GROUPS_K2["B"]` and `TYPE_SPLIT_GROUPS_K3["C"]`), and two dedup
passes — one in the chunk merge, one in `_combine_extractions`, which combines
across documents rather than chunks.

Removed from: both extract prompts, `ExtractionResult` (and the dead duplicate in
`_types.py`), `parse_extraction_result`, `extraction_to_dict`,
`_FIELD_JSON_SCHEMAS`, `TYPE_SPLIT_GROUPS_K2["B"]`, `TYPE_SPLIT_GROUPS_K3["C"]`,
both merge helpers, `classify_article`'s user message, merge's `_FIELD_PRIORITY`,
and the extraction file's frontmatter.

`SCHEMA_VERSION` stays at 1. Dropping a field is readable in both directions —
`parse()` ignores the `connections:` key old files still carry, and code that
still asked for it would read an absent key as the empty list it already tolerates
— so the version records no incompatibility. The re-extraction this forces comes
from `prompt_version` instead, which is the honest reason: editing `extract.md`
changes the hash, so every extraction in the reference KB is stale and the next
`compile` re-extracts all 108 of them. That holds for every deployment, not just
the default prompts — `_extract_stage_renderings` hashes the rendered type-split
variants too, so the `TYPE_SPLIT_GROUPS_K2/K3` and `_FIELD_JSON_SCHEMAS` edits move
the hash on their own, and a deployment overriding `extract.md` through
`KAAS_PROMPTS_DIR` cannot miss this change.

The 2026-08-07 record still describes the eight-field format wherever it was
specified, marked `[Superseded 2026-08-08: ...]` in place rather than rewritten:
[spec.md](spec.md) background item 2 and B1 (the frontmatter field list), B17 (the
sort, whose `serialize()` docstring *was* corrected, so the two now disagree by
design), the `spec.zh-CN.md` mirrors of all three, and
[alignment-questions.md](alignment-questions.md) C3. The four-layer diagram
(`assets/kb-four-layers.svg` and its `.zh` twin) still renders
`summary, topics, connections, counts` and was left as drawn — an SVG cannot carry
a bracketed marker, so the note sits in the caption line that embeds it.
