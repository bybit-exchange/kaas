# Extraction layer — questions to settle before the plan

Date: 2026-08-07
Spec: [spec.md](spec.md)
Status: all decided — S1 and Q1–Q10, on 2026-08-07. Next: apply S1's spec edits in
one pass, then write `plan.md`.

The spec's own "Open questions" section is empty: O1–O7 were settled in the
2026-08-07 alignment pass. These are different. They surfaced while reading
the code the plan has to touch, and they are the points where the spec either
contradicts itself, leaves the implementer a choice, or does not yet know about
something in the code. Each one changes what gets written, so each is settled
before `plan.md` exists rather than during implementation.

Every question carries a recommendation. Answering "take your recommendation" is
a complete answer.

## Corrections, 2026-08-07 (second pass over the code)

Re-verifying every measured claim in the spec turned up two wrong numbers. Both
appear in the reasoning below and are **superseded**; every occurrence is marked
inline. The decisions they supported all stand — see spec G3 and C5 for the
corrected figures and their basis.

1. **Extraction cost: 17.5 USD for 108 documents, not 1.4 USD.** The 1.4 USD
   figure came from the residual of a *derived* compile, taken as "extract plus
   classify". Derive copies the parent's cache entries alongside the documents, so
   that run's extraction phase was a full cache hit and cost nothing: `Phase 1
   done: 53 extracted (53 cached), 0 errors, $0.0000`. The residual was classify
   alone. The reference KB's own from-scratch compile has the real number —
   `Phase 1 done: 108 extracted (0 cached), 0 errors, $17.4541`, out of 30.2286
   USD for the whole compile. So Q10's X costs 17.5 USD against Y's 30.2 USD: X
   still wins, by 1.7× rather than 7×, and G4's argument rather than the cost is
   what now carries it.
2. **`sources:` entries: 153 across 78 articles, not 200.** Measured by parsing
   every article's frontmatter with `split_frontmatter`; the derived KBs add 314
   more. The load-bearing half of that claim is unaffected — **0** absolute paths
   anywhere, including the derived KBs — so Q7's conclusion is unchanged.

---

## S1 — scope decision: no migration, and what compatibility still means

*Decided 2026-08-07.*

**Nothing carries over across this redesign.** `.extract-cache/` is abandoned
rather than migrated, and the seven existing derived KBs under
`data/kb-2026-06/derived/` are pre-change artifacts with no claim on the new
code. The reference KB's `extraction/` is populated by re-extracting all 108
documents from scratch, at roughly 1.4 USD [superseded — see Corrections: 17.5 USD] (spec G3 measured 53 documents at
about 0.69 USD for extract plus classify; linear extrapolation, not measured at
108).

The payload was never the problem: 108 cache entries map to 108 live raw
documents, so a migration would have been free of LLM calls. What the old cache
never recorded is provenance, and the only way a migration pays for itself is
G5's exemption — `unknown` counting as fresh. That exemption is permanent in
practice: an entry that counts as fresh is never re-extracted, so a stable
corpus keeps `unknown` provenance forever, and a provenance layer whose
provenance was never once verified is not worth building. 1.4 USD [superseded — see Corrections: 17.5 USD] deletes
section G in full, along with the migration command, its auto-invocation, orphan
reporting, and a three-valued freshness rule.

**Compatibility that still holds.** With the KaaS version fixed, a derived KB
must remain self-consistent and usable: F1–F8 do not get weaker. This costs
almost nothing, because F5 and F3 depend on different things:

- F5 (has the parent moved since I was derived) reads `manifest.json`'s
  `documents` array (`derive/__init__.py:99`) and rehashes the parent's `raw/`.
  It never touches an extraction, so it runs unchanged against the seven
  existing derived KBs and H6's known-good baseline survives without re-deriving
  anything.
- F3 (does my copied extraction match my copied document) is format-dependent.
  The seven existing derived KBs have `.extract-cache/` and no `extraction/`, so
  F3 reports every document as missing there. Verified instead against a freshly
  derived KB, which H5 already produces.

**Accepted consequences.**

1. Building a catalog inside a *pre-change* derived KB silently degrades once
   the catalog reader moves from `.extract-cache` to `extraction/`
   (`storage/index.py:164`): no document summaries, no error.
2. A derived KB handed to someone who sets `KAAS_PROMPTS_DIR` has every copied
   extraction marked stale, and their first compile re-extracts in full. This is
   O3's intent — seeing a deployment-local override is one of its stated reasons
   for a content hash — but it now has a bill attached, so the spec must say so.

**Spec edits this forces** (applied in one pass once Q1–Q10 are settled, not
piecemeal):

- Delete G1–G8. Rewrite O5 as a hard cut with no migration.
- Rewrite H5 as a from-scratch extraction run, and H6 as F5-only against the
  seven existing derived KBs.
- Correct G3's cost sentence into the S1 basis above.
- Delete `KBStore.save_extract_cache` **and** `load_extract_cache`
  (`storage/store.py:257,265`); the migration was the only thing keeping `load`
  alive.
- Restate the derive copy step as a relative-path mirror of `extraction/<rel>`
  alongside `raw/<rel>`, replacing the checksum-addressed
  `.extract-cache/<checksum>.json` copy at `derive/_layout.py:195-199`.

**Correction to the spec found while deciding this.** O5 and G7 justify
auto-migration with "an unmigrated KB looks like a KB with no extractions and
would re-extract in full". That is false as written. `commands/compile.py:97-101`
selects work by comparing `.compile-state.json` checksums, and the extract cache
is only consulted for documents already selected (`:133`). With the compile state
intact, deleting `.extract-cache/` re-extracts nothing — `to_compile` is empty.
Moot now that migration is gone, but the same fact drives Q10.

---

## Q1 — B7 and B9/B10 cannot both hold as written

B9 defines `prompt_version` as a hash over the prompts *actually used for this
document*. B7 defines staleness as a pure field comparison. To compare, compile
must know what the current value *would* be before extracting, and it cannot.

Which prompts one extraction uses depends on the strategy, the chunk count, and
— for the summarize strategy — on the total length of the summaries:
`core/extract.py:635` routes on `n >= 20 or len(naive_joined) > 60_000`, where
`naive_joined` is the joined chunk summaries. Those summaries do not exist until
they have been paid for. So for any document on the summarize path there is no
expected `prompt_version` computable without spending money, which is what O4
forbids on a read path.

**Recommendation.** Split recording from comparing.

Recording side: implement B9/B10 literally. The sorted
`(prompt_name, sha256(rendered_content))` pairs actually collected during the
run, hashed to 12 hex digits.

Comparing side: replace "equals the expected value" with "is one of the values
this configuration can still produce". The combinations are enumerable from the
current prompt files alone, with no content and no LLM call:

1. `{extract}` — chunked, any chunk count; also summarize with ≤3 chunks
   reaching `extract_knowledge`
2. `{summarize, extract}`
3. `{summarize, extract-types×K2}` (both K=2 groups, rendered)
4. `{summarize, extract-types×K3}` (all three K=3 groups, rendered)
5. `{summarize, merge-summaries, extract-types×K3}`

An extraction is fresh on this field when its recorded hash is one of those
five. Editing any prompt shifts every combination containing it, so an
extraction made with the old text matches none of them. H4's "only the prompt
content changed, and nobody bumped a version number" case still fires.

**Trade-off.** Costs a static combination table that has to track the routing
families in `core/extract.py`. That is materially less drift-prone than
mirroring the numeric thresholds (`>= 20`, `> 60_000`, `<= 3`, `<= 7`), and a
test can assert a stubbed-LLM run's recorded version is a member of the
candidate set for each strategy.

**Status.** *Decided 2026-08-07: neither. `prompt_version` becomes a pure
function of the prompt set, independent of which prompts a given run used.*

The recommendation above (call it A) and its per-prompt refinement (B — record
the pairs decomposably, check each against the currently renderable set) both buy
per-document precision, and both pay for it with a mechanism that fails silently
in the wrong direction. A mirrors the routing families, and a mirror that drifts
marks everything permanently stale — silent overspend. B needs runtime collection
of which prompts a run touched, threaded through the three `ThreadPoolExecutor`
blocks that already re-propagate contextvars by hand
(`core/extract.py:595-598`, `:700-703`, and the one inside `merge_summaries_l2`);
missing one silently under-records, which lands back on exactly the silent-reuse
bug this layer exists to kill.

**The decision.** `prompt_version` is a 12-hex hash over the extraction stage's
prompt set as it currently renders, with no reference to what any particular run
did:

```python
EXTRACT_STAGE_PROMPTS = ("extract", "extract-types", "merge-summaries", "summarize")
```

Hashed input: the loaded content of `extract`, `merge-summaries` and `summarize`,
plus the five rendered `extract-types` variants — `_render_type_split_prompt`
called for every `(k, group)` enumerated from `TYPE_SPLIT_GROUPS_K2` and
`TYPE_SPLIT_GROUPS_K3` themselves, so nothing is mirrored. Name and content are
framed with a NUL separator and a length prefix so a trailing newline cannot
collide with the next name. Truncated to 12 hex.

B7 then holds literally, with no rewording: a plain field comparison, computable
on any read path from the prompt files alone. B9 collapses to one sentence and
B10 all but disappears — there is no "rendered strings actually sent" to collect.

**Why this is the codebase's existing convention rather than a new invention.**
`classify_inputs_hash` (`core/classify.py:88-100`) already hashes the *rendered*
classify system prompt for exactly this reason, and its docstring records that the
previous categories-only hash had precisely the silent-reuse bug: "a prompt-only
edit silently kept serving classifications produced by the previous prompt."
Extraction gets the same treatment, one layer down.

**Verified while deciding.** `load_prompt` is the only route into the registry on
the extraction path (`core/extract.py:91-92`); `core/merge.py:213,226,246` and
`core/classify.py:105` use the registry directly but belong to the write and
classify phases. No production caller overrides `prompt_name` — `chat.py` uses
different prompts through the registry, not through `load_prompt`. So the four
names are complete for extraction.

**Two requirements this carries, both found by self-check.**

1. *Hash the renderings, not the file.* Hashing `extract-types.md` verbatim would
   miss changes to `TYPE_SPLIT_GROUPS_K2/K3` and `_FIELD_JSON_SCHEMAS`
   (`core/extract.py:95-112`) — code constants that change the text actually sent
   to the model. Rendering closes the blind spot at no cost, since the renderer
   and both group tables already exist.
2. *Compute once per process, before any extraction.* The registry caches lazily
   per name (`registry.py:48-53`), so a long-lived daemon can hold `extract` from
   before a prompt edit and `summarize` from after it. `prompt_version` would then
   depend on load order rather than only on time: two documents extracted minutes
   apart in one daemon could record different hashes with no code change, and H3's
   byte-identity assertion would fail spuriously inside that window. Computing the
   version once, memoized, before the first extraction pins all four names into
   the cache together. It also makes `prompt_version` a per-process constant,
   which is what makes "restart the daemon after editing prompts" an exact rule
   rather than a hedge.

**Failure direction.** A missing or invalid prompt file makes `load_prompt` raise
`NoActivePromptError` (`registry.py:88`), so a read path computing
`prompt_version` would crash rather than report. It must catch, report the reason
in B8's style, and never fall back to fresh.

**Guard.** `load_prompt` asserts its argument is in `EXTRACT_STAGE_PROMPTS`, so
adding a fifth extraction prompt without listing it fails at first use instead of
silently narrowing the hash. Checked against the tests: `stub_prompts`
(`py/tests/test_core_extract.py:106-109`) monkeypatches `ex.load_prompt` itself,
so the assert does not break the five tests that use it — and therefore needs a
test of its own. `test_extract_knowledge_honours_prompt_name` (`:775-784`) passes
`"extract-types"`, which is in the set.

**Accepted costs.** Editing any extraction prompt re-extracts the whole KB — about
1.4 USD [superseded — see Corrections: 17.5 USD] for 108 documents under Q10's X. This is O3's stated intent, so C is the
only one of the three options that needs no change to O3's wording. A derived KB
opened with a `KAAS_PROMPTS_DIR` override has every copied extraction marked
stale (S1, consequence 2).

**Known gap, out of scope, recorded so it is not read as an oversight.**
Extraction gets provenance and classify already has its prompt hash, but the
write phase has neither: editing `merge-rewrite.md` or `merge-diff.md` invalidates
nothing, because the write phase is gated only by `.compile-state.json`.

---

## Q2 — C3's "byte-identical" versus `extracted_at`

C3 requires the same document ingested by either route to yield a byte-identical
extraction file. B1 requires an `extracted_at` field. Two runs cannot share a
timestamp.

**Recommendation.** Make byte-identity a property of the code rather than of two
implementations agreeing. One `persist()` function in the new extraction module,
called by both the CLI compile path and the daemon, with no second serializer
anywhere. `extracted_at` becomes a parameter with a late default (`None` → one
shared `_now_iso()` helper), so the C3 parity test injects a fixed timestamp and
asserts literal byte equality instead of equality-modulo-timestamp.

**Status.** *Decided 2026-08-07: one `persist()`, with two changes to the
recommendation.*

**What C3 actually is.** An extraction payload is LLM output, so two real runs of
the same document never agree byte for byte anyway. C3 is therefore a property of
the *serializer*, not of extraction, and H3 is necessarily a stubbed-LLM test.
What it proves is that there is one serializer on one code path — which is the
same argument as Q4. Two questions, one answer: a second serializer turns C3 from
a structural property into a coincidence between two implementations.

**Change 1 — `_now_iso()` emits UTC.** There is no convention to inherit; the tree
has four formats. `commands/compile.py:269,397` and `derive/__init__.py:230` use
naive local `datetime.now().isoformat()`; `core/classify.py:71` uses
`datetime.now(timezone.utc).isoformat()` for `categories_frozen_at`;
`core/people.py:191` and `core/merge.py:242,429` use date-only
`date.today().isoformat()`; `storage/index.py:327` uses a `strftime` display
format. `extracted_at` follows `classify.py:71` — UTC with an offset,
`timespec="seconds"` — because S1 established that derived KBs get handed to other
machines, and `derive/_layout.py` copies with `shutil.copyfile`, which does not
preserve mtime the way `copy2` would. The field in the file is the only durable
answer to "when was this extracted", and a naive local timestamp is misleading
once it has moved.

**Change 2 — no `extracted_at` parameter; H3 monkeypatches `_now_iso`.** A
production parameter whose only real caller is a test is test scaffolding leaking
into the API, which the repository's simplicity rule excludes. Monkeypatching a
module-level helper is already this tree's idiom (`test_core_extract.py:108`
patches `ex.load_prompt`). The cost is one private name coupled into one test.

**`extracted_at` stays.** It is the only field creating the tension — B7's four
staleness fields do not include it, and dropping it would make C3 literally true
with no helper and no injection. It stays because "when" is a provenance
question and this is a provenance header, and because mtime does not survive
derive, so nothing else can answer it. "This extraction has not moved in three
months" is exactly the audit the layer exists to support.

**Self-check.**

- *Is `extracted_at` the only non-deterministic field?* Yes. Given one
  `ExtractionResult`, all of `source`, `source_checksum`, `extract_model`,
  `extract_strategy`, `prompt_version` (a per-process constant per Q1),
  `schema_version`, `summary`, `topics`, `connections` and `counts` are fixed.
- *Can `prompt_version` differ between the two paths and break C3 quietly?* Yes —
  the daemon's lazy per-name registry cache, handled in Q1 by computing the
  version once per process before any extraction. H3 must run both paths in one
  process, or it is testing cache timing rather than the serializer.
- *Is `safe_dump` key order stable?* Yes, `sort_keys=True` is the default, so the
  same dict yields the same bytes on both paths. `core/people.py:117` already
  relies on this.

---

## Q3 — B2's `surprising: no` versus B4's `yaml.safe_dump`

B2 illustrates the explicit-labelling rule with `claims[].surprising` written as
`surprising: no`. B4 mandates `yaml.safe_dump(..., allow_unicode=True,
default_flow_style=False, width=10**6)`, which emits `surprising: false`. Only
one of the two can be satisfied.

**Recommendation.** Emit `false` and keep `safe_dump`. The property B2 is buying
is "every field is an explicit labelled value, never implied by styling", and
`false` has it; `no` was an illustration. Hand-writing the serializer to produce
`no` means hand-writing the escaping too, and H2 requires fixtures covering a
value containing `"`, a value containing `: `, CJK throughout, and a summary
long enough to trigger line wrapping. That is exactly the escaping surface
`safe_dump` exists to get right.

**Status.** *Decided 2026-08-07: emit `false`. The premise was wrong, and the
question underneath it is what serialises the body.*

**There is no conflict as written.** B4 governs the frontmatter; B2 governs the
body, and `claims[].surprising` lives in the body. The two never meet. They only
collide under a premise the spec never states — that the body is also written with
`safe_dump`. Which is the real question: **what serialises the body?**

**Decision: the body is `safe_dump` too**, which collapses O1's accepted
"serializer/parser pair" to almost nothing. Each section's content is
`yaml.safe_dump` of that field's list:

```markdown
---
source: raw/window-2026-06__meetings__2026-06-04-video-meetingcc.md
source_checksum: 0123456789abcdef
extract_model: claude-sonnet-4-6
extract_strategy: chunked
prompt_version: a1b2c3d4e5f6
extracted_at: '2026-08-07T11:22:33+00:00'
schema_version: 1
summary: ...
topics: [...]
connections: [...]
counts:
  action_items: 2
  claims: 5
  ...
---

## Claims

- claim: ...
  surprising: false
```

- Writing: one `safe_dump` for the frontmatter, five for the sections.
- Reading: reuse `split_frontmatter` (`py/src/kb_ai/_frontmatter.py`) rather than
  writing a second splitter — its docstring records the `content.split("---", 2)`
  bug that commit `eba18d0` fixed — then locate the headings and `safe_load` each
  block.
- Escaping: PyYAML's problem, not ours. All four of H2's fixtures (`"`, `: `, CJK,
  a value long enough to wrap) pass without hand-written escaping, which is the
  substance of the original recommendation.

**No heading/field mapping table.** The heading is a pure function of the field
name — `action_items` → `.replace("_", " ").title()` → `Action Items`, reversed by
`.lower().replace(" ", "_")`. All five field names are lowercase with underscores,
so the round-trip is exact and there is nothing to keep in sync. B3's `counts`
check becomes one dict comparison.

**B4 needs amending.** Its three options — `allow_unicode=True`,
`default_flow_style=False`, `width=10**6` — currently apply only to the
frontmatter. They are equally required for the body: the body is where the
CJK-dense values live (a concept's `definition`), and `width` is what stops a long
value folding.

**On `no` itself.** `false` has the property B2 is actually buying — every field is
an explicit labelled value, never implied by styling. `no` was an illustration.
It also buys nothing: `no` is a YAML 1.1 boolean literal, so `safe_load` returns
`False` for it either way, and insisting on it means hand-writing the escaping for
no change in what a reader parses.

**Self-check.**

- *Does `safe_dump` treat `no` as a boolean?* Yes — YAML 1.1 makes `no/yes/on/off`
  booleans, so a *string* field whose value is `"no"` gets quoted (`'no'`) to
  preserve its type. That is the behaviour we want, but H2 needs a fixture for it:
  a string field whose value is exactly `"no"`. None of the four fixtures listed
  covers it.
- *Empty lists?* `safe_dump([])` emits `[]`. The section exists, its content is
  `[]`, `counts` records 0 — all three agree, so B3's check passes. H2 already
  requires this fixture.
- *Section order* is fixed to B2's order (concepts, entities, decisions,
  action_items, claims), not alphabetical, so the file reads in the order the spec
  describes. It is part of C3's byte-identity and must be pinned, not derived from
  dict iteration.

---

## Q4 — which side of the bridge persists the extraction (C2)

C2 fixes that the worker path must persist, and states that which side does it
is a tech-design decision. The extraction is already returned by the daemon
(`server_daemon.py:168`) and carried through the bridge as an opaque blob
(`internal/bridge/api.go:42`).

**Recommendation.** The Python daemon writes it. Writing on the Go side means a
second markdown serializer in Go, which turns C3's byte-identity from a
structural property into a coincidence between two implementations. The
parser/serializer pair is already the accepted cost of O1; paying for it twice
is the wrong direction.

Consequence: `bridge.ExtractRequest` gains `kb_dir` and `source`, and the worker
derives the raw-relative path with `filepath.Rel(cfg.KBDir, task.RawPath)`.

**Status.** *Decided 2026-08-07: the Python daemon writes it, with two
additions.*

The argument holds and is the same one as Q2: a second serializer in Go turns C3
from a structural property into a coincidence. Q3 makes it stronger — with the
body on `safe_dump` too, a Go writer would have to reproduce not just the layout
but PyYAML's escaping decisions, which is not realistically achievable.

**Verified.** `ExtractRequest` (`internal/bridge/api.go:31-37`) carries only
`Content`, `Model`, `Strategy`, `SummarizeModel`, so it does need `kb_dir` and
`source`. But `PipelineRequest` already carries both `KBDir` and `SourceRef`
(`:56,61`) — the values are already in the worker's hand, they just never reach the
extract hop.

**Addition 1 — Q4 and Q7 are the same line of code.** Q7's fix is
`filepath.Rel(cfg.KBDir, task.RawPath)`, and that is exactly the value
`ExtractRequest.Source` needs. Compute it once in the worker and feed both
`ExtractRequest.Source` and `PipelineItem.SourceRef`. One change, not two. The
spec should also state that the `kb_dir` on the two requests must be the same
value — they both come from `w.cfg.KBDir` today, and carrying it twice invites
someone to change one of them later.

**Addition 2 — persisting at the extract hop is what makes retries free.** This
is the substantive difference between "the daemon writes it" and "the pipeline hop
writes it", and the spec does not say it. Retries are real: `MaxAttempts` plus
`Nack` returns a task to pending (`internal/queue/queue_test.go:79-92`,
`internal/worker/worker_test.go:172,186-189`), and `w.fail` is a `Nack`
(`internal/worker/worker.go:147-154`). Today the worker runs extract → pipeline →
ack, so a pipeline failure with an attempt left re-runs the whole task and **pays
for extraction a second time**.

So the daemon's extract handler reads `extraction/<rel>` before calling the model,
and returns it unchanged when it exists and all four B7 fields match. This does not
violate O4's "compile only may re-extract" — it is *not* extracting. Without it the
layer exists and the retry path ignores it, at a full extraction's cost per
pipeline failure.

**Self-check.**

- *Daemon write failure?* That is Q5. Q4 settles only who writes.
- *How does the daemon resolve an absolute path from a relative `source`?*
  `kb_dir` plus `source`, both in the same request. It also gives the daemon B1's
  `source` field directly instead of reverse-engineering it from an absolute path.
- *Does the CLI path change?* No. It already holds `store.base_dir` and
  `rf.rel_path` and calls the same `persist()`.

---

## Q5 — C4's failure semantics when the write fails

C4 says a write failure is reported on the task. It does not say whether the
pipeline still runs. Two readings:

(a) The daemon returns an error and the worker fails the task. The LLM spend on
that extraction is lost and a retry pays again.

(b) The daemon returns the extraction with a "not persisted" marker, the
pipeline runs anyway, and the task carries a warning.

There is a third case the spec does not name at all: an extraction that
succeeded structurally but is **entirely empty**.
`extract_knowledge_summarized` only warns when a chunk summarization fails
(`core/extract.py:608-614`), and if every chunk fails it returns a bare
`ExtractionResult()` (`:616`). Under B3 that file is valid — all counts are
zero — and under B8 it is not "absent", so it persists as a fresh, empty, correct
extraction and nothing ever retries it. Whichever way Q1 lands makes this worse in
a different direction: with per-prompt freshness the empty file is fresh forever;
with a combination table its prompt set matches nothing and it is re-extracted on
every compile, forever, for money. Both are wrong, and the fix belongs here rather
than in Q1 — the write path refuses to persist an extraction with an empty
`summary` and zero items across all five body sections, and treats it as a failed
extraction.

**Recommendation.** (a). D1 makes "composition reads only from `extraction/`" an
asserted invariant, and running the pipeline from an extraction that is not on
disk is the CLI-versus-worker divergence this spec exists to remove. Reading (b)
reintroduces it as a supported state. One code path, no half-success protocol.

**Trade-off.** Real money on a retry after a disk error. Raised rather than
decided here because it is a spend decision.

**Status.** *Decided 2026-08-07: (a), with a sharper reason, no write retry, and
the empty-extraction hole fixed at its source rather than in the write path.*

**Why (a): (b) needs a protocol that does not exist; (a) needs nothing.**
Stronger than the D1 argument. (a) reuses `w.fail`
(`internal/worker/worker.go:147-154`, itself a `Nack`) verbatim:
`w.fail(ctx, task, "extract: persist: ...")`. (b) needs a "not persisted" marker
added to `ExtractResponse`, which today carries only `Extraction` and `Cost`
(`internal/bridge/api.go:40-43`), plus a channel to surface a warning on the task
record — and `Warnings []string` exists nowhere but the *derive* response
(`:168`). One code path against one new half-success protocol.

**No retry on the write.** The atomic temp-plus-`os.replace` of B6 already covers
a torn write. What actually fails is ENOSPC, EACCES or EROFS, none of which clears
in milliseconds, so retrying is error handling for a scenario that cannot be
fixed in place — excluded by the repository's simplicity rule. Fail, report the
reason, let the operator fix the disk. The recorded trade-off stands and Q4's
skip-if-fresh does not rescue it: a failed write means there is nothing on disk to
reuse.

**The empty-extraction hole belongs in `core/extract.py`, not the write path.**
The two extraction paths disagree about what a chunk failure means. The chunked
path does `all_results[idx] = future.result()` with no `except`
(`core/extract.py:711`), so a failure propagates. The summarize path swallows it
into a warning (`:606-613`) and then returns a bare `ExtractionResult()` at
`:616-617` — indistinguishable from "the model read the content and had nothing to
say".

Fix: `:617` raises, matching the chunked path. An empty extraction then means only
the legitimate case, which is correctly persisted, so the write path needs no
emptiness check and there is no file that re-extracts on every compile forever.
`:585-586`'s `if not chunks: return ExtractionResult()` stays as it is — an empty
document honestly extracts to nothing.

Better than a guard in the write path on three counts: one fewer check, the
ambiguity is removed where it is created, and the two extraction paths end up with
the same error semantics.

**Self-check.**

- *Does raising at `:617` fail documents that work today?* Only where **every**
  chunk summarization failed. Today that produces an empty extraction file and
  then an empty article through classify and write. Failing is better.
- *Partial chunk failure?* Unchanged — warn and proceed on the survivors. That is
  deliberate degradation and not in scope.
- *Does `_phase2_with_retry` change?* No. It is already retry-once-then-propagate
  (`:664-671`), which is what Phase 1 becomes.
- *What does the CLI do with the new exception?* Existing path: into `errors`, the
  document absent from `extractions`, skipped by the later phases
  (`commands/compile.py:151-154`).

---

## Q6 — checksum newline normalisation (not in the spec)

B1 requires `source_checksum` to be "the same 16-hex prefix `_compute_checksum`
produces". The two paths feed it different bytes for the same file.

The CLI hashes `path.read_text()`, which applies universal-newline translation
(`storage/store.py:124-130`; `iter_raw_file_meta` documents the byte-equivalence
contract at `:132-149`). The daemon receives a JSON string that Go decoded from
the raw file bytes, CRLF intact. For any CRLF document the two checksums differ,
so B7 reports it permanently stale and F3 permanently skips copying its
extraction. Both failures are silent.

**Recommendation.** Normalise `\r\n` and lone `\r` to `\n` in the daemon before
hashing, and add a CRLF fixture asserting the daemon's `source_checksum` equals
`_compute_checksum(Path(...).read_text())`.

**Status.** *Decided 2026-08-07: normalise on receipt rather than before hashing,
because the divergence is wider than the checksum.*

**Verified as stated.** `_compute_checksum(content: str)` (`storage/store.py:53`)
takes text, and all five call sites feed it the result of `read_text()`
(`:127`, `storage/index.py:164`, `derive/_sources.py:95,179`) — already
universal-newline normalised. `iter_raw_file_meta` opens with `newline=None`
specifically to stay byte-equivalent to `read_text()`, and says so in its
docstring (`store.py:132-149`). On the Go side, `internal/worker/worker.go:94`
sends `Content: string(content)` read straight from the file, so CRLF crosses the
bridge intact.

**What Q6 missed.** Fixing only the hash leaves a second divergence: the daemon
chunks and prompts the model with CRLF text where the CLI uses LF. The two routes
feed the model different bytes. H3 stubs the LLM, and a stub returns the same
canned result for both, so the test would pass while the real behaviour diverges —
exactly the "coincidence between two implementations" C3 exists to rule out.

**Fix: one normalisation of `content` on receipt in `_handle_extract`**, so
everything downstream — checksum, chunking, extraction — sees the text the CLI
would have seen. Against the alternatives:

- *Inside `_compute_checksum`*: more central, but covers only the hash and leaves
  the model-input divergence.
- *In `submit.go` before writing raw*: more thorough but incomplete — CLI-fetched
  or hand-placed CRLF files still diverge — and it rewrites the bytes the
  submitter sent.
- *On the Go side before sending*: makes the bridge contract "content is
  LF-normalised", but then Python can only trust it and cannot test it.

`_compute_checksum` stays untouched: its five callers already pass normalised
text, so adding normalisation there is a no-op that only guards a caller which
does not exist.

**Tests.** Keep the CRLF fixture asserting the daemon's `source_checksum` equals
`_compute_checksum(Path(...).read_text())`. Add a second one: the same CRLF
fixture through both routes, asserting the content string handed to the (stubbed)
extraction function is identical. That second one is what closes the
green-test-diverging-behaviour gap above.

**Self-check.**

- *Does any checksum on disk change?* No. Every existing caller already feeds LF,
  so `.compile-state.json`, the derive manifest and the classify cache key are all
  unaffected.
- *Does `iter_raw_file_meta` need changing?* No, `newline=None` already normalises.
  Worth recording that the guarantee now lives in two places — the daemon's entry
  point and that `newline=None` — held together by the docstring contract at
  `store.py:132-149`. Pre-existing, not introduced here.
- *Does derive's `newline=""` copy (`derive/_layout.py:191`) change?* No.
  Preserving the original bytes is correct, and `read_text()` normalises on the way
  back in, so the checksum still matches.
- *Is a lone `\r` worth handling?* Yes. `read_text()`'s universal newlines turn it
  into `\n`, so skipping it leaves the divergence in place. One more branch in the
  same expression.

---

## Q7 — pre-existing bug: the worker sends an absolute `source_ref`

D3 says article `sources:` frontmatter keeps naming `raw/<rel>` paths. On the
worker path it does not, today.

`internal/api/submit.go:60` builds
`rawPath = filepath.Join(s.cfg.KBDir, "raw", id+".md")`, and
`internal/config/config.go:203-204` has already made `KBDir` absolute. The
worker forwards that verbatim as `SourceRef: task.RawPath`
(`internal/worker/worker.go:125`), which the write phase records as the
article's source. So documents ingested through the HTTP API or the web UI
produce articles whose `sources:` entries are absolute filesystem paths, while
CLI-compiled articles carry `raw/<rel>`. Derive's document resolution reads
those entries.

This is not caused by this spec and is not named by it.

**Recommendation.** Flag, do not fix here. Stage 2 computes the relative path in
the worker anyway, so the fix is one line, but it changes the format of an
existing artifact and belongs to whoever owns that decision rather than to a
surgical change inside this feature. Worth an issue.

**Alternative.** Fix it in Stage 2 while the code is open, and say so in the
commit. Pick one.

**Status.** *Decided 2026-08-07: fix it in Stage 2.* S1 removes the objection —
the recommendation's only argument for deferring was that the fix changes the
format of an existing artifact, and no existing artifact has a claim on the new
code. Measured: the reference KB's `wiki/` carries 200 [superseded — see Corrections: 153] `sources:` entries and
**0** absolute paths, so every article there was CLI-compiled and the bug never
polluted it. The fix therefore needs no read-side tolerance for both formats —
one line in the worker, and derive's document resolution stays as it is.

---

## Q8 — H5 runs the migration against the only reference KB

H5 requires a real smoke run: migrate `data/kb-2026-06`, rebuild
`index/document-index.md`, derive one existing topic, record the outcome.

`data/` is in `.gitignore`, so this KB exists only on this machine. Measured
now: 108 live raw documents, 108 `.extract-cache` entries, matching G4's stated
0 orphans and 0 missing. Migration writes 108 files under `extraction/` and
rebuilds `document-index.md`. It does not delete `.extract-cache` (G8), so the
pre-change state is recoverable, but the write itself is not free to undo.

**Recommendation.** `cp -R` a backup before the run; the repository already has
`data/kb-2026-06.bak-pre-md-rename` as precedent. Confirm before running, since
it mutates real local data.

**Status.** *Dissolved by S1: there is no migration to run.* H5 becomes a
from-scratch extraction of the same KB, so the `cp -R` backup is still worth
taking — the run writes 108 files under `extraction/` and spends real money — but
it is insurance rather than a precondition, and `.extract-cache/` stays untouched
on disk as the recoverable pre-change state.

---

## Q9 — two small readings, proceeding on the default unless corrected

G5's "unknown counts as fresh" applies to three fields, not four. Migration maps
a cache entry to a document *by* checksum, so `source_checksum` is always a real
value and is compared strictly. The `unknown` exemption covers `extract_model`,
`extract_strategy` and `prompt_version`.

**Correction, recorded because it corrects the spec rather than this file.**
G5 over-states: `extract_strategy` is knowable, and it is `chunked`.
`save_extract_cache` has exactly one caller in the tree
(`commands/compile.py:146`), and that path calls `extract_knowledge_chunked`
unconditionally (`:141`). The daemon never wrote an extract cache entry at all —
which is precisely the gap C2 exists to close. So only `extract_model` and
`prompt_version` were ever unknowable. Moot for the plan now that S1 drops
migration, but G5's sentence is wrong and should not survive into a rewrite.

C5 reports on the CLI compile path only. The revised-document report reuses the
`_file_done_articles` map the write phase already builds in
`commands/compile.py`; the Go worker path goes through
`commands/pipeline/_phase_write.py`, which has no equivalent. This matches the
spec's sequencing note placing C5 in stage 1 rather than with the rest of C.

**Status.** *Decided 2026-08-07.* The first reading is dissolved by S1 — with no
migration there are no grandfathered entries, so no `unknown` and no exemption.
Freshness is a plain four-field comparison with no special value, which was the
main thing S1 bought. The second reading stands as written: C5 is CLI-only and
lands in stage 1.

---

## Q10 — what staleness actually triggers, and what it drags with it

Raised by S1. Compile today has one selected set, `to_compile`, chosen by
comparing `.compile-state.json` checksums (`commands/compile.py:97-101`). All
three phases then iterate that same set: extraction (`:130`), classify
(`:180` via `items_to_classify`) and write (`:227`). The extract cache is a
second-level cache *inside* the selection, not a gate on it.

So making B7 staleness drive re-extraction is not a local change. If a stale
extraction puts its document into `to_compile`, that document also gets
re-classified and its articles rewritten. Two shapes:

**X — two independently gated phases.** Extraction is gated by B7 staleness;
the write phase stays gated by `.compile-state.json`. A prompt edit re-extracts
and stops there.

**Y — one selected set, as today.** Extraction staleness feeds `to_compile`.
A prompt edit re-extracts *and* rewrites every article.

Cost basis, same extrapolation as S1: the reference KB's 108 documents cost about
1.4 USD under X and about 10 USD under Y [superseded — see Corrections: 17.5 USD] (spec G3 measured 53 documents at
5.0644 USD total with 4.3763 USD in the write phase).

**Recommendation.** X. O4's stated reason for confining re-extraction to compile
is that "re-extracting on read turns prompt tuning into unpredictable spend"; Y
keeps the spend predictable and makes it seven times larger, on a workflow the
spec exists to serve. X also has the cleaner story: each artifact is gated by the
provenance of the artifact it is derived from.

**Coupled to Q1.** Option C over-invalidates by design — editing any
extract-stage prompt marks every extraction stale. C plus X costs 1.4 USD [superseded — see Corrections: 17.5 USD] per
prompt edit. C plus Y costs 10 USD per prompt edit and rewrites the whole wiki
each time, which is not a tuning loop anyone will use. Choosing C is close to
choosing X.

**Status.** *Decided 2026-08-07: X, plus a lag report and an `--extract-only`
flag.*

**X is not extra work; it is the shape D1 already implies.** Today the write
phase carries the in-memory `ExtractionResult` down through the `article_ops`
tuples into `_process_article` (`commands/compile.py:253,262`). D1 requires
classify and write to read only from `extraction/`. Once the write phase reads
`extraction/<rel>` off disk, the two phases are decoupled by construction: two
loops over `raw/`, two independent gates, one on-disk artifact handing off
between them. That is fewer concepts than today's single selected set with a
second-level cache inside it, not more. It also unblocks the TODO at
`commands/compile.py:87-94` — the write phase needs no raw content at all (D1),
and extraction needs it only for the documents it actually extracts.

**Y's extra spend does not buy what it appears to buy.** O4a already records that
merge can only add: "both paths can only add", and the real fix needs a
supersession signal plus a replace primitive in `merge-diff.md`, explicitly
excluded from this spec. So re-running the write phase after a prompt change does
not produce articles rewritten from the new extraction — it merges new extraction
content into articles that still carry the old extraction's content, accumulating
duplication and self-contradiction. Y spends roughly seven times as much to
produce a less well-defined artifact.

**X's real cost, and how it is handled.** Under X the wiki can lag `extraction/`
after a prompt edit. The lag is detectable for free: record which
`prompt_version` the articles were written from in the compile state, and report
"N articles were written from an older extraction". No LLM call, no network. This
is the same detect-and-report-never-auto-spend shape as C5 (revised documents)
and F5 (derived versus parent), so it is the third instance of an established
pattern rather than a new mechanism.

**`--extract-only`.** Extraction runs, then stops. This serves the workflow O1
chose markdown for — reading extractions in an editor is a first-class part of
tuning — by letting a prompt edit be re-extracted and inspected before anyone
pays for the write phase.

**Self-check.**

1. *Can the write phase consume a missing or stale extraction?* No. A document
   enters the write gate only because its checksum moved, and a moved checksum
   makes its extraction stale, so extraction has already handled it earlier in
   the same invocation. A failed extraction drops the document and is reported,
   the same shape as today.
2. *Does resumability break?* No. The `completed_ops` / `compiled_at` logic
   (`commands/compile.py:101,240`) moves wholesale into the write gate. Slightly
   better than today: a crash during extraction leaves persisted extractions that
   the next run reads as fresh, so nothing is paid twice.
3. *Any surprising spend direction?* One, and it is the point of the feature: a
   document whose text is unchanged but whose prompts moved now costs money,
   where today nothing sees it at all. It also means the first compile after this
   lands re-extracts the whole KB — S1's 1.4 USD [superseded — see Corrections: 17.5 USD], same basis.
4. *Does the worker path change?* No. A worker task handles one document,
   extracts it and writes it, which is correct for a document that just arrived.
   X constrains the CLI compile gate only. C3 governs the extraction *file's*
   bytes, not the gating, so the two paths do not diverge again here.

---

## Consequential change, recorded so it is not a surprise

Once stages 1 and 3 land, `KBStore.save_extract_cache`
(`storage/store.py:265`) has no callers: the writer moves to the extraction
layer (`commands/compile.py:146`), the catalog reader goes away
(`storage/index.py:164`), and derive copies a named file instead
(`derive/_layout.py:195`). Per the repository's rule on orphans created by one's
own change, it gets deleted. `load_extract_cache` (`storage/store.py:257`) goes
with it: S1 dropped the migration, which was its one remaining caller.

Test files that reference the extract cache and will need updating:
`py/tests/test_derive_layout.py`, `test_commands_compile.py`,
`test_storage_paths.py`, `test_storage_index.py`, `test_derive_kb.py`.

`py/src/kb_ai/commands/derive.py` also has operator-facing copy naming "the
source knowledge base's extract cache" in its declined-run `next_step`; it needs
to name the extraction layer instead.

---

## Resuming

Read `spec.md` (O1–O7 resolved, no open questions there) and this file. Nothing
here is open: S1 and Q1–Q10 were all settled on 2026-08-07 and each decision is
recorded inline under its own Status.

Two steps remain, in this order.

1. **Apply the spec edits in one pass.** S1 lists its own; the rest, gathered from
   the individual decisions: B4's dump options extend to the body (Q3); B9 shrinks
   to one sentence and B10 all but disappears (Q1); B2's `surprising: no`
   illustration becomes `false` (Q3); G5's claim that `extract_strategy` is
   unknowable is wrong regardless (Q9); O5 and G7's "an unmigrated KB would
   re-extract in full" is false as written (S1); H2 gains a fixture for a string
   field whose value is `"no"` (Q3); H3 must run both routes in one process (Q2)
   and gains a CRLF content-identity assertion (Q6); C4 gains the daemon's
   read-before-extract behaviour (Q4) and O4 a note that it is not re-extraction;
   D-something gains the wiki-lag report and `--extract-only` (Q10).
2. **Write `plan.md`** — stages in the spec's "Implementation sequencing" order
   minus the migration work, one verification line per task, formatted after
   `docs/features/derive-topic-kb-from-catalog/plan.md`.

Changes that fall outside the extraction layer proper but were decided here, so
they need to appear as explicit plan tasks rather than being discovered during
implementation: the two-gate split of `commands/compile.py` (Q10), the raise at
`core/extract.py:617` (Q5), the relative `source_ref` fix in the Go worker (Q7),
and the newline normalisation in `_handle_extract` (Q6).

Code already read and verified, so it does not need re-reading to answer these:
`core/extract.py`, `storage/store.py`, `storage/index.py`,
`commands/compile.py`, `server_daemon.py`, `prompts/registry.py`,
`prompts/__init__.py`, `_context.py`, `_errors.py`, `_frontmatter.py`,
`derive/_layout.py`, `derive/__init__.py`, `commands/pipeline/_phase_write.py`,
`internal/bridge/api.go`, `internal/worker/worker.go`, `internal/api/submit.go`.
