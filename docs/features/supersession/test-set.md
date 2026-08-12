# Supersession test set: measuring the failure before choosing a fix

Status: test set built, labels not yet adjudicated, and the fixture needs
restructuring before it can score anything — compiling all 38 documents in one run
routes each version chain into a single `merge→create` call and leaves the merge
paths untested. See FX2 in [spec.md](spec.md). Written 2026-08-10.
Companion to [design-options.md](design-options.md), which lists the options this
set exists to separate.

The design options were written from code reading. Two of their claims are
empirical and neither had a number attached: how often a later document actually
supersedes an earlier one, and whether the current pipeline gets it wrong when it
happens. This set answers both from a real corpus, and it is built so that each
option can be scored on the same cases rather than argued about.

One result already contradicts the design doc's framing. On the clearest Shape B
case in the corpus — a gateway design document at v1.5 and v1.7 as two separate
Lark documents — the current pipeline produced an article that states the v1.7
scope and cites the range: "The design is documented in v1.5–v1.7 of the
specification". The design doc's "Today it states both" is not universally true.
See [Two adjudicated cases](#two-adjudicated-cases).

## The corpus

`~/.knowledge` is a KaaS knowledge base compiled before the extraction layer
existed: 996 raw documents, 675 wiki articles, and a legacy `.extract-cache/`
instead of `extraction/`.

It has been converted to the current four-layer scheme at
`data/kb-knowledge/` (gitignored). Two facts made the conversion free:

- Raw paths were kept nested (`raw/docs/...`, `raw/meetings/...`) rather than
  flattened the way `fetch` names them. `KBStore.extraction_rel_path`
  (`py/src/kb_ai/storage/store.py:78-96`) mirrors any relative path, and
  flattening would have invalidated every `sources:` entry in the existing wiki.
- The legacy cache is keyed by `sha256(file_text)[:16]`, byte-identical to
  `_compute_checksum` (`py/src/kb_ai/storage/store.py:56-57`). 982 of 996
  documents matched, so their extractions were re-serialized into
  `extraction/` through the real serializer with no LLM call.

Verified by the shipped checker rather than by the migration script:

```
$ kb-ai check --kb data/kb-knowledge
[check] extractions: 982 match, 14 missing, 0 mismatched (of 996 documents)
```

Provenance is recorded honestly: `prompt_version: legacy-extract-cache`, so
`staleness()` reports `prompt_version changed: 'legacy-extract-cache' ->
'40173bb799fc'` and a compile re-extracts rather than serving a payload produced
by a prompt nobody can identify. Two consequences worth stating:

- The migrated payloads are usable for label drafting at zero cost, but a compile
  of any subset re-extracts it at 0.0551 USD per document.
- The existing `wiki/` is a historical artifact, compiled by prompt versions that
  no longer exist. It is evidence that the failure mode occurs; it is not a
  baseline any run can reproduce. The baseline has to be re-measured.

The old cache also carried a `connections` list that `ExtractionResult`
(`py/src/kb_ai/core/extract.py:51-59`) has no field for. It was dropped for all
982 documents.

## Conformance with the current scheme

Audited layer by layer against `data/kb-2026-06`, the output of the current
pipeline. Five gaps closed for nothing, one left open, and one defect found in
the current pipeline rather than in the conversion.

Closed:

- **`.compile-state.json`** copied from the source KB. Its checksums are
  `sha256(text)[:16]`, verified identical for all 996 present documents (45 of
  its 1041 entries name files no longer under `raw/`), so reusing it is free and
  does not flag anything as revised. Without it the composition gate would
  recompile all 996 documents — about 200 USD — and `wiki_lag` folded over an
  empty state, reporting a vacuous "0 behind". It now reports the truth: `996
  behind the extract prompt (first run), 996 behind the write prompt (first
  run)`.
- **Category directories** renamed to the singular names the current pipeline
  uses: `wiki/decisions` → `wiki/decision`, and the same for concept, project
  and `people` → `person`. 675 of the 682 articles moved — the 7 under
  `personal-growth` keep their directory — with 45 plural `type:` values
  (40 `decisions`, 5 `concepts`) normalised, 9 articles carrying a literal
  `wiki/<plural>/…` path in their body rewritten. Without this the first compile
  would write `wiki/concept/` beside the existing `wiki/concepts/` and split the
  tree.
- **`kaas.json`** written, freezing `DEFAULT_CATEGORIES` plus `personal-growth`.
  That category has 7 articles and which of the six it belongs to is a content
  judgement, so it is frozen as its own rather than folded in —
  `resolve_categories` exists for exactly this.
- **`index/document-index.md`** built. It did not exist, so `existing_documents()`
  returned nothing and `derive --select-from` had nothing to select from.
  `index/terms.md`, which no current writer produces, was removed. Both index
  rebuilds are pure functions over the tree and cost nothing.

Left open: **no article carries a `summary:`** field (0 of 682, against 78 of 78
in `data/kb-2026-06`). The catalog falls back to `_derive_summary` over the body,
which after the rebuild produced a prose first paragraph for every line rather
than a heading, so the practical cost is lower than the missing field suggests.
Filling it properly needs a write-phase pass.

Also left open by design: the extraction layer records
`prompt_version: legacy-extract-cache`, so all 982 are stale against
`40173bb799fc` and any compile re-extracts at 0.0551 USD per document. The old
`.classify-cache` was deliberately not copied: its filenames are already in the
current `{checksum}-{articles_hash}-{categories_hash}` shape, but its
`categories_hash` is `e6ca8913` and no current category list produces that
(`DEFAULT_CATEGORIES` gives `0bf6b426`), so not one entry could hit.

**Defect in the current pipeline, not in the conversion — since fixed.** `distill`
prepends `<!-- source: ... -->` to every file it ingests
(`py/src/kb_ai/distill.py:82`), which made `split_frontmatter` return None and
`_document_frontmatter` degrade to `{}`. Measured before the fix: 0 of 108
document-index lines in `data/kb-2026-06` carried a date or a source, and their
titles were filename stems; the same held for all four `distill`-built KBs under
`data/`, while `data/kb-knowledge` carried a date on 996 of 996. This was
load-bearing for the supersession design: the date that option D4 proposes to read
at write time is the same field this dropped. Filed as issue #37 and fixed in the
raw-document reader, which skips leading HTML comments before parsing — the same
108 documents now yield 108 dated lines with no re-ingest, so D4 is unblocked and
blocker 2 in [design-options.md](design-options.md) records the fix.

## Ground truth that costs nothing

Raw frontmatter from the Lark fetch path carries `id`, `date` and `checksum` on
all 996 documents. That gives lineage without any judgement call:

- **Shape A** (same document revised): same `id`, more than one file. 94 groups
  covering 202 files. Different `checksum` means the content moved: 39 groups.
  Identical `checksum` means the same bytes were ingested twice under two
  filenames: 55 groups.
- **Shape B** (v1 and v2 as separate documents): same title after stripping a
  trailing version marker, different `id`. 40 groups.

Line-level diffstat then separates the ones worth labelling from the ones that
only look like revisions. Strata, over all 134 lineage groups:

| Stratum | Rule | Groups | With a shared article | Role in the set |
|---|---|---|---|---|
| A1-rewrite | similarity < 0.55 | 37 | 10 | strongest positives |
| A2-edit | removed > 3 lines, similarity ≥ 0.55 | 11 | 3 | positives |
| B-append-only | removed ≤ 3 lines, added > 3 | 9 | 4 | negative controls |
| C-noise | added and removed both ≤ 3 lines | 22 | 18 | excluded |
| D-duplicate | identical checksum | 55 | 34 | double-counting controls |

"With a shared article" means every member of the group appears in the `sources:`
list of one article — the only groups where the pipeline was actually asked to
reconcile the versions. 101 of 675 articles (15%) cite two or more members of one
lineage group.

Two exclusion rules were needed and both come from the data:

- **Cross-source title collisions are not lineage.** `raw/docs/` and
  `raw/meetings/` can hold a document and the recording of the meeting that
  discussed it under the same title. Similarity near zero, and neither
  supersedes the other. Two groups excluded.
- **A person's name is not a document title.** Three meetings named `Cara`
  collide under the Shape B rule. Excluded.

## The cases

Fixture at `data/kb-supersession-fixture/` (gitignored): 38 raw documents with
their migrated extractions, ready to compile. Regenerate with the commands in
[Regenerating](#regenerating).

Each case still needs a label before it can score anything. The label is three
lists, drafted from the diff and from the migrated extractions, then confirmed by
a human:

- `superseded` — asserted by the earlier version, contradicted or dropped by the
  later one. An article stating one of these as current is the failure.
- `replacement` — what the later version says instead. An article missing one of
  these has lost the correction.
- `control` — asserted by the earlier version and kept by the later one. An
  article missing one of these means a variant is deleting too aggressively.

Positives. All are same-source, and the article named is the one whose `sources:`
holds the whole chain. In the Chain column a bare date such as `2026-04-17-`
means the same filename under a different date prefix, in the same directory.
Article paths are given as they stand in `~/.knowledge`; in `data/kb-knowledge`
the same file is under the singular category directory, so
`wiki/decisions/x.md` there is `wiki/decision/x.md`.

| # | Shape | Chain (dates) | Lines, sim | Article | Label |
|---|---|---|---|---|---|
| P1 | A | `raw/docs/2026-04-08-入离职-ai-岗位-it-方案.md` → `2026-04-17-` | 52→283, 0.042 | `wiki/decisions/ai-tools-onboarding-offboarding-automation.md` | adjudicated, see below |
| P2 | A | `raw/docs/2026-04-14-infra-双周会-2026_h1.md` → `2026-04-17-` | 2042→1085, 0.448 | `wiki/decisions/infra-ai-devops-roadmap-decisions.md` | to draft |
| P3 | A | `raw/docs/2026-04-20-cht-knowledge-跨系统知识蒸馏与索引方案.md` → `2026-04-30-` | 1155→981, 0.096 | `wiki/concepts/cht-knowledge-plugin-system.md` | to draft |
| P4 | A | `raw/docs/2026-05-19-交易回滚trd.md` → `05-26` → `06-02` → `06-04` | 4782→5860, 0.878 | `wiki/concepts/derivatives-position-field-schema.md` | to draft; 4-version chain |
| P5 | B | `raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单.md` → `raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单-v3.md` | 5494→6397, 0.217 | `wiki/projects/bybit-ai-trading-skill.md` | to draft; same-day pair |
| P6 | B | `raw/docs/2026-03-23-通用网关设计方案-v15.md` → `raw/docs/2026-03-30-通用网关设计方案-v17.md` | 2283→2902, 0.794 | `wiki/concepts/cgw-universal-gateway-architecture.md` | adjudicated, see below |
| P7 | B | `raw/docs/2026-04-09-2026-h1成本进展跟进.md` → `2026-05-14-` | 544→918, 0.731 | `wiki/projects/cloud-infrastructure-cost-optimization-2026h1.md` | to draft |
| P8 | B | `raw/docs/2026-04-12-ai-项目全景-分类总览.md` → `2026-04-13-` | 1709→1619, 0.079 | `wiki/decisions/ai-project-portfolio-status-q2-2026.md` | to draft |
| P9 | B | `raw/docs/2026-04-23-bybit-ai-toc-整体立项.md` → `2026-05-11-` | 281→685, 0.168 | `wiki/projects/tradegpt-toc-product-roadmap.md` | to draft |
| P10 | B | `raw/local/2026-03-05-2025-engineering-efficiency-report.md` → `raw/local/2026-03-06-2025-engineering-efficiency-report-v2.md` | 237→392, 0.067 | `wiki/decisions/2025-engineering-efficiency-report-full-data-decisions.md` | to draft |

Negative controls. The later version only adds. Marking anything superseded here
is a false positive, and the design doc's stated reason for preferring
current-plus-trail is exactly that this error should stay recoverable.

| # | Chain | Diff | Article |
|---|---|---|---|
| N1 | `raw/docs/2026-04-01-ai分析环境专项建设讨论.md` → `2026-04-17-ai分析环境接入流程讨论.md` | +100/−1 | `wiki/decisions/dbu-ai-data-analysis-architecture.md` |
| N2 | `raw/docs/2026-04-17-效能零信任项目-周例会.md` → `2026-05-06-` | +403/−3 | `wiki/projects/zero-trust-security-platform.md` |
| N3 | `raw/meetings/2026-03-10-realclaw安全评估.md` → `2026-03-11-` | +200/−1 | `wiki/decisions/realclaw-byreal-security-assessment.md` |
| N4 | `raw/meetings/2026-03-10-video-meetingai整体推进---固定对接群.md` → `2026-03-11-` | +114/−1 | `wiki/projects/ai-capability-building.md` |

Duplicate controls (U1–U4, sampled from the 34 identical-checksum groups that
share an article). Same bytes ingested twice. Correct behaviour is one
contribution, not two, and no supersession marker at all. These are in the
fixture because a variant that reasons about "which source is newer" will meet
them, and 55 groups is too many to leave untested.

## Two adjudicated cases

**P1 fails today.** The 04-08 version's 现有情况 section says only ~140 users have
Lark AI Summary. The 04-17 version drops that section and adds a step marked
"（新增，4.17 已上线）". The article still states the old number as current in four
places, including a table row `| Lark AI Summary | ~140 users only |` and a
callout beginning "Notable finding: Only approximately 140 users currently have
access", plus a pending action item to consult Lark on pricing. The correction
never landed.

Note what this case does *not* establish: v2 dropped the claim rather than
contradicting it. Whether a dropped claim counts as superseded is a labelling
rule this set has to fix explicitly, and it is the same question D1 answers for
the article body.

**P6 succeeds today.** v1.5 frames the problem as "当前 BGW 是一个面向业务的重量级
网关"; v1.7 reframes it as "当前团队维护着四套独立网关系统" and widens the scope to
consolidating bgw, bgwg, bgwtp and LiteLLM. The article leads with the v1.7
framing and names the version range it covers.

The likely reason it worked is worth testing directly: both documents carry their
version and date in the body text (`> 版本: v1.7`, `日期: 2026-03-30`), so the
writer had an ordering signal inside the payload. The design doc identifies this
as an accidental signal rather than a guaranteed one
([design-options.md](design-options.md), blocker 2). If the failures cluster on
documents without an internal version marker, then path A — make the signal
explicit — is the whole fix, and paths B and C are over-buying.

## Scoring

Per case, over the produced article:

| Metric | Measured as | Failure |
|---|---|---|
| Correction landed | each `replacement` present and stated as current | missing |
| Staleness | any `superseded` item present and stated as current | present |
| Trail | any `superseded` item present and marked as superseded | — |
| Collateral | each `control` item still present | missing |
| Size | article bytes, against the pre-run article | growth |
| False positive | on N1–N4, any supersession marker at all | present |
| Double count | on U1–U4, the duplicate contributing twice | present |

Staleness and Trail are separate columns on purpose: that pair is what separates
the D1 options, and no single score can.

- latest-wins: Staleness 0, Trail 0
- current-plus-trail: Staleness 0, Trail 1
- article family: two articles, and Trail is not applicable

For D2 the discriminating column is Correction landed on P1–P10 with False
positive held at 0 on N1–N4. Path A leaves the ordering judgement to the model;
path B hands it an explicit claim; path C removes the question by recomposing.
Path A is worth shipping first if and only if it clears the positives without
tripping the negatives.

Deciding "stated as current" versus "marked as superseded" needs an adjudicator.
For a set this size, an LLM judge over (labelled item, article) with the human
labels as the reference is affordable; the labels themselves stay human-owned.

## Cost

Unit costs measured on this corpus, from `~/.knowledge/.cost.db`, model
`claude-sonnet-4-6`, all phases: extract 0.0551 USD per document (n=423),
classify 0.0847 USD per op (n=191), write 0.1246 USD per merge op (n=320). The
database was added partway through this KB's history, so it covers 423 of 996
extractions rather than all of them.

One full run over the 38-document fixture: 2.09 extract + 3.22 classify + 4.73
write = **about 10 USD**, taking one merge op per document as an upper bound.
Baseline plus three variants is roughly 40 USD.

For comparison, converting all 996 documents cost nothing, but compiling them
would not: about 55 extract + 84 classify + 124 write, so **200 USD and up** for
one pass. The fixture exists to avoid that. Recompiling the whole corpus is only
worth it if a variant needs to be measured against the full 15% of articles that
cite a lineage group, and that decision should follow the fixture result, not
precede it.

## What this set cannot decide

- Whether the historical `wiki/` failures would reproduce today. Its articles
  were written by prompt versions that no longer exist, so those failures are
  existence proofs, not measurements.
- Classify's instability. Two of the four fixture strata assume a chain lands in
  one article; if classify routes a version elsewhere on a given run, the case
  scores nothing rather than scoring a failure. Same instability the design doc
  lists as out of scope (`docs/articles/kaas-four-layers.md:308-313`).
- Whether a dropped claim is superseded. That is a labelling rule to be fixed
  before scoring, and it is upstream of D1 rather than answered by the data.
- The 14 documents with no cached extraction. They are in `data/kb-knowledge/`
  with no `extraction/` file and are outside every case.

## Regenerating

The corpus conversion and the case selection are mechanical and cost nothing:

```
python3 /tmp/supersession/convert_kb.py     # ~/.knowledge -> data/kb-knowledge
kb-ai check --kb data/kb-knowledge          # expect: 982 match, 14 missing, 0 mismatched
```

The scripts under `/tmp/supersession/` are throwaway. They move into
`py/scripts/` with tests when the harness is built, which is after D1 and D2 are
answered — a harness that scores options nobody chose is the wrong thing to own.
