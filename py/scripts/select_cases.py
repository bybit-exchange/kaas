"""Select supersession cases from a KaaS KB (supersession spec FX1).

Finds the lineage chains in a KB, measures how far each version moved, and says
which of them the pipeline was actually asked to reconcile — the input the fixture
and the labelling in [test-set.md](../../docs/features/supersession/test-set.md) are
built from. No LLM call, so re-running it costs nothing.

Two shapes, and the difference matters to what a chain proves:

- **A**, one document re-fetched after an edit: same ``id``, several files.
- **B**, v1 and v2 ingested as two documents: nothing but the title connects them,
  so this goes through ``storage.lineage``, exclusions and all (spec RP4).

This replaces a script that measured the corpus and was then thrown away. Its
output survived, and every rule here was reconstructed against it: the diffstats of
all 79 non-identical chains and all 134 strata reproduce exactly. Three places
deliberately differ, each because the original was wrong rather than because the
rule changed:

- Comma-joined ``sources:`` entries are split. Articles written before per-source
  blocks recorded a whole batch as one entry, and reading it as a single path
  undercounted the shared-article column — 34 duplicate-stratum groups against the
  43 the corpus has, 10 rewrites against 12.
- Shape B carries the two exclusions ``storage.lineage`` implements. The emitted
  file has neither, so it holds three cross-source pairs and a set of one-to-ones.
- Titles are compared case-insensitively and a three-part ``v1.0.0`` marker counts,
  which found one chain the original missed.

Usage::

    uv run python scripts/select_cases.py --kb ../data/kb-knowledge --out cases.json
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kb_ai._frontmatter import read_document_frontmatter          # noqa: E402
from kb_ai.derive import parse_sources                            # noqa: E402
from kb_ai.storage.lineage import (                               # noqa: E402
    known_person_names,
    lineage_groups,
    read_document_facts,
    strip_version_marker,
)
from kb_ai.storage.store import KBStore                           # noqa: E402

# Below this, a later version is a rewrite rather than an edit of the earlier one.
# test-set.md's stratification, kept as a name so the tables and the code cannot
# drift apart.
_REWRITE_SIMILARITY = 0.55
# A change of three lines or fewer on one side is noise: a date in a header, a
# typo, a moved link. Both bounds are the corpus's, not chosen.
_NOISE_LINES = 3


def body_lines(content: str) -> list[str]:
    """The lines a version comparison runs over: the body, never the frontmatter.

    Every version of a document differs in ``date``, ``id`` and ``checksum``, so a
    whole-file diff reports three changed lines on two files whose prose is
    identical — enough to push a noise-stratum group into the edit stratum.

    The closing delimiter's own line break is counted, which is what makes these
    counts match the ones recorded in test-set.md: the original split the text on
    the delimiter rather than on lines, so the newline that ended it stayed with the
    body. A rule that disagreed by one line per document would put every stratum
    boundary case somewhere else, so the offset is reproduced rather than tidied.
    """
    _frontmatter, body = read_document_frontmatter(content)
    return ("\n" + body).splitlines()


def diffstat(earlier: list[str], later: list[str]) -> tuple[int, int, float]:
    """(added, removed, similarity) between two versions' body lines.

    A replaced line counts on both sides, which is what makes "removed" mean
    "content the later version does not carry forward" rather than "lines deleted".
    """
    matcher = difflib.SequenceMatcher(None, earlier, later)
    added = removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    return added, removed, round(matcher.ratio(), 3)


def stratum(identical: bool, added: int, removed: int, similarity: float) -> str:
    """Which stratum a chain falls in, and therefore what it is evidence of.

    The order of these tests is load-bearing, and the corpus settled it. A version
    that only appends is a negative control however much it appends — marking
    anything in it superseded is a false positive — but a large enough append drives
    similarity below the rewrite threshold anyway: two corpus groups add 134 and 182
    lines while removing 2 and 1, at similarity 0.056 and 0.367. Testing similarity
    first called both of them rewrites, which would have put two negative controls
    in the positive set.
    """
    if identical:
        return "D-duplicate"
    if removed <= _NOISE_LINES and added > _NOISE_LINES:
        return "B-append-only"
    if added <= _NOISE_LINES and removed <= _NOISE_LINES:
        return "C-noise"
    if similarity < _REWRITE_SIMILARITY:
        return "A1-rewrite"
    return "A2-edit"


def _raw_documents(store: KBStore) -> list[str]:
    return sorted(p.relative_to(store.base_dir).as_posix()
                  for p in (store.base_dir / "raw").rglob("*.md")
                  if not p.name.startswith("."))


def _article_sources(store: KBStore) -> dict[str, list[str]]:
    """Every article's ``sources:`` entries, batch entries split apart."""
    out: dict[str, list[str]] = {}
    wiki = store.base_dir / "wiki"
    for path in sorted(wiki.rglob("*.md")):
        rel = path.relative_to(store.base_dir).as_posix()
        entries, _reason = parse_sources(store, rel)
        if entries:
            out[rel] = entries
    return out


def select_cases(store: KBStore) -> list[dict]:
    """Every lineage chain in the KB, measured and stratified."""
    rels = _raw_documents(store)
    facts = {rel: read_document_facts(store.read_raw, rel) for rel in rels}
    checksums = {rel: str(read_document_frontmatter(store.read_raw(rel))[0]
                          .get("checksum") or "") for rel in rels}

    by_id: dict[str, list[str]] = defaultdict(list)
    for rel in rels:
        if facts[rel].doc_id:
            by_id[facts[rel].doc_id].append(rel)

    chains: list[tuple[str, str, str, list[str]]] = []
    for doc_id, members in by_id.items():
        if len(members) > 1:
            ordered = _date_order(facts, members)
            chains.append(("A", doc_id, facts[ordered[0]].title, ordered))
    for group in lineage_groups(facts.values(), known_person_names(store.wiki_dir)):
        chains.append(("B", group.title, group.title, list(group.members)))

    articles = _article_sources(store)
    cases = []
    for shape, key, title, members in chains:
        first, last = members[0], members[-1]
        identical = len({checksums[m] for m in members}) == 1 and bool(checksums[first])
        earlier = body_lines(store.read_raw(first))
        later = body_lines(store.read_raw(last))
        added, removed, similarity = diffstat(earlier, later)
        cases.append({
            "shape": shape,
            "key": key,
            "title": title,
            "chain": members,
            "n": len(members),
            "identical": identical,
            "linesV1": len(earlier),
            "linesVn": len(later),
            "added": added,
            "removed": removed,
            "sim": similarity,
            # Every member in one article's sources:, which is the only case where
            # the pipeline was actually asked to reconcile the versions.
            "shared_article": sorted(art for art, srcs in articles.items()
                                     if all(m in srcs for m in members)),
            "stratum": stratum(identical, added, removed, similarity),
        })
    return sorted(cases, key=lambda c: (c["title"].casefold(), c["shape"], c["chain"]))


def _date_order(facts: dict, members: list[str]) -> list[str]:
    """Oldest first, undated last in path order — the order the writer's blocks and
    the lineage report both use (WP5), so no two of the three disagree about which
    version is later.
    """
    dated = sorted((m for m in members if facts[m].date is not None),
                   key=lambda m: (facts[m].date, m))
    undated = sorted(m for m in members if facts[m].date is None)
    return dated + undated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kb", required=True, help="path to the KB to scan")
    parser.add_argument("--out", help="write JSON here instead of stdout")
    args = parser.parse_args(argv)

    cases = select_cases(KBStore(args.kb))
    text = json.dumps(cases, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)

    counts: dict[str, int] = defaultdict(int)
    shared: dict[str, int] = defaultdict(int)
    for case in cases:
        counts[case["stratum"]] += 1
        if case["shared_article"]:
            shared[case["stratum"]] += 1
    print(f"{len(cases)} chains "
          f"({sum(1 for c in cases if c['shape'] == 'A')} shape A, "
          f"{sum(1 for c in cases if c['shape'] == 'B')} shape B)", file=sys.stderr)
    for name in sorted(counts):
        print(f"  {name}: {counts[name]} ({shared[name]} with a shared article)",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
