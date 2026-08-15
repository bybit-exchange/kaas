# FX3 labels — the supersession test set's reference standard

Status: **drafted, awaiting confirmation.** Every item below is `to confirm`. The
two blocking rulings are **settled** (2026-08-15): P2 leaves the positives and is
kept as the documented wrong-date counter-case, and P7's measurement-time reading
is accepted. Neither is still a question; see [P2](#p2--infra-biweekly-review-withdrawn-counter-case)
and [P7](#p7--2026-h1-cost-progress-tracking).

These labels are what [test-set.md](test-set.md)'s scoring columns are measured
against. A wrong entry does not fail loudly; it silently mis-scores A1 and feeds
the decision about whether A2 gets bought. They are drafted from the documents
and human-confirmed before they score anything ([spec.md](spec.md) FX3), and the
labels themselves stay human-owned.

Cases P1 and P6 are not here: both were adjudicated in test-set.md when the set
was built. The eight below are the ones its Label column had marked `to draft`,
and that column now links to the drafts here.

## How to confirm

Set each item's Status to one of:

| Status | Meaning |
|---|---|
| `to confirm` | not yet reviewed (the state everything ships in) |
| `confirmed` | the item is right as written and scores as-is |
| `amended` | kept, with the correction written into the row |
| `rejected` | struck, with the reason written into the row |

**Done means**: no item still reads `to confirm`; the two blocking rulings (P2's
direction, P7's same-period reading) are recorded here as decisions rather than as
questions — **done, 2026-08-15**; and test-set.md's Status block stops calling the
labels awaiting-confirmation. Until then FX5's scoring cannot run, because there is
nothing settled to score against.

Confirming does not require reopening the fixture. Every row carries the file and
line of both sides, plus the decisive quote, because aligning them is the
drafter's job rather than the reviewer's.

## The rule these labels apply

Four lists, defined in [test-set.md](test-set.md#the-cases). The split that
matters: `superseded-contradiction` (the later version asserts something
incompatible about the same subject) gates A1 under FX7, while
`superseded-drop` (the later version is simply silent) is measured and does not
gate. `replacement` pairs one-to-one with `superseded-contradiction`.
`control` is what both versions assert, and it catches over-deletion.

Item IDs are stable and citable: `<case>-C<n>` contradiction, `<case>-R<n>` its
paired replacement, `<case>-D<n>` drop, `<case>-K<n>` control (kept).

Quotes are verbatim Chinese, as the source documents are. `v1`/`v2` line numbers
are into the fixture files named at the head of each case.

## Progress

| Case | Contradictions | Drops | Controls | Stale in article today | Status |
|---|---|---|---|---|---|
| P3 | 8 | 5 | 6 | 6 of 8 | to confirm |
| P4 | 10 | 4 | 6 | **9 of 10** | to confirm — worst case in the set |
| P5 | 5 | 5 | 6 | **0 of 5** | to confirm — passes today, see [P5](#p5--bybit-trading-skill-api-inventory) |
| P7 | 8 | 0 | 6 | 6 of 8 | to confirm — reading accepted, see [P7](#p7--2026-h1-cost-progress-tracking) |
| P8 | 4 | 6 | 6 | 2 of 4 | to confirm |
| P9 | 7 | 5 | 6 | 4 of 7 | to confirm |
| P10 | 8 | 5 | 6 | 4 of 8 | to confirm |
| ~~P2~~ | ~~8~~ | ~~6~~ | ~~6~~ | ~~7 of 8~~ | **withdrawn from the positives** — counter-case, scores nothing, see [P2](#p2--infra-biweekly-review-withdrawn-counter-case) |

Totals across the seven scoring cases: **50 contradictions, 30 drops, 42
controls**, and 31 of the 50 contradictions are stated as current in the articles
today — a 62% pre-A1 staleness rate on the gating column, measured over compiled
output rather than argued from P1 alone. Plus one non-scored
`chained-supersession` entry (P4) as evidence for NG3's trail format, and P2's
withdrawn label (8/6/6) retained below as counter-case evidence.

- **P5 already passes** (0 of 5 stale), and it leaks its ordering three ways
  inside the body, so it belongs with P6 as an accidental-signal case rather than
  as evidence about A1.
- P4 is the sharpest probe at 9 of 10 stale. P8 is the weakest at 4
  contradictions, all resting on one reading of a column rename.
- Drops are not a rounding error: 30 of them, and on P8 all six are stated as
  current. That is the baseline A2's RP1 arm would be measured against.
- The gating set is therefore **seven drafted cases plus P6**, which succeeds
  today. P1 and P2 are both evidence rather than tests: P1 because it is a drop,
  P2 because its date lies.

---

## P3 — cht-knowledge distillation and indexing

- `v1` = `data/kb-supersession-fixture/raw/docs/2026-04-20-cht-knowledge-跨系统知识蒸馏与索引方案.md`
- `v2` = `data/kb-supersession-fixture/raw/docs/2026-04-30-cht-knowledge-跨系统知识蒸馏与索引方案.md`
- `article` = `data/kb-knowledge/wiki/concept/cht-knowledge-plugin-system.md`

The revision is an architecture change, not a polish pass: project-level cache
becomes user-level, a resident index becomes trigger-based injection, the
distillation command changes owner and shape. Six of the eight contradictions are
still stated as current in the article today, which makes P3 the strongest pre-A1
failure in the set after P1. Unlike P1, its items are contradictions, so they
gate.

### Contradictions and their replacements

| ID | What v1 asserts | Evidence | Article today | Status |
|---|---|---|---|---|
| P3-C1 / R1 | Knowledge caches live in the project, in a gitignored `.claude/knowledge/` → they live at a user-level path shared across projects | v1 L265 「.claude/knowledge/ ← 整个目录 gitignored」 → v2 L152 「**本地克隆路径**：`~/.claude/plugins/cht-knowledge/knowledge/<domain>/`」, L64 | not stale — article states the v2 path (L66) | to confirm |
| P3-C2 / R2 | Three-level loading with `index.json` permanently resident, ~50 tokens per system and ~1500 for 30 → two-stage loading with nothing resident, ~200 tokens for the summary | v1 L746 「Level 0（常驻）：index.json ~50 tokens/系统」, total at L325 → v2 L951 「两阶段加载在大多数情况下仅消耗 ~200 tokens（Stage 1 摘要）」, L212 | **stale** — L30 heading, L36 table row, L40 「1,500 tokens」 | to confirm |
| P3-C3 / R3 | The SessionStart hook generates `index.json` and injects it every session → injection moves to a `UserPromptSubmit` hook on trigger words, and SessionStart only pulls silently | v1 L294 「index.json 从 registry.mjs 自动生成，在每次会话启动时通过 hook 注入 AI 提示词。」 → v2 L214 「**时机**：UserPromptSubmit Hook 检测到触发词时自动注入」, L115 | **stale** — L63 asserts the resident global index; L67 also describes v2's pull, so the article carries both mechanisms side by side | to confirm |
| P3-C4 / R4 | Cached knowledge has a 24-hour validity window and is not re-fetched inside it → freshness comes from a `git pull --rebase` on every session start, failing silently offline | v1 L289 「缓存有效期：24 小时内不重复拉取」 → v2 L251 「对每个知识库执行后台 `git pull --rebase`」, L253 | **stale** — L68 states the 24-hour window as current | to confirm |
| P3-C5 / R5 | There is no `init` command; installing the plugin completes setup → each knowledge base is installed explicitly with `/cht-knowledge:init <system-id>`, which git-clones it | v1 L399 「**注意：没有 init 命令。** 安装插件即完成所有设置」 → v2 L112, L481/484 | **stale** — L71 「**No init command:**」 | to confirm |
| P3-C6 / R6 | Distillation is a `cht-tools` command, `/cht-tools:distill` → it is `/cht-knowledge:distill --source <path>`, run inside the knowledge-base repo | v1 L448 「## 四、蒸馏工具设计（/cht-tools:distill）」 → v2 L513, L516 | **stale** — L75, and L21/L181/L232/L262; `/cht-knowledge:distill` appears nowhere | to confirm |
| P3-C7 / R7 | Distillation scans 6 dimensions with 6 parallel sub-agents → an 8-agent pipeline, 5 parallel then 3 serial | v1 L464 「蒸馏工具自动扫描 6 个维度，使用并行子 Agent 提高效率：」, agents at L468–473 → v2 L109, L393, L400 | not stale — article states 5 parallel + 3 serial (L75) | to confirm |
| P3-C8 / R8 | A knowledge base is `manifest.json` plus five named files (`system-overview.md`, `proto-guide.md`, `integration-guide.md`, `data-model.md`, `error-reference.md`) → `manifest.json` plus eight numbered files `00-overview.md` … `07-usage-guide.md` | v1 L609–615 → v2 L159–167 | **stale** — article's tree is v1's names plus two extras (L108–117) | to confirm |

### Drops (measured, not gating)

| ID | What v1 asserts and v2 drops | Evidence | Status |
|---|---|---|---|
| P3-D1 | The platform has 100+ repositories | v1 L14 「在中台大团队（100+ 仓库、多个子团队）中」; `100+` and 「子团队」 both 0 hits in v2. **Narrowed on verification** — the original row also claimed "and multiple sub-teams", which v2 restates at L20 「中台有 30+ 微服务，跨团队协作时…」, so that half was not a drop | to confirm — see note 1, this may belong in C |
| P3-D2 | Distillation extracts a minimum knowledge set rather than copying code: 50 Proto methods reduce to 5–10 selected external core interfaces | v1 L561 「**蒸馏不是照搬代码，而是提取 AI 对接时需要的最小知识。**」, L575/578 | to confirm |
| P3-D3 | The transfer system's `Transfer` interface is idempotent on `request_id` with a 3000 ms timeout, `RATE_LIMITED`/`TIMEOUT` retryable and `INSUFFICIENT_BALANCE`/`ACCOUNT_FROZEN` fatal | v1 L635–638 | to confirm |
| P3-D4 | The plugin offers `/cht-knowledge:search`, a keyword search over already-cached knowledge | v1 L355/361; v2's command reference (L461–543) has no analogue — `:match` debugs trigger words, it does not search content | to confirm |
| P3-D5 | The first systems to distill are transfer, deposit, withdraw, risk and account | v1 L1113/1116 (L1114 as first drafted is `</lark-td>`) | to confirm |

### Controls (present in both; missing from the article means over-deletion)

| ID | Asserted by both versions | Evidence | Status |
|---|---|---|---|
| P3-K1 | Each system's knowledge lives in its own independent Git repository | v1 L1140 → v2 L151 | to confirm |
| P3-K2 | `cht-context` is a Git submodule bound to a project, unlike `cht-knowledge` which is git-cloned | v1 L160 → v2 L72 | to confirm |
| P3-K3 | Distillation is AI-driven: an agent scans source and generates structured documents | v1 L964 → v2 L97/L109 (L28 as first drafted asserts source→structured docs but not AI authorship) | to confirm |
| P3-K4 | A knowledge base becomes platform-wide by registering in `registry.mjs` and merging an MR | v1 L994/997 → v2 L756 | to confirm |
| P3-K5 | Distilled output must be human-reviewed before publication | v1 L972 → v2 L785 | to confirm |
| P3-K6 | On-demand deep loading of full documents costs ~2000–4000 tokens | v1 L796 → v2 L237 | to confirm |

### P3 open judgement calls

Each needs a yes/no from Captain; the default if ignored is the drafted position.

1. **P3-D1, drop or contradiction?** v2 replaces the framing with 「中台有 30+ 微服务」 (v2 L20). Drafted as a drop, because repo count and microservice count are different measures that can both hold. The article merges them into one sentence (L16). Ruling it a replacement promotes it to C9.
2. **`manifest.json` schema — left out, strongest candidate for promotion.** v1's manifest carries per-interface contracts (`interfaces[]` with `idempotent_key`, `timeout_ms`, `retryable_errors`, `fatal_errors`, v1 L630–646); v2's carries `version`/`createdAt`/`updatedAt`/`triggers`/`documents` and no interface data (v2 L172–192). Same subject, incompatible content. Held out only to stay inside the eight-item ceiling. The article asserts v1's shape as current (L119–123) plus v2's semver (L125), so promoting it adds a 7th stale item.
3. **Knowledge-repo naming — left out as low consequence.** v1 `cht/ai-coding/knowledge-{system}` (L890, L986) against v2 `<系统ID>-knowledge` under `cht/ai-coding/knowledge/` (L583, L586). A real contradiction; the article uses v1's form throughout (L105, L190, L262).
4. **Do exhaustive command tables contradict removed commands?** v2's 命令参考 (L461–543) reads as a complete set and omits `search`, `clean` and `update` (v1 L379/384, L388/394). Drafted as absences, and only `search` is listed, as the one with no v2 analogue. Ruling that an exhaustive table contradicts moves all three up to C.
5. **Roadmap table — left out.** v1's 实施路径 (L1088–1107) is fully replaced by v2's Roadmap (L806–826). Held out because v1's phases are plan items, not assertions about current state, and the article already uses v2's table (L252–257), so it would score as non-stale either way.
6. **The 80K-token figure — left out, but the article is internally inconsistent here.** v1 asserts full preload costs 80K+ tokens (L843); v2 asserts full injection is ~22,000 tokens *per system* (L951). Over 30+ systems those are arithmetically incompatible, but the incompatibility is inferred rather than asserted, so it was not labelled. The article states both (L40 「80K+ tokens」, L212 table 「660K+」). Note the trap: the article also reuses 80,000 as v2's distillation *input* size (L96), a separate and correct claim that shares the number.
7. **C2 and C3 are two facets of one architectural shift** (resident index → trigger-based injection), so one article fix would likely satisfy both and that single defect carries double weight. Kept separate because each is independently checkable in prose. Merging them is defensible if the score should weight defects rather than sentences.

Extraction cross-check: every v1 claim the pipeline itself considered salient is
accounted for, and so is every v2 counterpart. One artifact to keep out of the
label: the v2 extraction records 「Each session costs approximately 1-2 USD」 and
「10-15 minutes」 per *session*, where v2 states them per distillation run
(v2 L887–897).

---

## P2 — Infra biweekly review (WITHDRAWN, counter-case)

- `v1` = `.../raw/docs/2026-04-14-infra-双周会-2026_h1.md` (fixture calls this earlier)
- `v2` = `.../raw/docs/2026-04-17-infra-双周会-2026_h1.md` (fixture calls this later)
- `article` = `data/kb-knowledge/wiki/decision/infra-ai-devops-roadmap-decisions.md`

**Ruled 2026-08-15: P2 is withdrawn from the positives and kept as the documented
wrong-date counter-case** — option (c) of the direction call below. It scores
nothing under FX5 and gates nothing under FX7. Its drafted label is retained
verbatim, in the fixture's stated direction, because P2 is the corpus's only
instance of an inverted chain and deleting the label deletes the evidence. What it
is evidence *for* is a limitation of A1's design, not a defect in A1's
implementation: WP2 takes ordering from raw frontmatter `date`, and on this
document that date is wrong rather than missing.

The chain runs backwards relative to its content, verified three independent ways:

| Evidence | v1 (dated 04-14) | v2 (dated 04-17) |
|---|---|---|
| Dated section headings in body | `# 2026-05-04` (L81) **and** `# 2026-04-17` (L1025) | `# 2026-04-17` (L81) only |
| Extraction `extracted_at` | `2026-05-04T04:32:44+00:00` | `2026-04-17T13:24:00+00:00` |
| Shared 04-17 section's own figures | storage governance 56%, vLLM 100% | storage governance 20%, vLLM 90% |

So the file the fixture calls *earlier* is a rolling document that accumulates
meeting sections and carries reporting three weeks *newer* than the file it is
supposed to precede. Its frontmatter `date` is its creation day, not its content
day. Every `replacement` drafted below is therefore the **older** figure.

P2 is worth more as evidence of this failure mode than as a scoring case. WP2
reads the ordering signal from raw frontmatter `date`, so on this document A1
would hand the writer `- Date: 2026-04-14` for content dated 2026-05-04 and
assert an order that is confidently wrong. Q2 and D3 provisioned for a *missing*
date, not a *wrong* one.
Scope of the risk, measured over the corpus rather than assumed:

| Measurement | Result |
|---|---|
| Fixture chains whose body-content order inverts their frontmatter order | **1 of 12** (P2 only) |
| Fixture docs whose newest body heading date postdates their frontmatter date | 6 of 38 |
| Corpus docs with the same symptom | 101 of 996 (10.1%); 36 stale by more than a week |
| Corpus docs sharing the placeholder `date: 2026-01-01` | 21 |
| N3 / N4 | absolute dates stale by ~30 days, **relative order preserved** — still valid controls |

The symptom is common; the fatal form (inverted order) is rare. Meeting
transcripts are the main source — `2026-03-10-realclaw安全评估.md` is dated
2026-03-10 while its body heading reads 「Meeting transcript: realclaw安全评估
2026-04-10」.

### Contradictions and their replacements — drafted in the fixture's stated direction, i.e. reversed relative to content

| ID | What v1 (04-14 file) asserts | Evidence | Article today | Status |
|---|---|---|---|---|
| P2-C1 / R1 | Q2 cloud-cost optimization at 40.95%, 24.57W banked → 0.28%, 0.17W | v1 L898 → v2 L953 | **stale** — L615, L761 state 40.95% / 24.57W as current | to confirm |
| P2-C2 / R2 | Low-load governance over-delivered at 117.3%, 17.6W against a 10W–15W target → 0% | v1 L919 → v2 L969 | **stale** — L618, L762 | to confirm |
| P2-C3 / R3 | AI-gateway scenario convergence 90% (36/40) plus 34 extra → 87.5% (35/40) plus 32 extra | v1 L435 → v2 L448 | **stale** — L578, L759 | to confirm |
| P2-C4 / R4 | Self-developed AI gateway kicked off 4.20 at 100%, design review due 5.8 → still an evaluation due 4.20 | v1 L438–439 → v2 L451 | **stale** — L578 | to confirm |
| P2-C5 / R5 | Bgwst gray release at 50% trading QPS, 40K/s daily, 230K peak, full 5.12 → 45%, 35K/s, 61K peak, full end of April | v1 L557 → v2 L578 | **stale** — L592 | to confirm |
| P2-C6 / R6 | Bgws C++ committed to testnet 5.27 and mainnet 6.16 → no schedule, estimate due 4.24 | v1 L562–564 → v2 L585 | **stale** — L593 | to confirm |
| P2-C7 / R7 | vLLM instance monitoring 100% complete → 90% | v1 L399 → v2 L405 | **stale** — L580, L760 | to confirm |
| P2-C8 / R8 | Storage non-standard governance overall 56% → 20% | v1 L1781, L783 → v2 L824 | not stale, and the replacement is absent too — no storage-governance figure in the article | to confirm |

### Drops (measured, not gating)

| ID | Asserted by the 04-14 file, absent from the 04-17 file | Evidence | Status |
|---|---|---|---|
| P2-D1 | ABF security-compliance conversion 100% complete by 4.30 across testnet/prod — 6 accounts, 585 hosts, 922 disks | v1 L315 | to confirm |
| P2-D2 | The Fiat model-call anomaly was fixed, cutting spend from a 1750/day peak to under 50/day, catching about 4w per month | v1 L940 | to confirm |
| P2-D3 | Private-model stability progress was slow because staff were absorbed by ABF disk encryption, finishing 4.30 | v1 L395 | to confirm |
| P2-D4 | Agreed plan for third-party gateway metadata: align with the efficiency platform by Q2, add vendor and purpose fields to the Blueking egress ticket, Blueking loads it into the efficiency database | v1 L225–227 | to confirm |
| P2-D5 | Three pending improvements for the AI deployment platform: one-click deploy for Claude Code and OpenClaw, externally reachable generated domains pending security review, database creation | v1 L1397–1400 | to confirm |
| P2-D6 | EBS storage-encryption data migration is complete | v1 L1271 | to confirm |

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P2-K1 | Third-party gateway totals: 338 channels (+21), 197 not onboarded (−17), 141 onboarded (+38) | v1 L720 → v2 L750 | to confirm |
| P2-K2 | Third-party gateway scope: 6 departments, 206 applications, 57 scheduled for April, rest evaluated in batches before 4.20 | v1 L709 → v2 L739 | to confirm |
| P2-K3 | Unified-framework backlog: 198 Java and 179 Go applications remaining | v1 L1789, L1791 → v2 L832, L834 | to confirm |
| P2-K4 | AI adoption: 67.35% AI developers (33/49), 40.13% AI-generated code | v1 L991–992 → v2 L1037–1038 | to confirm |
| P2-K5 | Cost baseline: Q1 stock baseline 3330W excluding 90W of compliance sites, Q1 3330W → Q2 3090W/3030W | v1 L890 → v2 L945 | to confirm |
| P2-K6 | Image zero-trust is live, all base images converging onto the efficiency platform by 4.30 | v1 L626 → v2 L647 | to confirm |

### P2 open judgement calls

1. **Direction — RULED (c), 2026-08-15.** The three options were (a) accept the
   fixture's direction, in which case A1 is being asked to prefer an older figure
   and P2 measures the wrong thing; (b) invert the label, swapping contradiction
   and replacement and turning the six drops into v2-only additions; or (c)
   withdraw P2 from the positives and keep it as a **documented counter-case** for
   the wrong-date failure mode, which is what its evidentiary value actually is.
   (c) was taken. Under it the rows above keep the fixture's direction — so read
   every `replacement` as the older figure and do not score any of it — and (b)'s
   inversion is the reading to apply if the case is ever revived: swap each C with
   its R, and reclassify D1–D6 as v2-only additions rather than drops. The reason
   (a) was rejected is that it would have A1 graded as correct for asserting an
   order that is wrong, which corrupts FX7 in the direction that flatters the
   work.
2. **Only C7 and C8 are unambiguous.** They sit inside the section both files date
   2026-04-17, so v1 asserts exactly one value. For C1–C6 the 04-14 file carries
   *both* values in different sections (87.5% at L1405 beside 90% at L435), so an
   article stating v2's figure proves nothing about ordering — it may have copied
   the older subsection. If only unambiguous items should gate, keep C7 and C8 and
   demote C1–C6.
3. **The article asserts the inversion in prose**, which is worth reading before
   ruling: L574 「It provides updated metrics and decisions that supersede or
   complement the April 17 data」 and L615 「a significant improvement from the
   0.17W (0.28%) reported at the April 17 meeting」. The pipeline already inferred
   the true direction from content.
4. **Left out — the EC2 Savings Plan reversal**, the largest decision difference
   in the pair. The 04-14 file strikes 「目标覆盖率90%…」 (L907) and substitutes
   「预期不新增购买sp,需优化1w核」 with a 3000C gap, while the 04-17 file states the
   90% target unstruck (L962). It hinges on reading `~~…~~` as cancellation, and
   the pipeline's own extraction did not read it that way. Add it if the
   strikethrough reading is accepted.
5. **Also left out**: ABF percentages where the 04-14 file asserts both values in
   one file (unscoreable); two monitoring rows too deep in a table to reach article
   prose; a decision softening neither version's article states; and eight smaller
   numeric pairs, capped rather than padded.

---

## P4 — trade-rollback TRD, four versions

- `v1`…`v4` = `.../raw/docs/{2026-05-19,2026-05-26,2026-06-02,2026-06-04}-交易回滚trd.md`
- `article` = `data/kb-knowledge/wiki/concept/derivatives-position-field-schema.md`

**The strongest failure case in the set: 9 of 10 contradictions are still stated
as current.** The chain is a design document converging over three weeks, and
what changed is mostly storage architecture.

| Transition | What actually changed |
|---|---|
| v1→v2 | Storage flips from MySQL monthly sharding to single TiDB tables (nine tables lose `_{yyyyMM}`, gain DDL); three new fields are struck from the monthly translog and re-scoped to the real-time table; the engine `RollbackUserRequest` is rewritten (ban/unban RPCs deleted, `user_snap` / `cash_balance_info_list` / `repayment_info_list` added); §5 becomes an 11-row module table |
| v2→v3 | `set_time` redefined from nanoseconds to milliseconds across seven log tables; `action` renamed `service_action`; counterparty renamed 交易系统户 → 交易系统内的差额账户 with disposal reassigned to TRW; fund-recovery callback API added; the 兑币流水回滚 task and two open questions deleted |
| v3→v4 | Three progress cells only: 封禁 gains 联调结束, 资产追回 60% → 开发90%，下周可以联调, MarginDB 开发中 → 联调中 |

### Contradictions and their replacements (judged v1→v4)

| ID | Earlier assertion → v4's | Evidence | Article today | Status |
|---|---|---|---|---|
| P4-C1 / R1 | Monthly translog gains `change_flow_usd`, `uta_result_topic_name`, `uta_result_offset` → monthly tables get no new fields this round, they go to the real-time table | v1 L1144, L1363, L1368 → v2 L1519 / v4 L1742 | **stale** — L454–456 list all three as current additions, plus open action L636; the correction exists but is misfiled under `uta_liq_trans_log` (L473–478), so the article asserts both | to confirm |
| P4-C2 / R2 | Coin-exchange table is monthly `uta_exchange_record_202604` → a single TiDB table, dual-written with MySQL for a transition | v1 L1433 → v4 L1751 | **stale** — L487 | to confirm |
| P4-C3 / R3 | §4.1.3 fund-flow table is `uta_liq_trans_log_202605`, monthly, past data deletable → `translog_realtime` in TiDB | v1 L1761 → v4 L2111 | **stale** — L469–471 | to confirm |
| P4-C4 / R4 | User-behaviour log tables are monthly-sharded `_{yyyyMM}` → unsharded TiDB tables | v1 L2539, L2667, L3653 → v4 L3272, L3416, L4488 | **stale** — L494, L498, L499 | to confirm |
| P4-C5 / R5 | Existing `uta_leverage_log` will be refactored into monthly shards → migrated from MySQL to TiDB | v1 L3213 → v4 L3869, L3871 | **stale** — L504–506, action L638, plus `uta_spot_leverage_log_{yyyyMM}` L508 | to confirm |
| P4-C6 / R6 | `set_time` in the user-behaviour log tables is nanoseconds → milliseconds | v1 L2626 (and L2782, L2921, L3179, L3353, L3612, L3754) → v4 L3359, L3405 | **stale** — L494 | to confirm |
| P4-C7 / R7 | `uta_auto_add_margin_log` trigger column is `action` → `service_action` | v2 L3954 → v4 L4192 | **stale** — L514, action L639 | to confirm |
| P4-C8 / R8 | Incident counterparty is the trading system account (系统户), funds settle against it → the in-trading difference account (差额账户), overdraft allowed | v2 L5447, L5453 → v4 L5698, L5704 | **stale** — L421–424 | to confirm |
| P4-C9 / R9 | Post-rollback disposal is futures dumped to the order book with options and spot moved to a PM takeover account, pending TR discussion → spot and positions handed to TRW | v2 L5455 → v4 L5706 | **stale** — L425–426, plus open item L667; TRW appears nowhere | to confirm |
| P4-C10 / R10 | Asset recovery is 60% done → 90% developed, integration testing next week | v3 L5674 → v4 L5675 | not stale — L735 carries v4's value | to confirm |

### Drops (measured, not gating)

| ID | Asserted earlier, absent from v4 | Evidence | Status |
|---|---|---|---|
| P4-D1 | The engine exposes `TradeEngineService` with batch ban/unban RPCs (`BatchBanTrading` / `BatchUnbanTrading`, carrying `user_ids`, `operator`, `reason`, `expire_at`) | v1 L705–737; v4 §3.3 (L705–743) defines no service, and `TradeEngineService` does not occur in v4 | to confirm |
| P4-D2 | `uta_leverage_log` already holds ~166.6M rows (`AUTO_INCREMENT = 166624305`) | v1 L3236; the number does not occur in v4 | to confirm |
| P4-D3 | The engine reconciles/tops up to a system account, which can be created in advance | v1 L4776; neither 对账补齐 nor 提前创建 occurs in v4 | to confirm |
| P4-D4 | Coin-exchange flows roll back through the normal coin-exchange path | v2 L5442; v4's 回滚 row ends at item 2 (L5684–5691) | to confirm |

### Controls

| ID | Asserted by v1 and v4 | Evidence | Status |
|---|---|---|---|
| P4-K1 | The transaction log table is sharded by month and UID trailing digit | v1 L760 → v4 L1074 | to confirm |
| P4-K2 | Users who changed account mode, toggled collateral, changed single/dual position mode, or are institutional borrowers are not auto-rolled-back | v1 L172 → v4 L174 | to confirm |
| P4-K3 | `per_user_max_subsidy_usd_amount` defaults to 10000 and `user_rollback_watermark` to 90 | v1 L4001, L4018 → v4 L4854, L4871 | to confirm |
| P4-K4 | `translog_realtime` is a single TiDB table, daily partitions, 7-day rolling window | v1 L1763 → v4 L2115 | to confirm |
| P4-K5 | `mark_price` applies only to USDC perpetuals | v1 L1279 → v4 L1593 | to confirm |
| P4-K6 | Volume estimate ~91 million rows / 55GB over 7 days | v1 L2529 → v4 L2896 | to confirm |

### Chained supersession (evidence for NG3's trail format, not scored)

| ID | Sequence | Status |
|---|---|---|
| P4-X1 | The system-side account absorbing incident funds: v1 「对账补齐到系统账号（账号可以提前创建好）」 (L4776) → v2 「交易系统户 … 和系统户结算，允许透支」 (L5447, L5453) → v4 「交易系统内的差额账户 … 和差额账户结算」 (L5698, L5704) | to confirm — weak, see call 4 |

**Restored (contradicted mid-chain, then reverted by v4): none.** v3→v4 touches
three progress cells and reverts nothing.

### P4 open judgement calls

1. **C6 is deliberately scoped to `set_time` in the user-behaviour log tables
   only.** v4 still has `exec_time_e9` in nanoseconds (L1976) and unstruck prose
   bullets about the three new fields (L1746–1747). Do not widen C6 to "all
   timestamps are milliseconds" — that would be wrong.
2. **C7 has residual contrary prose.** v4 L4182 still says 「增加action字段…」 while
   the DDL at L4192 says `service_action`. Scored on the DDL, which is what v4's
   own extraction did. Drop it if zero ambiguity is required.
3. **C9 is the least certain.** v4's 待决策 section still lists TWAP order-book
   selling and the PM-account transfer as options, while the module table says
   TRW. Scored on the module table because the other block is explicitly marked
   "pending decision".
4. **X1 is weak.** The v1→v2 step is a reframing rather than a contradiction of
   the identical predicate, so a strict reading makes this chain a single
   supersession (v2→v3) and X1 should read "none". Decide before using it as
   trail-format evidence. Its two ends are already scored separately as P4-D3 and
   P4-C8, so lists 1–4 are not double-counting.
5. **Left out — the engine `RollbackUserRequest` retyping**, the largest IDL
   change in the chain (v1 L739–748 → v4 L728–742). An identically-named
   `RollbackUserRequest` with the *old* field set still sits in §3.2 risk_eval
   (v4 L645–654), so the question is answerable both ways from v4 alone. Add it
   only phrased strictly as "the *engine* rollback request".
6. **Left out**: the §1.2 heading widening (§1.6 was not renamed, so v4 is
   internally inconsistent about ban scope); the `liq_type` value set (the DDL
   comment still lists only the original five); `uta_delayed_fee_record` fee-comment
   refinements; two v2 open questions dropped in v3, both arguably answered
   elsewhere in v4 rather than dropped.
7. **Only C10 comes from v3→v4.** Add the MarginDB cell (v3 L5774 → v4 L5775) if
   the v3-vs-v4 discrimination should rest on more than one item. The 封禁 cell was
   empty in v3, so that is an addition, not a supersession.

Also carried as current in the article but not gating: **all four** drops —
P4-D1 `TradeEngineService` as the ban/unban service (L333, L357, L396, L563),
P4-D2 `AUTO_INCREMENT ~166,624,305` (L506), P4-D3 pre-created reconciliation
accounts (L396), and P4-D4 the coin-conversion rollback path (L666). Each was
re-checked in the article rather than taken from the draft, which is how the
count was corrected from three. All six controls are present.

---

## P5 — Bybit trading skill API inventory

- `v1` = `.../raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单.md`
- `v3` = `.../raw/docs/2026-03-13-bybit-trading-skill-完整-api-清单-v3.md`
- `article` = `data/kb-knowledge/wiki/project/bybit-ai-trading-skill.md`

**This case already passes: 0 of 5 contradictions are stale.** That is a result,
not a gap in the label. Like P6, it comes with a confound. The pair leaks its
ordering three ways inside the body: the H1 carries 「(v3)」 (v3 L10), the
`生成时间` lines differ (v1 L13 「2026-03-13」 vs v3 L12 「2026-03-19」), and the
module count differs. A pipeline can order this pair with no dated metadata at
all, so P5 cannot testify that A1's explicit signal did the work. It belongs with
P6 as an accidental-signal case.

Note also that the same-day filenames make this the one pair where `date`
frontmatter alone cannot order the versions — the tie is broken by path, per WP5.

### Contradictions and their replacements

| ID | v1 → v3 | Evidence | Article today | Status |
|---|---|---|---|---|
| P5-C1 / R1 | The inventory covers 8 skill modules → 11, the new three being Copy Trading, Strategy Orders and Trading Bot | v1 L13 → v3 L12, sections L5649, L5753, L5856 | not stale — L32 states 11 modules | to confirm |
| P5-C2 / R2 | Total audited API count 280 → 301 | v1 L5438, L5441 → v3 L6341, L6344 | not stale — L141; `280` occurs nowhere | to confirm |
| P5-C3 / R3 | Retained endpoints 258 → 279 | v1 L5446, L5449 → v3 L6349, L6352 | not stale — L142; no `258` | to confirm |
| P5-C4 / R4 | Retained split ~165 GET / ~93 POST → ~169 GET / ~110 POST | v1 L5454–5465 → v3 L6357–6368 | not stale — L142 | to confirm |
| P5-C5 / R5 | Endpoints needing Mainnet confirmation ~25 → ~31 | v1 L5470, L5473 → v3 L6373, L6376 | not stale — L144, L404 | to confirm |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v3 | Evidence | Status |
|---|---|---|---|
| P5-D1 | The skill inventories a Leverage Token module (`/v5/spot-lever-token/*`, 5 endpoints under `spot.md`), Purchase and Redeem needing Mainnet confirmation | v1 L1241, endpoints L1273–1349; verified absent (`spot-lever-token`, `杠杆代币`: 0 hits in v3) | to confirm — see call 1 |
| P5-D2 | When cancelling all orders, take care not to cancel strategic standing orders | v1 L584; v3 L583 reduces the note to 「Mainnet 需确认」 | to confirm |
| P5-D3 | Batch order placement must display all orders before confirmation | v1 L604; v3 L603 reduced | to confirm |
| P5-D4 | The BybitPay Payout endpoint is essentially an alternative withdrawal channel | v1 L4744; v3 L4889 reduced | to confirm |
| P5-D5 | Institutional-loan UID bind/unbind is removed because it affects other users' accounts | v1 L4007; v3 L4044 reduced | to confirm |

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P5-K1 | 22 endpoints removed on security grounds, split 12 P0 and 10 P1 | v1 L5481, L5489, L5497 → v3 L6384, L6392, L6400 | to confirm |
| P5-K2 | Move Position and its history endpoint are removed because they move positions across UIDs | v1 L970 → v3 L969 | to confirm |
| P5-K3 | Withdraw is removed because it sends funds to external addresses | v1 L2723 → v3 L2612 | to confirm |
| P5-K4 | Modify Master API Key is removed because the AI could grant itself Withdraw permission | v1 L3055 → v3 L2998 | to confirm |
| P5-K5 | Upgrade to UTA is removed as irreversible | v1 L2039 → v3 L1930 | to confirm |
| P5-K6 | Leverage above 20x triggers an extra warning beyond Mainnet confirmation | v1 L802 → v3 L801 | to confirm |

### P5 open judgement calls

1. **P5-D1: drop or contradiction?** v3 never says leverage tokens are out of
   scope — the module is simply gone. Under the stated rule that is a drop. But
   「全部 11 个 modules」 plus the absence arguably asserts it is no longer in
   scope. **This is the entry most likely to need overruling, and it changes the
   headline**: the article does still carry the v1-only content (L413 「Earn Place
   Order, Leverage Token Purchase/Redeem」, L567 「22 endpoints including leverage
   tokens」), so reclassifying it makes P5 1 of 6 stale instead of 0 of 5.
2. **No status flags changed anywhere.** All 251 pairable endpoint rows match on
   name, method and 状态; the ⚠️ count rose only because of nine new
   copy-trading / strategy / bot write endpoints. So this revision offers no
   reversed-decision contradiction — it is additive scope plus a recount. Verified
   mechanically: 280 distinct `/v5/...` paths in v1, 301 in v3, 5 dropped (all
   `spot-lever-token`), 26 added, and 280 − 5 + 26 = 301.
3. **Left out — note abridgement below article altitude.** v3 shortens several
   备注 cells without contradicting them (fixed-term borrow, flexible borrow,
   Release Assets, Create Sub-account, Distribute Voucher, Delete Master API Key).
   Treated as restatement because the parent claim survives; the four promoted to
   drops are the ones where a whole distinct assertion disappears. Note the article
   still carries two of the abridged details verbatim (L399, L402).
4. **Left out**: the 🔴 glyph on removal rows (presentation), and endpoint index
   renumbering caused by the Leverage Token removal (positional artifact — a
   grader must not match on endpoint numbers).
5. **Unrelated stale content, not this chain's**: L189 「274+ API endpoints across
   7 functional modules」 and L198 「plus 7 functional modules」 come from a
   different source document. A naive whole-article number match would
   false-positive on them.

---

## P7 — 2026 H1 cost progress tracking

- `v1` = `.../raw/docs/2026-04-09-2026-h1成本进展跟进.md`
- `v2` = `.../raw/docs/2026-05-14-2026-h1成本进展跟进.md`
- `article` = `data/kb-knowledge/wiki/project/cloud-infrastructure-cost-optimization-2026h1.md`

**One framing decision governs this whole label. Ruled 2026-08-15: the
measurement-time reading is accepted, so the label below stands and P7 scores its
8 contradictions.** v2 contains v1 verbatim plus two new weekly columns, so no
*dated* claim is ever textually contradicted — v2 asserts both 「as of 4/30:
24.57w」 and 「as of 5/14: 57.11w」, which are compatible. The accepted reading
takes the measure to be "cumulative Q2 progress / current status of item X", with
the as-of date being a measurement time rather than a different period.

The stricter reading (as-of date is part of the period) was rejected: under it this
case has **zero** contradictions and measures nothing. What decided it is the
article's own behaviour rather than a preference between two defensible readings —
it flattens the table into undated current-state prose (「significant remaining
opportunity」, an open action to close a 3,000-core gap), which is exactly where
v1's figures become wrong. An article that had preserved the as-of qualifiers
would have made the strict reading the right one; this one did not.

`superseded-drop` is **empty by construction**: a body diff returns additions
only. See call 2 for the three candidates under a different absence test.

### Contradictions and their replacements

| ID | v1 → v2 | Evidence | Article today | Status |
|---|---|---|---|---|
| P7-C1 / R1 | Q2 progress 40.95%, 24.57w banked → 95.18%, 57.11w | v1 L69 → v2 L75 | present but dated 「as of 2026-04-30」 (L43–49); v2's 95.18% absent, and 57.11 appears mis-rendered as a *rate* at L39 | to confirm |
| P7-C2 / R2 | Low-utilization governance 17.6w at 117.3% of a 10w–15w target → 44.4w, with 117.3 struck and no new rate given | v1 L90 → v2 L102–103 | **stale, undated** — L480, L57; `44.4` absent | to confirm |
| P7-C3 / R3 | Commercial-model optimization 13.3%, 6.8w → 41.5%, 8.3w | v1 L75 → v2 L82 | present under a 「Completed (Apr 30)」 column (L58); v2's values absent | to confirm |
| P7-C4 / R4 | Listing low-utilization rightsizing 3300C at 83.1% → 3864C at 97.28% | v1 L92 → v2 L222 | **stale and undated** — L480; the article *also* carries v2's value at L70 and L481, contradicting itself | to confirm |
| P7-C5 / R5 | Optimizable cores 7197C on AWS (13.8w) and 17054C on Tencent Cloud (3.8w) → 11362C and 25046C | v1 L96, L99 → v2 L108, L115, L107 | **stale, framed as a live opportunity** — L490 | to confirm |
| P7-C6 / R6 | EC2 SP shortfall 3000C → 7C, with confirmed reducible scope 11362C | v1 L82 → v2 L207, L88 | **stale and live as an open action** — L571, L192 | to confirm |
| P7-C7 / R7 | Tencent Cloud ES monthly contract submitted but not landed → done, normal May cashback | v1 L86–87 → v2 L98 | **stale** — L201, open action L572 | to confirm |
| P7-C8 / R8 | The identify–analyze–track–review closed loop is at 0% → 50% | v1 L319 → v2 L549 | **stale** — L91; sibling rows *were* patched (L114, L115) | to confirm |

**6 of 8 stale**, and **8 of 8 corrections lost** — C1 and C3 keep v1's value under
an explicit as-of label, which is defensible on its own, but their replacements
are absent from the article entirely.

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P7-K1 | H1 target is 420w committed / 540w stretch against a Q1 baseline | v1 L37 → v2 L43 | to confirm |
| P7-K2 | Architecture rationalization is still 0% against its 16w–30w Q2 target | v1 L70 → v2 L76 | to confirm |
| P7-K3 | EC2 SP coverage 83%, daily on-demand spend 3.5w | v1 L77 → v2 L84 | to confirm |
| P7-K4 | Tencent Cloud Doris monthly contract landed, saving 4w | v1 L85 → v2 L97 | to confirm |
| P7-K5 | Fiat's model-call anomaly was throttled from a 1750/day peak to under 50/day, about 4w per month of identified anomaly | v1 L111 → v2 L162 | to confirm |
| P7-K6 | AI capability building overall stands at 60% | v1 L294 → v2 L526 | to confirm |

### P7 open judgement calls

1. **The same-measure/same-period reading — RULED accepted, 2026-08-15**, on the
   article-behaviour evidence above. The label stands and P7 keeps its 8
   contradictions. Had it been rejected, P7 would have had zero contradictions and
   left the positives. One consequence to carry into scoring: because the reading
   is a judgement about what the measure *is*, C1 and C3 — where the article keeps
   v1's value under an explicit as-of label — are scored on their lost
   replacement rather than on staleness. Their `Article today` column says so.
2. **Drops, if a non-empty list is wanted**, need the test "asserted in v1's
   newest column, not carried into v2's newest column, not contradicted". The
   three candidates are v1 L93 「新增可缩容68C」, v1 L94 (the architect-weekly
   follow-up, replaced in v2's 0514 column by a per-BU confirmation table), and
   v1 L110 「20260506评审方案」. All three were left out because a scorer testing
   "absent from v2" finds them present at v2 L325, L326 and L342 — the exact shape
   that silently corrupts a score.
3. **C2 is the messiest entry.** v2 struck 「117.3」 without supplying a new rate,
   so the replacement is the amount only. 44.4w against a 10w–15w target is
   296–444%, so the article's 「117.3% ✅」 is arithmetically stale too — but do not
   score for a specific new percentage. v2's own extraction misread this, recording
   the struck figure as live.
4. **C4's v2 quote is from the 0507 column**, because in the 0514 column the same
   sentence is struck (v2 L104). The document uses strikethrough for both "done"
   and "cancelled". Read as "item closed", because the 0514 column's 41.13w and
   36408C are built on that rightsizing. If it is a retraction, C4 becomes a drop.
5. **C6 mixes columns deliberately** (v1's gap is in the 0430 column, v2's 7C in
   0507, and 0514 carries no gap line because the confirmed scope exceeds the
   need). Kept because the article turns it into a live open action. Drop it if
   every contradiction must be anchored in the newest column.
6. **C5 bundles two numbers** because the article states them as one pair (L490).
   Split if the scorer needs one number per entry.
7. **Money markers.** Neither version contains `¥`, `CNY`, `RMB` or 人民币 — zero
   hits. Amounts are bare (`420w`) or USD-marked. The *article* introduces `RMB`
   and 「万 CNY」 at L18, L128, L137, L170–173, L516; those are downstream
   transcription artifacts and must not be converted.
8. **No internal version marker in either body** — identical title, no revision
   line. The only body-internal ordering signal is the set of weekly column
   headers. Note that v1's filename date (2026-04-09) is *older* than its newest
   column (20260430), so the filename date is not an as-of date for v1.
9. **Left out but valid under the same reading**, trimmed to the eight-item cap:
   database low-load 0.5w → 3.27w; HDFS 200TB → 600TB (article L491 stale); Kafka
   S3 deep archive planned-by-4.30 → done (L494 stale); Q3 其他 0% → 88.5% (L497
   stale); four AI-cost scenarios 0% → 30%; source governance 0% → 20% (corrected
   in the article at L115); other-data onboarding 0% → 10%; MySQL and Redis
   low-load counts.
10. **Out of scope**: the article merges five sources, so `~3,000 cores` at L169,
    L524 and L702, `~68万/month`, and the Gen5→Gen6 cancellation come from two
    meeting notes rather than this chain. Also unverified: several progress figures
    live only inside `<image>` payloads in both versions, so a claim marked absent
    could in principle sit inside an image.

---

## P8 — AI project portfolio overview

- `v1` = `.../raw/docs/2026-04-12-ai-项目全景-分类总览.md`
- `v2` = `.../raw/docs/2026-04-13-ai-项目全景-分类总览.md`
- `article` = `data/kb-knowledge/wiki/decision/ai-project-portfolio-status-q2-2026.md`

Revised the next day, and **not** the wholesale reorganisation the recorded
similarity of 0.079 suggests: 71 of 88 table rows are byte-identical and 212 of
~1,700 body lines differ. (That similarity figure is an artifact — see
[the similarity note](#note-the-recorded-similarity-figures-are-distorted).) The
real edit is a **re-attribution of infrastructure projects from named individuals
to teams**: the infra tables' `Owner` column becomes `团队`, four rows replace named
individuals with team names, and Lucas's attribution relocates to the section heading as
`@lucas.wan`. Secondarily, v2 deletes the whole `### 关键资源约束` headcount table
and three milestone rows.

Both bodies carry the same internal date marker `2026-04-12` (v1 L15, v2 L14) and
neither has a version number, so only the frontmatter `date` distinguishes them.
This is the case where A1's signal does all the work with no accidental help.

### Contradictions and their replacements

| ID | v1 → v2 | Evidence | Article today | Status |
|---|---|---|---|---|
| P8-C1 / R1 | The AI unified governance (three-review) process is owned by Lucas Wan → by the architecture team | v1 L233, L236 → v2 L228, L231 | **stale** — L27 and L188 state v1's ownership, hedged alongside v2's | to confirm |
| P8-C2 / R2 | AI Gateway integration is owned by Lucas Wan → by the architecture team | v1 L253, L256 → v2 L248, L251 | **stale** — L192 | to confirm |
| P8-C3 / R3 | The AI Coding standards project is owned by Lucas Wan → by the architecture team | v1 L122, L125 → v2 L66, L69 | not stale — the article states no owner for it | to confirm |
| P8-C4 / R4 | AI Trading Skills is owned by Lucas Wan and Victor → by the architecture and API teams | v1 L88, L91 → v2 L49, L52 | not stale — L144 names no owner; 「Victor」 occurs nowhere | to confirm |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v2 | Evidence | Status |
|---|---|---|---|
| P8-D1 | The AI team has 6 people and is severely insufficient across CS, personalization and infrastructure | v1 L1563–1569 | to confirm |
| P8-D2 | Infra support for AI is 3 people, spread across business lines, unsustainable | v1 L1574–1580 | to confirm |
| P8-D3 | The security team has 5 people with 25% of capacity consumed by AI projects for two months or more | v1 L1585–1591 | to confirm |
| P8-D4 | An AI asset convergence roadmap and freeze strategy is due in the week of 4/13–4/19 | v1 L1618, L1621 | to confirm |
| P8-D5 | Rockman formally joins as CTO on 4/14 | v1 L1629, L1632 | to confirm |
| P8-D6 | Locking the AI Coding 20% metric definition is a Q2 milestone | v1 L1662, L1665 | to confirm |

Five of the six are stated as current in the article today (L16, L94, L161, L49–52,
L185, L40, L194) — recorded because it sizes A2's RP1 arm, not because it gates A1.
D3 holds only in part: the article carries its 25%/≥2-month clause at L16 but never
states the security team's headcount, and `5 people` returns no hits.

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P8-K1 | Smart Router is a Go-native LLM routing service validated at ≥50% cost reduction | v1 L199 → v2 L160 | to confirm |
| P8-K2 | AI Gateway covers 82.5% of 40 target scenarios (33/40) | v1 L262 → v2 L257 | to confirm |
| P8-K3 | The portfolio totals 63 projects (24 infrastructure + 39 business) | v1 L1541 → v2 L1534 | to confirm |
| P8-K4 | 88 AI scenarios collected company-wide, 41 pending for lack of AI team resources, cross-BU common needs recommended for central build | v1 L1598 → v2 L1541 | to confirm |
| P8-K5 | Q1 2026 AI coding actuals: 74.89% adoption, 34.17% AI code ratio | v1 L322 → v2 L317 | to confirm |
| P8-K6 | Bybot automatically handles 83.85% of online CS volume at an 84%+ resolution rate | v1 L654 → v2 L647 | to confirm |

### Relocated, not dropped — the list that proves reorganisation was not read as deletion

- Lucas Wan's ownership of the infrastructure category is not deleted; it moves to
  the section heading (v2 L19 「## 一、基建类全局 AI 项目 @lucas.wan」, absent from
  v1 L24). This is why C1–C4 are about specific rows.
- Completed-infra rows 1 and 2 move from the top of the table (v1 L49, L66) to the
  bottom (v2 L163, L180), byte-identical; v2's row order is 3, 5, 6, 4, 7, 8, 9, 1, 2.
- Smart Router row 9 relocates (v1 L185 → v2 L146), content identical, still
  `Lucas Wan` — v2 did *not* teamify it.
- MCP 能力建设 and AI Coding 采纳率提升 also keep `Lucas Wan` in v2's `团队` column
  (v2 L291, L311; L283/L303 as first drafted were off by eight lines).
- The 88-scenario / 41-pending callout moves out from under the deleted
  `### 关键资源约束` (v1 L1598) to sit under `## 三、数据汇总` (v2 L1541), so the
  resource-shortage *framing* survives; only the headcounts drop.
- `AI Code Review CI 集成` is *expanded*, not contradicted: v1 「中台架构组」 (L108)
  → v2 「效能 / app / 中台架构组」 (L103).

### P8 open judgement calls

1. **Is `Owner` → `团队` a real re-attribution or a column relabel?** Read as real,
   because it is *selective*: rows 9, 12, 13 and 14 keep person names inside v2's
   `团队` column while rows 3, 5, 10 and 11 change to `架构`, and the header change
   is confined to the two infra tables (the 未开始 infra table and all four
   business tables still say `Owner`, v2 L497, L561, L707, L1150). A mechanical
   relabel would have converted all of them. The competing reading — an editor who
   started and stopped halfway — cannot be excluded from the text. **If rejected,
   all four contradictions collapse and P8 has none.**
2. **The column-header change itself is deliberately not an entry.** It is the
   umbrella cause of C1–C4, but "the infra tables use an Owner column" is not
   scoreable in article prose.
3. **Left out, wants a decision — the JIRA/GitLab MCP schedule.** v1 「Q2 W6」
   (L1684) → v2 「Q2」 (L1594). Q2 W6 is inside Q2, so v2 de-specifies rather than
   contradicts; but the week-level commitment was removed. The article says "Q2
   Week 6" in three places (L102, L157, L191), so promoting this adds a third
   stale hit.
4. **Left out**: v1 「新多站点架构测试完成 (100% AI 编写)」 (L1709) → v2 adds an
   「App」 scope qualifier (L1619); the underlying project row is identical in both.
   Restatement, not change.
5. **Do not trust the stored extractions on ownership.** v2's extraction invents
   `owner: Frontend Team` for the multi-site item where the raw text says `Arkin`,
   same as v1, and renders v1's 「中台 / AI Infra」 as "Middle platform team" — a
   translation, not a change. The extractions did independently corroborate C1 and
   C2, but every entry above is grounded in raw text.
6. **Drops are at the cap of 6**, and they are two editorial acts: D1–D3 delete
   `### 关键资源约束` (v1 L1546–1594) and D4–D6 delete three milestone rows.
   Collapse to 2 entries if scoring should count acts rather than claims.

---

## P9 — Bybit AI ToC project initiation

- `v1` = `.../raw/docs/2026-04-23-bybit-ai-toc-整体立项.md`
- `v2` = `.../raw/docs/2026-05-11-bybit-ai-toc-整体立项.md`
- `article` = `data/kb-knowledge/wiki/project/tradegpt-toc-product-roadmap.md`

A genuine positive rather than an append-only revision, but most of the
281→685-line growth is additive and the contradictions concentrate in schedule,
scope-limit and decision-reversal claims. v2's body carries two internal date
markers — the heading 「# 会议纪要 20260513」 (L656), which postdates v2's own
frontmatter date of 2026-05-11, and 「ABF（6月末启动，目标7.30主网）」 (L234) — so v2
is distinguishable from v1 by body content, not only by the date prefix.

### Contradictions and their replacements

| ID | v1 → v2 | Evidence | Article today | Status |
|---|---|---|---|---|
| P9-C1 / R1 | The end state is two parts (Skills for self-hosted OpenClaw users, plus an "online lobster" via the TradeGPT entry) → natural-language personalized answers plus cross-product order placement and risk management, structured as three pillars (问答交互 / 智能投顾 / Agent能力) | v1 L20 → v2 L122, L130, L133, L136 | **stale** — L21, L23–24 keep the two-component framing, L26 keeps "four interconnected product areas" | to confirm |
| P9-C2 / R2 | Phase 3 completes end of September → end of October | v1 L140–141 → v2 L124 | not stale — L339, and L341 explicitly records the move | to confirm |
| P9-C3 / R3 | Phases 1 and 2 complete mid-June and mid-August → end of June and end of August | v1 L108–109, L126–127 → v2 L124 | not stale — L339, L422, L461 | to confirm |
| P9-C4 / R4 | Top-20 Q&A optimization is a phase-1 deliverable → reassigned to phase 2 | v1 L121 → v2 L156 with the legend at L124 | **stale** — L434 lists it under Phase 1 | to confirm |
| P9-C5 / R5 | The phase-1 killer feature is a cross-product yield comparison spanning Earn, spot and RWA → yield routing limited to 5 capital-protected Earn products across 16 auto-release scenarios | v1 L205 → v2 L161–162, L316–317, L673 | not stale — no RWA or horizontal-comparison killer feature in the article | to confirm |
| P9-C6 / R6 | Personal dedicated OpenClaw instances open to high-value TradeGPT users in phase 2 → per-user hosted OpenClaw is a paid mid-tier subscription (phase 3) | v1 L134 → v2 L185–186, L650–653 | **stale** — L236 states the phase-2 exception, L465, L339; the article carries v2's Cloud OpenClaw (L68, L234, L477) alongside without resolving | to confirm |
| P9-C7 / R7 | The adopted Bybot/TradeGPT resolution is the hybrid keeping Bybot's own entry alive → Global keeps only the TradeGPT entry, Local keeps the CS entry | v1 L287, L281 → v2 L678, L662 | **stale** — L258, decision heading L297; v2's routing decision is appended at L260 without retracting the hybrid | to confirm |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v2 | Evidence | Status |
|---|---|---|---|
| P9-D1 | One OpenClaw per user costs 20 USD/month to run plus 20 USD/month in tokens, reaching 4M USD/month at 100K DAU | v1 L24 | to confirm |
| P9-D2 | OpenClaw cannot be shared across users — the design is single-user and sharing risks data contamination, forcing one instance per user | v1 L25 | to confirm |
| P9-D3 | Model selection is decided by parallel A/B testing of next-day retention, breaking ties on cost and response time | v1 L225, L227; 留存 occurs nowhere in v2 | to confirm — see call 5 |
| P9-D4 | TradeGPT will offer an A/B answer picker returning two answers in parallel, doubling as a way to test answer logic and compare models | v1 L233 | to confirm |
| P9-D5 | Regulators prohibit trading recommendations inside a CS bot, so a merged entry would fail licensing review on Local Sites and on a future licensed Global site | v1 L278, L280; neither 合规 nor 监管 occurs in v2 | to confirm |

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P9-K1 | The only four OpenClaw capabilities TradeGPT lacks — heartbeat trigger, workflow orchestration, long memory, multi-chat-app adaptation — will be built in-house | v1 L27 → v2 L184, L625–632 | to confirm |
| P9-K2 | The 26H1 Fee Conversion target is 80 Mil, 300% growth on 25H2's 19.9 Mil actual | v1 L63–72 → v2 L54–63 | to confirm |
| P9-K3 | Agent sub-account phase 1 covers account balance cap, fund transfer, max borrow leverage and max contract leverage | v1 L186 → v2 L620 | to confirm |
| P9-K4 | TradeGPT's private Skills may recommend on 180 days of Copy Trading leader performance while the product shows users only 90 | v1 L194 → v2 L639 | to confirm |
| P9-K5 | The TradeGPT entry end state is a hideable persistent floating button on the right offering page-specific preset questions | v1 L266 → v2 L287 | to confirm |
| P9-K6 | Phase-1 Skills and MCP are live, Skills covering basic query and execution across all product lines, MCP basic queries for most products | v1 L159 → v2 L593 | to confirm |

### P9 open judgement calls

1. **C3 bundles the phase-1 and phase-2 date moves** because v2 states all three
   deadlines on one line (L124) and two-week slips are individually low
   consequence. Split for strict one-assertion-per-entry (8 contradictions);
   collapsing C2 and C3 into one instead makes an article that gets phase 1 right
   and phase 3 wrong score ambiguously.
2. **C4 rests on colour markup, not prose.** 「Top 6-20 问答优化」 is phase 2 only
   via the `light-green` span plus the legend at L124; the 输出端 prose (L307) gives
   no phase. Drop C4 if colour-encoded phase assignment is too weak to score. The
   same mechanism carries C6's phase (absence of a highlight = phase 3).
3. **C6 is the least certain.** v2 never says high-value users will *not* get a
   personal OpenClaw; the contradiction rests on reading v2's user-tier table as an
   exhaustive segmentation. If the tiers are non-exhaustive this becomes a drop —
   and the article's current "Phase 2 exception" wording (L236) is exactly the
   reconciliation someone would write under that reading.
4. **C5's subject match is a judgement call**: v1's killer feature is a
   *comparison* across 理财+现货+RWA, v2's is *routing* into 5 capital-protected
   products. Treated as the same subject because both fill the phase-1 slot and v2
   uses the exclusive 「限于」. Alternatively re-cut as a drop (RWA comparison) plus
   a purely additive yield-routing entry.
5. **D3 could be a contradiction** against v2's 「底层模型定期更新（GPT -> Sonnet ->
   Haiku）」 — a predetermined migration path instead of retention-driven selection.
   Called a drop because v2 says nothing about selection criteria. The article
   fuses both (L307, L443), which is what a failed contradiction resolution looks
   like; reclassifying makes the stale count 5 of 8.
6. **Left out**: the OKR section retitle 「TradeGPT 业务目标」 → 「Bybit AI 业务目标」
   (a real scope reframing, but all three carried numbers are byte-identical);
   TradFi, where v2 splits the capability across phases rather than contradicting
   the phase-2 completion; AI Marketplace timing (v2's 「5.30 AI Marketplace」 reads
   as a note under 收益路由, too ambiguous); 「Skills编辑后台（视业务需要而定）」, already
   conditional in v1; and the token-quota statistic, which v2's 「交易量提升Token额度」
   presupposes.
7. **Additive, not superseding** (the list that proves P9 belongs with the
   positives rather than the negative controls): a whole new 智能投顾 pillar with
   two detail tables plus 大模型交易员 and 资产配置助手 (L320–585); two new OKR rows
   (Question Count per User 2.6 → 6.5, per Day 96.5K → 241K, L89–117); an
   Agent-capability resourcing table (L197–243); ABF独立部署; a new 运营支持 section
   (L245–263); new knowledge-base sources (L151–154, L293); A2UI generative layout
   (L157, L308–310); periodic base-model updates (L182, L644); and the entire
   「# 会议纪要 20260513」 section (L656–691). New is not corrected.
8. **Out of scope**: the article also compiles
   `raw/meetings/2026-05-20-bybit-ai-toc--weekly.md` and
   `raw/docs/2026-05-29-客服top5场景对比.md`; the BabyAI merger phases,
   internal-controls workstream and top-5 CS scenarios come from those.

---

## P10 — 2025 engineering efficiency report

- `v1` = `.../raw/local/2026-03-05-2025-engineering-efficiency-report.md`
- `v2` = `.../raw/local/2026-03-06-2025-engineering-efficiency-report-v2.md`
- `article` = `data/kb-knowledge/wiki/decision/2025-engineering-efficiency-report-full-data-decisions.md`

The revision changes the **measurement basis**, and every headline figure moves
with it. Neither body carries an internal version or date marker — the only "v2"
strings are in the frontmatter `id` and `title` — so ordering here genuinely
depends on frontmatter date and filename, which makes P10 a clean test of A1's
signal.

### Contradictions and their replacements

| ID | v1 → v2 | Evidence | Article today | Status |
|---|---|---|---|---|
| P10-C1 / R1 | Excludes delivery cycles over 90 days (~6.3% of the population) → over 120 days, removing 668 items (3.6%) | v1 L235, L10 → v2 L378, L12, L263 | not stale — L17 carries v2's rule, and Decision 1 recommends 90 → 120 (L116) | to confirm |
| P10-C2 / R2 | The 2025 sample is one population of 17,294 → two datasets, 18,445 full and 17,777 filtered, with purposes split (full for throughput, filtered for efficiency) | v1 L12 → v2 L12, L377 | not stale but blended — L30 keeps 17,294 as a live dataset row and L162 says 「17,294–17,777 data points」 | to confirm |
| P10-C3 / R3 | Annual on-time rate ~36%, H1 41.8% → H2 28.5% (−13.3pp) → ~25%, 33.1% → 18.2% (−14.9pp) | v1 L26 → v2 L31 | not stale — L169 uses v2's value | to confirm |
| P10-C4 / R4 | The best month of 2025 reached only 45% on-time → January was best at 35%, falling monotonically to 14.3% in October | v1 L32 → v2 L36, L51, L204 | **stale** — L84 states the 45% claim, in the same sentence as v2's 35%→14.3%, self-inconsistently | to confirm |
| P10-C5 / R5 | Median end-to-end delivery cycle ~15 days (13.8 H1, 17.8 H2) → ~17 days (15.3, 19.8) | v1 L24 → v2 L29 | not stale, replacement also missing — neither ~15 nor ~17 appears | to confirm |
| P10-C6 / R6 | The headline engineering-time metric is *average development duration*, ~9.2 days, +54.8% from 7.3 to 11.3 → *median R&D cycle*, ~6 days, +70% from 5.0 to 8.5, with the cycle decomposed into 产品准备期 plus 研发周期 | v1 L25 → v2 L28, L14–15 | **stale** — L21, L50, L54, L170 all carry v1's mean framing; v2's median sits alongside rather than replacing | to confirm |
| P10-C7 / R7 | Monthly throughput peaked at 1,907 in July, bottomed at 1,081 in October, a 43% swing → 2,036 and 1,182 | v1 L59 → v2 L135, L138, L176 | **stale** — L60 glues v1's extremes to v2's monthly average in one sentence | to confirm |
| P10-C8 / R8 | UserService's on-time rate fell 44.6% (Q1) → 22.0% (Q4) → 37.2% → 12.1% | v1 L101 → v2 L233 | **stale** — L282 | to confirm |

### Drops (measured, not gating)

| ID | Asserted by v1, absent from v2 | Evidence | Status |
|---|---|---|---|
| P10-D1 | The technical-requirement share of throughput fell from ~31% in Q1 to ~24% in Q4, squeezing technical improvement work | v1 L60; v2's monthly table has no business/technical split, and 技术需求占比 survives only as a 25–35% target (L317) | to confirm |
| P10-D2 | Recommends WIP limits per team to cut context switching | v1 L210 | to confirm |
| P10-D3 | Recommends an organizational-change buffer: a 2–4 week transition with lowered delivery expectations when a leader changes, plus a knowledge-transfer checklist | v1 L225 | to confirm |
| P10-D4 | Proposes a tech-lead quality tier of bug-association rate ≤0.3, rework ≤5%, and a per-capita monthly throughput baseline | v1 L163; v2's third tier is stale-requirement rate / estimation accuracy / P-1+P0 share (L322–326) | to confirm |
| P10-D5 | Mandates splitting any requirement whose delivery cycle exceeds 20 days, targeting ≤10 days | v1 L199; v2 manages size by tiering instead | to confirm |

### Controls

| ID | Asserted by both | Evidence | Status |
|---|---|---|---|
| P10-K1 | The population is JIRA requirements with Actual End Date in 2025.01–2025.12 and status MainNet | v1 L10 (source/window/status part only — the >90-day clause in the same line is C1) → v2 L11 | to confirm |
| P10-K2 | On-time means Actual End Date ≤ Planned MainNet Date, with requirements lacking a planned date excluded | v1 L236 → v2 L381 | to confirm |
| P10-K3 | Team attribution uses the JIRA `dept_l2` field | v1 L237 → v2 L382 | to confirm |
| P10-K4 | August 2025 is the inflection point after which efficiency deteriorated without recovering | v1 L30 → v2 L194 | to confirm |
| P10-K5 | Three-point estimation should replace single-point estimation, with calibration workshops for the lowest on-time teams | v1 L194 → v2 L342 | to confirm |
| P10-K6 | DORA metrics (deployment frequency, change lead time, MTTR, change failure rate) should be added long-term | v1 L221 → v2 L363 | to confirm |

### Measurement-basis changes — why C1–C8 are contradictions rather than new figures

1. **Exclusion rule >90 → >120 days** (v1 L10, L235 → v2 L12, L378). The root
   change; it invalidates every efficiency figure in v1. C1, C3, C5, C6 and C8 are
   downstream. Note the exclusion rate also moves from 「约占 6.3%」 to 3.6% —
   roughly 1,151 items excluded against 668.
2. **One filtered population → a two-dataset design** with purposes split
   (v2 L377–378). Invalidates every throughput figure: annual 17,294, monthly
   average 1,441, H1 8,916 / H2 8,378 and −6.0% (v2: 9,412 / 9,033, −4.0%), and
   every monthly cell of v1's §2.1. C2 and C7 are downstream.
3. **Overall cycle decomposed into 产品准备期 + 研发周期** (v2 L14–15, L379–380).
   The most consequential change, because it re-attributes the H2 decline: v1 says
   delivery cycle and development duration both worsened; v2 says the R&D cycle
   nearly doubled while product preparation stayed flat (5.3 → 5.5 days), making
   the bottleneck engineering execution and the product queue a separate
   long-tailed problem (mean 13.5 vs median 5.5, P90 43.5).
4. **Statistic and scope changed: mean 平均开发时长 → median 中位研发周期** (dev+test,
   from dev start). v2 reports no mean anywhere, so v1's ~9.2 days, 7.3→11.3,
   +54.8% and Q1 7.1 → Q4 13.5 have no counterpart. C6.
5. **Team-level measure changed from delivery cycle to R&D cycle**, so v1's
   team-level cycle values have no counterpart while team-level on-time rates are
   restated on the new basis and all move down. C8.
6. **Target basis moved with the metric basis**: the 2026 on-time target drops from
   ≥55% (H2) to ≥40%, and the cycle target changes measure from median delivery
   cycle ≤12 days to median R&D cycle ≤5.0 days plus median product preparation
   ≤5.0 days.
7. **Unchanged basis elements**, hence K1–K3: data source, time window, status
   filter, on-time definition, team attribution.

### P10 open judgement calls

1. **C6 is the softest entry.** A mean of 9.2 days and a median R&D cycle of 6.0
   days are different statistics over different spans and could coexist without
   logical conflict. Scored as a contradiction because the rule counts "a metric
   redefined" and because v2 deliberately retires the mean. Demoting it to a drop
   removes the gate on the single most consequential change in the revision.
2. **Left out — the causal attribution of the Aug–Oct dip.** v1 attributes it to
   organizational restructuring and leader transitions (L82, L126–131); v2
   explains the same months with summer absence, July overdraft and the holiday
   calendar (L191–194) and asserts 「春节/国庆…并非 H2 效率下滑的主因」 (L39). Because
   v1 words it as 可能原因, this was judged neither contradiction nor drop and left
   out. The article states v1's framing as current (L44, L299–301), so ruling it a
   contradiction raises the stale count to 5 of 9.
3. **Left out as derivative**: monthly average throughput 1,441 → 1,537; H1→H2
   change −6.0% → −4.0%; the 2026 targets (article already carries v2's ≥40%);
   dashboard alert thresholds; and the large-requirement metric redefinition.
4. **Team-level contradictions are a family; one is labelled.** Every team's Q1/Q4
   on-time rate is restated downward and the roster itself changes (v1 has 8 rows,
   v2 has 10 different ones). UserService was picked because v1 calls it the worst
   deterioration and the article repeats v1's figures verbatim. Fiat Channel
   (L277) and Compliance (L283) are equally stale if a second entry is wanted.
5. **Five sources, only two of them this pair.** The article also compiles
   `2026-03-05-…-report-full.md`, `2026-03-06-2026-engineering-team-goals.md` and
   `2026-03-06-2026-q1-engineering-efficiency-report.md`. Numbers that look like
   v1 residue but are legitimately from the full-data report and must not be
   scored: 「984 | 5.3%」 (L30), 「9.3 days (annual)」 (L170), 「28% (full-data
   view)」 (L84), and the Q4 full-vs-filtered table (L260–263). The unambiguous v1
   fingerprint is the H1 7.3 / H2 11.3 / +54.8% triple.

---

## Note: the recorded similarity figures are distorted

test-set.md's `sim` column is computed by `py/scripts/select_cases.py`'s
`diffstat`, which calls `difflib.SequenceMatcher(None, earlier, later)` over body
lines and leaves **`autojunk` at its default of `True`**. For sequences of 200
elements or more that heuristic discards any line occurring in more than 1% of
the second sequence. In markup-heavy documents that means blank lines, table
delimiters and Lark attribute lines. The recorded values reproduce exactly with
`autojunk=True`, so this is the metric the corpus was stratified with, inherited
from the original throwaway script rather than introduced by FX1's rebuild.

| Case | Recorded | `autojunk=False` | Identical body lines |
|---|---|---|---|
| P8 | 0.079 | **0.928** | 1544 of 1709 |
| P5 | 0.217 | 0.645 | 3833 of 6397 |
| P2 | 0.448 | 0.485 | 759 of 2042 |
| P9 | 0.168 | 0.333 | 161 of 685 |
| P3 | 0.096 | 0.253 | 270 of 1155 |

`stratum()` calls anything below `_REWRITE_SIMILARITY = 0.55` a rewrite.
Corrected, P8 (0.928) and P5 (0.645) are not rewrites, so the strata table and the
"123 of 682 articles at 18%" figure rest on a distorted metric. No label here is
invalidated, because labels are drafted from the documents, not from the
similarity, and the 18 chains already selected do not change. Captain's call,
recorded as an open item rather than fixed silently.

## Note: a verification hazard in the drafting method

The recipe `diff <(sed -n '/^---$/,/^---$/!p' A) …` silently suppresses body
content between the third and fourth standalone `---`, so on a document with
horizontal rules it hides whole sections — in P4's case the entire §5 module
table, which makes the v3→v4 body diff look empty. 20 of the 38 fixture documents
have more than two standalone `---`, affecting P3, P4, P5, P8 and P10 (P2, P7 and
P9 are clean).

Checked rather than assumed: all 17 `superseded-drop` claims for P3, P5 and P10
were re-verified by direct negative grep on their distinguishing phrases, and
every one returned 0 hits in the later version. P4's drafting used full-file
diffs, and P8's confirmed each absence by grep. So no drop list is corrupted, but
anyone extending this label set should not reuse that `sed` recipe.
