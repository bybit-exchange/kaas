# Supersession test set: measuring the failure before choosing a fix

Status: test set built; staging landed under FX1; labels **drafted and awaiting
item-by-item confirmation** in [labels.md](labels.md) — 44 contradictions, 31 drops
and 42 controls across the seven scoring cases, of which 27 contradictions are
still stated as current in today's articles. Both blocking rulings are settled
(2026-08-15): **P2 is withdrawn** from the positives and kept as a counter-case,
because its frontmatter date inverts its content order, and **P7's
measurement-time reading is accepted**, so it keeps its 8 contradictions.

All 128 drafted items have since been **independently verified** in fresh contexts,
one per case: 111 verified, 4 line-corrected, 13 disputed, none unverifiable. The
confirm pass therefore starts from a queue of
[19 rulings](labels.md#independent-verification-pass-2026-08-15) rather than from 122
unchecked rows, and **seven are taken with 12 left**. Nineteen items were raised: one
asked whether a document outside P5's declared sources fed its article, and
investigation settled that on the article's own content, while ruling V19 raised a
twentieth. Three of the rulings move the totals above and **all three are taken**:
**V1 struck P8's four
contradictions** as de-specifications of one column rename, so the gating set is **six
cases plus P6**, not seven, and P8 stays in on its 6 drops and 6 controls; **V2 struck
P9-C1**, which v2 preserves item-for-item in material already scored as a control; and
**V3 reclassified P10-C6 as a drop**, since it paired a mean against a median over a
different span. That is why the totals read 44 and not 50. Verification also found that these articles merge more
sources than the chain under test, which confounds the staleness column; the 61% figure
is motivation, not measurement — and since **V20** keeps P5 out of that column for good,
61% (27 of 44) is the all-cases reading while the five cases actually judged on it read
**69% (27 of 39)**. Written 2026-08-10, labels drafted 2026-08-14, rulings and
verification 2026-08-15 to 2026-08-16.
Companion to [design-options.md](design-options.md), which lists the options this
set exists to separate, and to [spec.md](spec.md), whose FX and VF criteria say
what this set has to deliver before A1 can be judged.

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
See [Three adjudicated cases](#three-adjudicated-cases).

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
  of any subset re-extracts it at 0.0551 USD per document. **Not through the
  loader, as of 2026-08-14**: they were serialized at `schema_version: 1` and
  `storage/extraction.py` now reads 2, so `extraction.load` refuses all 982 with
  `unsupported schema_version`. The files are still readable as text — the RP3
  measurements above parsed them directly, and so did FX3's label drafting, which
  is why **no re-serialization is needed** despite an earlier note here saying it
  was. The version is checked inside `parse` (`storage/extraction.py:209`), which
  only `load` calls; `load_header` never checks it, so the catalog and selection
  paths read these files fine. Re-serializing would also buy a compile nothing:
  `prompt_version: legacy-extract-cache` makes every one of them stale, so a
  compile re-extracts whatever the schema line says.
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
  trailing version marker, different `id`. 42 groups.

**Corrected 2026-08-14, when the rule became code** (`storage/lineage.py`, spec
RP4). The script that produced the counts above was thrown away and only its output
survived, so the rule was reconstructed against that output. It reproduces all 40 of
those shape-B groups and finds two more, both from limits of the original script
rather than from a looser rule:

- `Bybit Skill Testnet 测试报告` at `v1.0.0`. The original marker did not match a
  three-part version, though it did match `(v3)`. A genuine group, so 41 by title.
- A `raw/docs` and `raw/local` copy of one all-hands document whose titles differ
  only in capitalisation, which the original compared case-sensitively. It is a
  cross-source collision, so the exclusion below removes it either way — 42 titles
  match, 41 of them are groups worth counting.

Applying the two exclusions leaves **38** groups after the cross-source rule and
**37** after the person-name rule.

Line-level diffstat then separates the ones worth labelling from the ones that
only look like revisions. Strata, over all 131 lineage groups, as
`py/scripts/select_cases.py` reports them:

| Stratum | Rule | Groups | With a shared article | Role in the set |
|---|---|---|---|---|
| A1-rewrite | similarity < 0.55 | 36 | 10 | strongest positives |
| A2-edit | removed > 3 lines, similarity ≥ 0.55 | 10 | 3 | positives |
| B-append-only | removed ≤ 3 lines, added > 3 | 8 | 6 | negative controls |
| C-noise | added and removed both ≤ 3 lines | 22 | 18 | excluded |
| D-duplicate | identical checksum | 55 | 43 | double-counting controls |

The rules are evaluated in a fixed order, and it is not the order of the table:
identical checksum, then append-only, then noise, then similarity. A version that
only appends is a negative control however much it appends, and a large enough
append drives similarity below 0.55 on its own — two groups here add 134 and 182
lines while removing 2 and 1, at similarity 0.056 and 0.367. Testing similarity
first put both of those in the positive set.

The diffstat runs over each document's **body**, never its frontmatter: every
version differs in `date`, `id` and `checksum`, so a whole-file diff reports three
changed lines between two files whose prose is identical — enough on its own to move
a group out of the noise stratum.

"With a shared article" means every member of the group appears in the `sources:`
list of one article — the only groups where the pipeline was actually asked to
reconcile the versions. 123 of 682 articles (18%) cite two or more members of one
lineage group.

**Corrected 2026-08-14 together with the group counts above.** The numbers first
recorded here were 134 groups with 37/11/9/22/55 per stratum and 10/3/4/18/34
sharing an article, and 101 of 675 articles at 15%. Three things moved them: the
shape-B exclusions are now applied by the selector rather than by hand afterwards
(−3 groups, and the `v1.0.0` chain the original missed is +1); the append-before-
similarity ordering moved two groups from A1-rewrite to B-append-only; and
`sources:` entries holding a comma-joined batch are now split, which is what raised
the shared-article column — 43 duplicate-stratum groups rather than 34, 6
append-only rather than 4. 46 articles in this corpus carry such an entry, so
reading each as a single path hid every group behind a batch-merged article.

Two exclusion rules were needed and both come from the data:

- **Cross-source title collisions are not lineage.** `raw/docs/` and
  `raw/meetings/` can hold a document and the recording of the meeting that
  discussed it under the same title. Similarity near zero, and neither
  supersedes the other. Two groups excluded — four titles collide across sources
  once the marker forms above are matched, and the implemented rule splits rather
  than drops them, so two members that do share a source stay a group.
- **A person's name is not a document title.** Three meetings named `Cara`
  collide under the Shape B rule. Excluded.

One more thing the corpus says, found when RP3 was wired up and load-bearing for
the report's usefulness rather than for these counts: a recurring meeting series has
one fixed title and a new `id` per occurrence, so it satisfies the Shape B rule
exactly. Of the 41 (article, group) pairs the rule reports over `wiki/`, 4 are real
version chains and 37 are recurring series — `AI团队日会` alone puts 11 members in one
article. That is why the report carries a version-marker flag, and why the flag is
not a filter: P7, P8 and P9 are positives whose two versions share a title verbatim.

## The cases

Fixture at `data/kb-supersession-fixture/` (gitignored): 38 raw documents with
their migrated extractions, ready to compile. Regenerate with the commands in
[Regenerating](#regenerating).

Each case still needs a label before it can score anything. The label is four
lists, drafted from the diff and from the migrated extractions, then confirmed by
a human:

- `superseded-contradiction` — asserted by the earlier version, and the later one
  asserts something incompatible about the same subject. There has to be a
  specific later statement to point at. An article stating one of these as
  current is the failure A1 is judged on.
- `superseded-drop` — asserted by the earlier version and simply absent from the
  later one, which says nothing incompatible. Measured and reported, but it does
  not gate: Q1 scopes A1's trigger to explicit contradiction and sends dropped
  claims to the RP1–RP3 report instead, so scoring A1 on drops would judge it
  against work it does not contain. A restated claim is not a drop.
- `replacement` — what the later version says instead, one entry per
  `superseded-contradiction` entry. An article missing one of these has lost the
  correction.
- `control` — asserted by the earlier version and kept by the later one, restated
  in new words included. An article missing one of these means a variant is
  deleting too aggressively.

Splitting the first list is what keeps FX7 honest, and it is not free: P1, the
one case already adjudicated as failing, is a **drop** rather than a
contradiction, so the clearest historical failure in this set no longer gates the
thing it motivated. That is the correct trade: P1 is evidence for A2's RP1 arm,
not evidence about A1. But it means the positives that gate A1 are the seven
scoring cases plus P6, and a thin contradiction list on any of them shrinks the
set that decides whether A2 gets bought. P2 is the second such subtraction, for an
unrelated reason given below.

Positives. All are same-source, and the article named is the one whose `sources:`
holds the whole chain. In the Chain column a bare date such as `2026-04-17-`
means the same filename under a different date prefix, in the same directory.
Article paths are given as they stand in `~/.knowledge`; in `data/kb-knowledge`
the same file is under the singular category directory, so
`wiki/decisions/x.md` there is `wiki/decision/x.md`.

| # | Shape | Chain (dates) | Lines, sim | Article | Label |
|---|---|---|---|---|---|
| P1 | A | `raw/docs/2026-04-08-入离职-ai-岗位-it-方案.md` → `2026-04-17-` | 52→283, 0.042 | `wiki/decisions/ai-tools-onboarding-offboarding-automation.md` | adjudicated, see below |
| P2 | A | `raw/docs/2026-04-14-infra-双周会-2026_h1.md` → `2026-04-17-` | 2042→1085, 0.448† | `wiki/decisions/infra-ai-devops-roadmap-decisions.md` | [withdrawn](labels.md#p2--infra-biweekly-review-withdrawn-counter-case) — **counter-case, scores nothing**, see below |
| P3 | A | `raw/docs/2026-04-20-cht-knowledge-跨系统知识蒸馏与索引方案.md` → `2026-04-30-` | 1155→981, 0.096† | `wiki/concepts/cht-knowledge-plugin-system.md` | [drafted](labels.md#p3--cht-knowledge-distillation-and-indexing) — 8C / 5D / 6K |
| P4 | A | `raw/docs/2026-05-19-交易回滚trd.md` → `05-26` → `06-02` → `06-04` | 4782→5860, 0.878 | `wiki/concepts/derivatives-position-field-schema.md` | [drafted](labels.md#p4--trade-rollback-trd-four-versions) — 10C / 4D / 6K, 9 of 10 stale |
| P5 | B | `raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单.md` → `raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单-v3.md` | 5494→6397, 0.217† | `wiki/projects/bybit-ai-trading-skill.md` | [drafted](labels.md#p5--bybit-trading-skill-api-inventory) — 5C / 5D / 6K, **0 stale under the drafted reading**; both versions share a frontmatter date and the payload orders them backwards, so V19 held it out of the gate and V20 keeps it out — the ruled fix withdraws the ordering claim rather than correcting it. Its 5C still count in the set totals; **V21** carries the disposition, v3's frontmatter date being six days off its own body |
| P6 | B | `raw/docs/2026-03-23-通用网关设计方案-v15.md` → `raw/docs/2026-03-30-通用网关设计方案-v17.md` | 2283→2902, 0.794 | `wiki/concepts/cgw-universal-gateway-architecture.md` | adjudicated, see below |
| P7 | B | `raw/docs/2026-04-09-2026-h1成本进展跟进.md` → `2026-05-14-` | 544→918, 0.731 | `wiki/projects/cloud-infrastructure-cost-optimization-2026h1.md` | [drafted](labels.md#p7--2026-h1-cost-progress-tracking) — 8C / 0D / 6K, 6 of 8 stale; **V4 ruled**, the co-source bounds the causal claim to C8 but not the score |
| P8 | B | `raw/docs/2026-04-12-ai-项目全景-分类总览.md` → `2026-04-13-` | 1709→1619, 0.079† | `wiki/decisions/ai-project-portfolio-status-q2-2026.md` | [drafted](labels.md#p8--ai-project-portfolio-overview) — **0C** / 6D / 6K, its 4 contradictions struck by V1 |
| P9 | B | `raw/docs/2026-04-23-bybit-ai-toc-整体立项.md` → `2026-05-11-` | 281→685, 0.168† | `wiki/projects/tradegpt-toc-product-roadmap.md` | [drafted](labels.md#p9--bybit-ai-toc-project-initiation) — **6C** / 5D / 6K, C1 struck by V2 |
| P10 | B | `raw/local/2026-03-05-2025-engineering-efficiency-report.md` → `raw/local/2026-03-06-2025-engineering-efficiency-report-v2.md` | 237→392, 0.067 | `wiki/decisions/2025-engineering-efficiency-report-full-data-decisions.md` | [drafted](labels.md#p10--2025-engineering-efficiency-report) — **7C** / **6D** / 6K, C6 reclassified as a drop by V3 |

† The `sim` value is distorted downward by `difflib`'s `autojunk` heuristic and
should not be read as a body-similarity fraction — P8's 0.079 is 0.928 with the
heuristic off, on two files sharing 1,544 of 1,709 lines. The recorded values are
the ones the corpus was stratified with, so they are kept rather than silently
replaced; the measurement and what it costs are in
[labels.md](labels.md#note-the-recorded-similarity-figures-are-distorted).

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

### Controls verified, 2026-08-15

The controls were checked directly, because they are what protects A1 from being
**wrongly failed**: if a chain labelled purely additive in fact contains a
contradiction, then A1 reporting that contradiction correctly would be scored as a
false positive. All eight hold.

| # | Claim | Result |
|---|---|---|
| N1 | later version only adds | **valid.** The only body line not carried forward is the H1 itself — a retitle from 「AI分析环境专项建设讨论」 to 「AI分析环境接入流程讨论」. A retitle is a scope shift, not a contradicted claim |
| N2 | later version only adds | **valid.** An append-at-top rolling meeting log. Its shared 「周例会 0428」 section is unedited between versions apart from one heading whitespace change and a removed `<!-- Unsupported block type: 53 -->` extraction artifact |
| N3 | later version only adds | **valid.** One blank line differs; nothing else |
| N4 | later version only adds | **valid.** One blank line differs; nothing else |
| U1–U4 | same bytes, two dates | **valid, all four.** Bodies are byte-identical after frontmatter is stripped, and each pair's `checksum` field matches exactly (`49fa91ea…`, `248f8e30…`, `34e46297…`, `224bee9b…`) while `date` differs. U1 is the most adversarial: `ai-应用部署平台方案` is identical across a **six-week** gap, 2026-03-04 to 2026-04-17 |

Precision note on N1–N4: "only adds" is right in substance but not literally true for
N1, whose title changed. State it as *adds only, apart from a retitle*.

**N2 carries the same wrong-date pathology as P2**, and this is the second named
instance in the fixture rather than a P2 quirk. The file dated `2026-04-17` contains
「周例会 0428」 (L12) and 「周例会 0422」 (L177) — both meetings held *after* its own
date — and the file dated `2026-05-06` contains 「周例会 0512」 (L37). Unlike P2 this
does **not** invalidate the control, because the pair still orders correctly: the
05-06 file is a strict superset of the 04-17 one. But it is direct evidence that a
frontmatter `date` can misdescribe its own content in the fixture, which is the open
question spec.md records against A2.

## Three adjudicated cases

**P1 fails today.** The 04-08 version's 现有情况 section says only ~140 users have
Lark AI Summary. The 04-17 version drops that section and adds a step marked
"（新增，4.17 已上线）". The article still states the old number as current in four
places, including a table row `| Lark AI Summary | ~140 users only |` and a
callout beginning "Notable finding: Only approximately 140 users currently have
access", plus a pending action item to consult Lark on pricing. The correction
never landed.

**Verified 2026-08-15, and it holds exactly.** v1 L21 `## 现有情况` and L26
「目前仅有 140 左右用户拥有 AI Summary 权限」; in v2 both `现有情况` and `140` return **0
hits**, so the section is dropped and the figure is not restated; v2 L41 carries
「**Step 4｜OpenClaw 机器人创建（新增，4.17 已上线）**」. The article has exactly **four**
occurrences of `140` — L39 (the quoted table row), L44 (the quoted callout), L241 and
L702 — and both quoted strings match verbatim.

Worth stating because it is unusual in this set: **P1 is not confounded.** Its article
compiles from 11 sources, but none of the nine co-sources asserts the ~140 figure —
the only other hit in any of them is a coincidental substring of the numeric `id`
`7612093357330714037`. So unlike P7, P1's four stale mentions are attributable to this
chain alone. That makes the motivating case's evidence stronger than the drafted
positives' on this axis, even though it is a drop and therefore does not gate A1.

Note what this case does *not* establish: v2 dropped the claim rather than
contradicting it. That labelling rule is now fixed — P1's items go in
`superseded-drop`, which is measured and does not gate A1 (see
[The cases](#the-cases)). So this case, the most legible failure in the set, is
evidence for A2's RP1 arm rather than a test A1 has to pass. Keeping it scored
under its own column is what stops that evidence from being quietly discarded.

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

**Verified 2026-08-15, and it holds.** v1 L25 carries 「当前 BGW 是一个面向业务的重量级网
关，存在以下问题：」 and v2 L25 「当前团队维护着**四套独立网关系统**，各自针对不同场景发展，
代码重叠、运维分散：」. Precision on the second quote: the source bolds the phrase, so it is
`当前团队维护着**四套独立网关系统**` rather than the plain string quoted above. The scope
widening also shows up in a second and cleaner place the adjudication does not cite — the
定位 line, 「定位: 通用业务网关，以 AI 接入场景为首期落地」 at v1 L17 against 「定位: 通用业务
网关，整合 bgw / bgwg / bgwtp / LiteLLM，以 AI 接入场景为首期落地」 at v2 L17. The article
leads with the v1.7 framing in its first sentence and names the range in the same one:
"documented in v1.5–v1.7 of the specification" (L15).

The superseded framing is absent in both languages — 0 hits for `重量级`, and 0 for
`heavyweight` or `business-oriented gateway` — so the pass is not an artefact of grepping
Chinese against an English article. One thing that could have read as stale and is not:
the article repeats BGW's own problem list at L21, including the `fasthttp` and
technical-debt items. v1.7 keeps that list — the same six-row 问题/描述 table, relocated
under a new `#### bgw（业务 HTTP 网关）` subheading at v1.7 L27, with 「使用 fasthttp 而非
byone rest，无法享受 byone 的 OTel Trace、熔断、Nacos 注册等开箱能力」 verbatim at v1.7 L68
against v1.5 L66. So v1.7 **subordinates** v1.5's framing to one of four gateways rather
than retracting its detail, and the article is repeating the newest source rather than
carrying an older one.

**P6 is not confounded either.** Its article compiles from three sources rather than the
chain's two, but the third — `raw/docs/2026-04-17-access-gateway技术方案.md` — returns 0
hits for 四套, bgwg, bgwtp and 重量级 and carries no version or date marker of its own; it
contributes §14 alone. So P6's success is attributable to this pair, just as P1's failure
is. That co-source is not staged in the fixture, which is how the fixture is built — chain
files only — so FX4's P6 re-compile sees two of three sources and cannot reproduce §14.
Score P6 on the framing, not on article completeness.

**One finding, and it lands on the design lesson rather than on the case.** v1's internal
version marker disagrees with v1's own title: frontmatter `title` (L5) and the H1 (L10)
both say 「通用网关设计方案 v1.5」, while the body marker at L13 says `> 版本: v1.6`. The
ordering signal P6's success is credited to is therefore present in both documents but
self-inconsistent in the earlier one. The case stands, since v1.6 still orders before
v1.7 — but the finding pushes toward path A rather than away from it: the accidental
signal is not merely unguaranteed, it can contradict the same document's own title, and a
reader taking the title sees v1.5→v1.7 where a reader taking the marker sees v1.6→v1.7.
It is a fifth instance of the shape recorded in
[labels.md](labels.md#note-within-version-ambiguity), and the first where the ambiguity is
about the version rather than about a claim.

Two reproductions, recorded because P6's is the one positives row carrying no `†`: its
line counts rebuild exactly at 2283→2902, and its 0.794 similarity is genuinely
undistorted — identical to three places with `autojunk=False`, over 2,131 of 2,283 shared
body lines. The missing dagger is correct rather than an oversight.

**P2 is withdrawn, because its date lies.** Ruled 2026-08-15. The file dated
2026-04-14 is a rolling document that accumulates meeting sections: its body
carries a `# 2026-05-04` heading as well as the `# 2026-04-17` one, its extraction
records `extracted_at: 2026-05-04`, and in the section both files date 2026-04-17
it reports figures three weeks newer than the file it supposedly precedes. Its
frontmatter `date` is its creation day, not its content day, so the chain runs
backwards relative to its content and scoring it would grade A1 as correct for
asserting an order that is wrong. It is kept as a counter-case with its label
intact — see [labels.md](labels.md#p2--infra-biweekly-review-withdrawn-counter-case)
for the evidence and for the inverted reading to apply if it is ever revived.

This is a finding about the design and not only about the fixture, which is why it
is recorded here rather than in a footnote. WP2 takes the ordering signal from raw
frontmatter, so on such a document A1 hands the writer a date that is confidently
wrong; Q2 and D3 provisioned for a *missing* date, not a wrong one. Scoped rather
than alarmed: 1 of 12 fixture chains inverts, while 101 of 996 corpus documents
(10.1%) carry a body heading date later than their frontmatter date. The symptom is
common and the fatal form is rare. N3 and N4 are stale by about 30 days but their
relative order holds, so they remain valid controls.

## Scoring

Per case, over the produced article:

| Metric | Measured as | Failure |
|---|---|---|
| Correction landed | each `replacement` present and stated as current | missing |
| Staleness | any `superseded-contradiction` item present and stated as current, where the newest source in the compile set that speaks to that item asserts otherwise | present — this is the gating column |
| Staleness (drop) | any `superseded-drop` item present and stated as current, on the same reading of "newest" | recorded, does not gate (Q1 sends these to the RP1–RP3 report) |
| Trail | any `superseded-contradiction` item present and marked as superseded | — |
| Collateral | each `control` item still present | missing |
| Size | article bytes, against the pre-run article | growth |
| False positive | on N1–N4, any supersession marker at all | present |
| Double count | on U1–U4, the duplicate contributing twice | present |

**Both staleness columns are measured per claim, not per document** (queue item
**V19**, ruled 2026-08-16). The criterion names the newest source *that speaks to the
item*, not the newest source in the set, because the newest document is usually silent
on any given claim — read the other way the column would clear an item whenever the
latest source happened not to mention it. Phrasing it this way is also what keeps the
column from charging this chain for an old value the article carries because an
unsuperseded co-source still asserts it. That correction is narrower than it looks
here: P7's co-source is dated `2026-04-14` against a chain head of `2026-05-14`, and
P10's is `2026-03-05` against `2026-03-06`, so both stay stale and
[V4](labels.md#independent-verification-pass-2026-08-15) is not answered by this
wording. P5 is the only case whose co-source is newer than its own chain head.

**V4 is ruled 2026-08-16 and did not need the wording**: a co-source that supplied the
old value does not excuse the article, because supersession is a property of the compile
set rather than of the labelled pair — the newest source speaking to the item still
contradicts what the article states. So P7 keeps all 8 rows and 6 of 8 stale, and what
the confound bounds is the causal claim, which only P7-C8 supports. For FX7 it cancels,
the co-source being present in both arms.

**A case whose source order rests on a same-day tie-break is reported apart from the
gate**, because the compile set cannot order it. P5's two versions both carry
`date: 2026-03-13`, and `build_source_blocks` breaks that tie on the path
(`py/src/kb_ai/core/merge.py:173-174`) while the system prompt states without
qualification that blocks run oldest to newest (`merge.py:596-603`, caveated for
undated blocks only). Since `-` sorts before `.`, the payload presents `…-v3.md`
first — so it tells the writer that **v1 is the newest source**, inverting the chain.
Scored against the order actually stated, P5 reads 5 of 5 stale rather than 0 of 5,
since the article carries v3's figures (L32, L141–144).

**V20 is ruled 2026-08-16, and it keeps P5 out rather than letting it in.** Same-day
blocks get WP6's undated caveat — their relative position carries no ordering claim —
because no stated tie-breaker reaches the population: of 384 same-day pairs on the
reference KB a filename version marker survives inspection on 1, and a body-stated date
on 1. The payload therefore stops telling the writer that v1 is newest and puts nothing
in its place, so P5's 0 of 5 would be luck rather than evidence and its Staleness stays
reported separately for good. **The cases judged on the gating column are five** — P3,
P4, P7, P9, P10 — and P5's five contradictions still count in the set totals, which is
why the stale rate has two readings: 27 of 44 (61%) over all cases carrying
contradictions, 27 of 39 (69%) over the five that gate. Ruling V20 also found what sits
under the tie: v3's body reads 「生成时间：2026-03-19」 (L12) against v1's 「2026-03-13」
(L13), so the shared frontmatter date is an **error in v3's metadata**, not a fact about
the corpus, and how P5 is finally reported is queue item **V21**.

Staleness (drop) is carried as its own column rather than left unmeasured because
it is the only number that says whether A2's RP1 arm is worth building: if A1's
explicit ordering signal happens to clear the drops as well, that arm gets
cheaper, and nobody learns that from a run that does not look.

Staleness and Trail are separate columns on purpose: that pair is what separates
the D1 options, and no single score can.

- latest-wins: Staleness 0, Trail 0
- current-plus-trail: Staleness 0, Trail 1
- article family: two articles, and Trail is not applicable

For D2 the discriminating column is Correction landed on every case with a
non-empty `replacement` list, with False positive held at 0 on N1–N4. P1 is not
one of them: a dropped claim has nothing to replace it with, so its Correction
landed is vacuous and it scores only under Staleness (drop). Path A leaves the
ordering judgement to the model; path B hands it an explicit claim; path C removes
the question by recomposing.
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
- Whether a dropped claim *ought* to be treated as superseded. The labelling rule
  is now fixed (drops are scored in their own non-gating column), but that is a
  scoping decision about what A1 is judged on, taken because Q1 had already scoped
  A1 to explicit contradiction. It is not a finding about the data, and the data
  cannot produce one.
- The 14 documents with no cached extraction. They are in `data/kb-knowledge/`
  with no `extraction/` file and are outside every case.

## Regenerating

The case selection and the staging are mechanical and cost nothing:

```
cd py
uv run python scripts/select_cases.py --kb ../data/kb-knowledge --out cases.json
uv run python scripts/stage_fixture.py --kb ../data/kb-supersession-fixture \
    --cases cases.json --out ../data/kb-supersession-staged        # plan only
uv run python scripts/stage_fixture.py ... --stage 1               # writes stage 1
kb-ai check --kb ../data/kb-supersession-staged                    # expect 0 missing
```

`select_cases.py` on this corpus prints `131 chains (94 shape A, 37 shape B)` and
the strata table above; on `data/kb-supersession-fixture` it prints `18 chains`,
which is the 10 positives, 4 negative controls and 4 duplicate controls. Staging
that fixture plans four stages of 18, 18, 1 and 1 documents — the last two are P4's
four-version chain, which is the case the single-run fixture never reached.

**The conversion is not regenerable and does not need to be.** The two scripts that
built `data/kb-knowledge` from `~/.knowledge` — a copy plus a re-serialization of
the legacy extract cache, and a one-shot conformance pass — ran once against a
gitignored KB with absolute paths baked in, and both have since been deleted. They
are recorded here rather than kept as code: repeating them would mean re-doing a
migration whose output is on disk and verified by `kb-ai check`. What the fixture
needs going forward is selection and staging, and those are the two scripts that
landed with tests.
