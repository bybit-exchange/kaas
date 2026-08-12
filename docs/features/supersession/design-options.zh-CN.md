# Supersession：让后来的文档覆盖先前文档说过的话

> 本文是 [design-options.md](design-options.md) 的中文翻译副本。**英文版是唯一正本**，
> 两者必须保持同步；出现分歧时以英文版为准。标识符、文件路径、字段名一律保留英文原文。

状态：D1–D5 全部定案——D1、D2 于 2026-08-10 在本文定案（见[已定案的决策](#已定案的决策)），
D3、D4、D5 于 2026-08-12 定案。决策记录已移至 [spec.md](spec.md)，该文档同时把 path A 拆成
A1 与 A2，并明确了本文留作隐含的触发条件。本文保留下来的是这些选择背后的方案分析。
撰写日期：2026-08-10。

触发这份文档的场景：一份项目方案有 v1 和 v2。两份都编译进去，结果应该是一篇陈述 v2 的
文章，而不是一篇同时陈述两版、自相矛盾的文章。今天的结果是后者。

这不是新发现，而是一个已经被记录在案的缺口。extraction layer 的 `spec.md` 把它记为 O4a
（`docs/features/extraction-layer/spec.md:830-837`），已发布的 four-layers 文章记了两处
（`docs/articles/kaas-four-layers.md:195`、`:307`），代码里也有一句 docstring 写着：
"Until a supersession path exists, an operator reading the count is the useful thing"
（`py/src/kb_ai/core/merge.py:512-521`）。它们都没说这个修法该长什么样，本文补的正是这块。

## 两种形态，只有一种被检测到

**A 形态——同一份文档原地改版。** `raw/plan.md` 内容变了，checksum 变化，抽取重跑，
写相位把新的抽取结果 merge 进那篇旧文本已经贡献过的文章。检测到了：compile 会把这类
文档记为 revised，并点名需要人类重读的文章（`py/src/kb_ai/commands/compile.py:329`、
`:632-640`）。没修：紧接着的那次 merge 只能追加。

**B 形态——v1 和 v2 是两份独立文档。** 在系统看来，`raw/plan-v1.md` 和 `raw/plan-v2.md`
毫无关系。两份各自独立对照文章目录做分类，双双落到同一篇文章上，而系统里任何地方都不持有
「其中一份替代了另一份」这个论断。完全没检测。

触发本文的场景属于 B 形态。它也是更常见的那一种：一份拿到 v2 的方案文档，通常是一个新文件
或一篇新的 Lark 文档，而不是对旧文档的一次编辑。

## 今天挡在路上的五件事

**1. 两条 merge 路径都只能追加。** `merge-diff.md` 只提供两个 patch action：
`append_to_section` 和 `new_section`。`merge-rewrite.md` 说的是 "integrate new
information naturally" 和 "do not duplicate information already in the article"
——完全没有一条关于「某个陈述现在已经错了」。没有任何原语能删除或替换一句话。

**2. 时效信号到不了写入端。** 走 Lark 导入路径的 raw 文档带有 frontmatter `date`
（`data/kb-smoke-newpipeline/raw/` 下任意文件可见），文档目录也确实去读它
（`py/src/kb_ai/storage/index.py:24`，在 `:262-263` 从 raw frontmatter 读出）。
现在每条路径都读到了。`distill` 仍然会给每个摄入的文件前面加一行 `<!-- source: ... -->`
（`py/src/kb_ai/distill.py:82`），这曾经把文档自己的 frontmatter 挤出第 0 行、让
`_document_frontmatter` 退化成 `{}`——没有 date、没有 source，title 退化成文件名。
issue #37 在 raw 文档的读取处修掉了它：解析前先跳过前导的 HTML 注释。修复后在
`data/kb-2026-06` 上实测：108 条文档目录行全部带 date 和 source、没有一条再以文件名为
title，修复前是 0/108，而且不需要重新摄入。

这个修复只落在一个私有函数 `_document_frontmatter` 里。下面的 D4 会在写相位再加一个 raw
frontmatter 的读取方，D3 会再加一个 raw 内容的写入方，所以谁先落地，谁就该把这段跳过逻辑
提成共用 helper，而不是直接调 `split_frontmatter`、把这个坑重新挖开。

再往后，对所有路径仍然一律到此为止。抽取层的 provenance 记录里没有文档日期
（`py/src/kb_ai/storage/extraction.py:71-89`），merge 的 user message 只发出
`- Source: <path>` 加上 payload 字段（`py/src/kb_ai/core/merge.py:95-154`）。
那个决定写什么的模型，没人告诉它哪个来源更新。

有一点让当前行为显得比实际好，值得点明：在参考知识库里日期就在文件名里
（`window-2026-06__docs__2026-06-01-...`），所以模型有时能从 source path 顺带推断出
先后顺序。这不是任何机制保证的信号。

**3. 一次运行内多个来源命中同一篇文章时，归属被销毁。** `_combine_extractions` 把每个
来源的 claims、decisions、action items 拼接成一个扁平的袋子，并把路径连成一个逗号分隔的
字符串（`py/src/kb_ai/core/extract.py:778-794`）。当 v1 和 v2 在同一次编译里处理时，
写入端收到的是一份不加区分的列表，v1 那条已被替代的 claim 和 v2 的替代版本无法分辨。
merge 和 create 两条路都要过这一步。

**4. 写入顺序不稳定。** 文章分组是并行写的——两条路径默认都是 16 个 worker
（`py/src/kb_ai/commands/compile.py:595-597`、
`py/src/kb_ai/commands/pipeline/_phase_write.py:215-231`）。在一个分组内部，ops 按
raw 扫描顺序排列，也就是路径排序。跨运行之间，顺序取决于什么东西在什么时候被摄入。
所以连「最后写的赢」这种便宜的兜底都用不上：不存在一个确定的「最后写的」。

**5. classify 看不到矛盾。** 分类器拿到的是目录行——path、title、summary——从来看不到
文章正文（`py/src/kb_ai/prompts/defaults/classify.md`）。它可以把 v2 路由到 v1 建的那篇
文章，这一步是对的，但它没有办法说出「并且这条替代了里面已有的内容」。

## 「覆盖」应该是什么意思——这个要先定

这个词底下藏着三种不同的产物。

**latest-wins（最新者胜）。** 文章正文只陈述 v2。frontmatter 的 `sources:` 列表保留
两份文件，所以 provenance 不丢，`raw/` 里也仍然逐字保留着 v1。规格最好写。代价是：
一个读者问「我们之前是怎么定的、什么时候改的」，从 wiki 里什么也得不到。

**current-plus-trail（现状加一条替代痕迹）。** 正文陈述 v2，并显式记一条注解说明 v1 说过
什么、以及它从什么时候起不再成立。本仓库自己的文档就用的正是这个惯例——
`docs/features/extraction-layer/spec.md` 里贯穿着 `[Superseded 2026-08-08: ...]` 标记。
代价是每一篇曾被修正过的文章都要多花篇幅。它的降级方式是安全的：一次标错的 supersession
留下的是两条都还能读的陈述，而不是删掉了对的那条。

**article family（文章家族）。** v1 和 v2 各自保留为独立文章，另有一篇 canonical 文章
指向当前那篇。历史最干净，同时对检索最不友好：目录行翻倍，而 page selection 得学会
「刚检索到的两个候选其实是同一件事的不同时点」。

推荐：current-plus-trail，两个理由都不是审美层面的。检索读的是文章正文，所以静默删除会让
「变了什么」这个问题在不回到 `raw/` 的情况下无法回答。另一个理由是失败模式才是关键：模型
迟早会在「谁替代谁」上判错，而一条错误的痕迹记录是可恢复的，一次错误的删除不是。

## 三条实现路径

**A——replace 原语加时效信号，不引入新的检测。** 给 `merge-diff.md` 加一个 replace
action，给 `merge-rewrite.md` 加一条 supersession 规则。把文档日期带到写入端能看见的地方。
不再把多个来源拍平成一个袋子，让写入端拿到可以排序的按来源分块。

这是能奏效的最小改动，而且两种形态都覆盖：A 形态成立，因为改版后的抽取 merge 进的那篇文章
现在可以被它修正；B 形态成立，因为 v2 merge 进 v1 写出的那篇文章，可以就地修正它。
它不需要任何新产物，也不需要任何新的 LLM pass。

有两项代价不那么显眼。编辑两个 merge prompt 会让 `write_prompt_version` 变化
（`py/src/kb_ai/core/merge.py:504-533`），而这个值只被记录和上报、不对任何东西把关，
所以已有文章不会被重访——修复只对将来的 merge 生效。另一项是按来源分块也会改变 *create*
路径看到的东西，那是对每一篇新文章的正文质量改动，不只是对修正场景。这个要实测，不能靠假设。

**B——A 加上显式的 lineage。** 增加一个步骤，把「文档 X 替代文档 Y」这个论断记为它自己的
产物、上报它，并把它作为指令喂给 merge，而不是留给模型自己推断。信号候选：raw frontmatter
的 `date` 加标题相似度加共享的 `source`/`url`，或者对文档目录跑一次 LLM pass。

它买到的是文本本身有歧义时的可靠性，以及一个人类可以纠正的、可审计的论断。代价是一个新产物，
而 LLM 那个变体会在一条目前不花钱的路径上按文档数花钱。这项应该由 A 的一次实测失败来证明其
必要，而不是预先买下。

**C——重新合成，而不是打补丁。** 当一篇文章的任一来源改版时，从它全部来源的抽取结果重写整篇
文章，而不是对现有文本打补丁。这样 supersession 就变成单次写调用内部的排序问题，完全不需要
replace 原语。

这是唯一会收敛的选项：什么都不会累积，因为什么都不往前带。它同时是最贵的，而且会丢弃对文章的
手工编辑。成本基线已经有了——108 份文档的参考知识库全量重编译是 30.2 USD，对比一次抽取
pass 的 17.5 USD（`docs/articles/kaas-four-layers.md:185-191`）；另有一次针对 88 份文档
的测量，两次编译一次产出 48 篇文章、另一次 98 篇（`:308-313`），所以重新合成还会继承
classify 的不稳定性。

推荐：A 作为要发的那个增量，因为它是解开其余两条路的那一步，且不需要新产物。C 是 revised
文档问题的最终答案，等到文章级可复现性值得付这个钱时，它应该立成自己的 feature。B 只在有
证据时才做。

## 已定案的决策

D1、D2 于 2026-08-10 定案。D3、D4、D5 仍然未决，实现 spec 还得回答它们。

### D1——正文写当前论断，外加一条被替代的记录

文章陈述现在成立的那一条，并显式记一笔：上一条说的是什么、什么时候不再成立。旧句子是被这对
内容替换掉，而不是与它们并存——一篇把两条都当作当前有效来陈述的文章，正是本 feature 要修的
那个 bug。

格式用示例固定下来——就是本仓库自己的文档已经在用的写法：

```markdown
The gateway targets 2 000 requests per second.

[Superseded 2026-06-14 by raw/plan-v2.md: the earlier target was 1 200 requests
per second.]
```

这个格式带四条规则：

- 一个方括号块，以 `[Superseded ` 开头、以 `]` 收尾，这样一次 grep 就能找出 wiki 里所有
  被替代记录，读者也能一眼区分正文与这类簿记。
- 日期取**做出替代的那份文档**的 `date`，来自它的 raw frontmatter——不是编译日期。编译日期
  每次重编译都会变，会把它本该记录的历史改写掉。
- `by <raw path>` 点明是谁替代的，读者可以直接落到 `raw/`，不用猜该翻回哪个来源。
- 这个块紧跟在它所纠正的那句话之后，同一节内。retrieval 读的是文章正文，放得更远就等于多一次
  查找，而 page selection 没有理由去做这次查找。

不选 latest-wins，是因为静默删除会让「我们之前决定了什么、什么时候变的」在不翻回 `raw/` 的
前提下无法回答；不选 article family，是因为 catalog 行会翻倍，而 page selection 无从知道两个
候选是同一件事的两个时点。决定性的理由是失败形态：模型有时会判错谁替代谁，而一条记错的
supersession 记录是可恢复的，删错一句话不是。

### D2——先发路径 A，两项代价一并接受

两个 merge prompt 里加 replace 原语、把文档日期送到写入端、用按来源分块取代一个扁平袋子。
B 继续以 A 的实测失败为前置；C 留作它自己的一个 feature。

A 名下点明的两项代价都是接受，而不是划出范围：

- **已有文章不被把关。** 编辑 merge prompt 会让 `write_prompt_version` 变化，而它只被记录和
  上报、不把关任何事，所以已经写好的文章会一直留着它们的自相矛盾，直到别的什么东西重写它们。
  接受的理由是：把它变成 gate 属于 D5，而 D5 的推荐正是保持只上报——一次 prompt 编辑就重写
  整个 wiki，那是 C 的决策，不是 A 的。
- **create 路径也会看到按来源分块。** 这是对每一篇新文章的散文质量改动，不只影响纠正类改动。
  接受，但附带一次实测而非凭信心：这项改动只有在同一批文档分别按两种形态编译、并比较产出的
  文章散文之后才发车，语料就用 [test-set.md](test-set.md) 已经为本 feature 建好的那一份。

## 待决策项

每一行都需要在动手实现前有答案。「闭环条件」是这项决策关闭的判据。

| # | 决策 | 落点 | 选项 | 推荐 | 闭环条件 |
|---|---|---|---|---|---|
| D1 | 「覆盖」在文章正文里产出什么 | `prompts/defaults/merge-rewrite.md`、`merge-diff.md` | latest-wins / current-plus-trail / article family | current-plus-trail——**2026-08-10 定案** | ✅ 已关闭：[已定案的决策](#已定案的决策)用示例固定了标记格式 |
| D2 | 先发哪条实现路径 | `core/merge.py`、`core/extract.py:778-794` | A / B / C | A——**2026-08-10 定案** | ✅ 已关闭：[已定案的决策](#已定案的决策)接受了 A 的两项代价，没有一项被划出范围 |
| D3 | 经 UI 摄入的文档，时效信号从哪来 | `internal/api/submit.go:60-65` 原文直写 raw 内容，不带 frontmatter | 提交时写入 frontmatter / 读 task 记录 / 接受这条路径没有日期 | 提交时写入 frontmatter——这是唯一能让日期持久化的做法，而且 `derive` 会拷贝 `raw/`，所以它能跟着走（`py/src/kb_ai/derive/_layout.py:193-199`） | 决策已记录；若选「接受没有日期」，则要指定无日期来源下的 merge 兜底行为 |
| D4 | 日期存在 `extraction/` 里，还是在写入时从 `raw/` 读 | `storage/extraction.py:71-89` 的 provenance，对比读一次 raw frontmatter | 新增 provenance 字段 / 写入时读 raw | 写入时读 raw——不花任何 LLM 调用，也不需要 bump `schema_version`，而一次 bump 会拒收每一个已有文件（`storage/extraction.py:199-203`），进而以 17.5 USD 重抽整个知识库。已不再受阻：issue #37 已修，在 `distill` 建的库上去读 raw frontmatter 同样能拿到 date | 已定案，且无论选哪个都记下与 extraction layer 自己那条 D1 的张力：写相位重新去读 `raw/` 是对「写相位只从 `extraction/` 读」的一次刻意破例（`docs/features/extraction-layer/alignment-questions.md:762-771`） |
| D5 | 有了 replace 原语之后，`write_prompt_version` 是否升级为一道 gate | `core/merge.py:504-533`、`storage/lag.py` | 保持只上报 / 升级为 gate | 本 feature 内保持只上报——把关正是让一次 prompt 编辑重写整个 wiki 的那个开关，而那是 C 的决策，不是 A 的 | 已定案；若维持不变，写进 spec 的 non-goals |

## 本文没有决定的事

- 文章能不能变小。上面除 C 以外的每个选项，都会让文章在字节数上单调增长，即使它在论断数上
  已经不再增长。
- classify 的不稳定性。同样 88 份文档产出 48 篇或 98 篇文章
  （`docs/articles/kaas-four-layers.md:308-313`）位于这里一切的上游，任何选项都不触及它。
- 孤立的抽取文件，它仍然是 extraction layer 明确声明的 non-goal。
