"""Audit the shape of a KB's articles -- the two checks both FX4 arms run.

Neither check costs an LLM call, and neither is covered by ``kb-ai check``, whose
extraction line counts documents against extractions and whose grounding line
skips a ``schema_version: 1`` KB entirely.

**Comma-packed and duplicated ``sources`` entries.** G2's claim is that a source
is an attributable unit. Articles written before per-source blocks recorded a
whole batch as one YAML item (``- raw/a.md, raw/b.md``), and some list the same
path twice, which is the double-count the U1-U4 controls exist to catch. Across
the 682 articles in ``data/kb-knowledge`` there are 91 packed entries in 46
articles and 47 duplicated paths in 30. Both are old-writer output, so a fresh
run should reproduce neither -- which is only a result if someone looks.

**Frontmatter that does not start at byte 0.** ``split_frontmatter`` returns None
for content that does not open with a delimiter line, so where the writer left
its own preamble above the block -- seven of those 682 articles, one of them
additionally wrapped in a ``` ```markdown ``` fence -- every key is invisible to
every reader: no ``title`` for the catalog, no ``date`` for WP2's ordering
signal, and no ``sources`` for ``derive`` to copy, which fails G2 outright rather
than mis-shaping it.

The walk goes over the filesystem rather than ``existing_articles()`` because the
index is built from the frontmatter the second defect hides: an article with an
unreachable block is invisible to every reader that goes through it. Everything
under ``wiki/`` is an article -- the catalog the pipeline writes lives at
``<kb>/index`` and is never reached.

Usage::

    uv run python scripts/audit_articles.py --kb ../data/kb-knowledge \\
        --out /tmp/baseline-audit.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kb_ai._frontmatter import split_frontmatter  # noqa: E402

_BOM = "﻿"


def _articles(kb: Path) -> list[Path]:
    wiki = kb / "wiki"
    if not wiki.is_dir():
        return []
    return sorted(p for p in wiki.rglob("*.md") if p.is_file())


def _entries(loaded: object) -> list[str] | None:
    """The ``sources`` value as a list of entries, or None when there is none.

    A bare string counts: the value is what the writer emitted, and one article
    holding ``sources: raw/a.md`` is still making a provenance claim.
    """
    if isinstance(loaded, str):
        return [loaded] if loaded.strip() else None
    if isinstance(loaded, list):
        kept = [e for e in loaded if isinstance(e, str) and e.strip()]
        return kept or None
    return None


def _paths(entry: str) -> list[str]:
    """One entry's paths. Splitting on commas is how the packed ones read."""
    return [piece.strip() for piece in entry.split(",") if piece.strip()]


def audit(kb: Path) -> dict:
    """Both checks over every article in ``kb``, as one report."""
    report: dict = {
        "kb": str(kb),
        "articles": 0,
        "comma_packed": {"entries": 0, "articles": []},
        "duplicated_paths": {"occurrences": 0, "articles": []},
        "unreachable_frontmatter": [],
        "delimiter_not_at_byte_0": [],
        "unparseable_frontmatter": [],
        "without_sources": [],
    }

    for path in _articles(kb):
        rel = path.relative_to(kb).as_posix()
        report["articles"] += 1
        content = path.read_text(encoding="utf-8")

        # A BOM shifts the delimiter off byte 0 without hiding anything: every
        # reader in this package strips it. Reported apart so it cannot be
        # mistaken for the defect the seven articles carry.
        if content.startswith(_BOM):
            report["delimiter_not_at_byte_0"].append(rel)
            content = content[len(_BOM):]

        split = split_frontmatter(content)
        if split is None:
            reason = ("unclosed_block"
                      if content.split("\n", 1)[0].strip() == "---"
                      else "no_leading_delimiter")
            report["unreachable_frontmatter"].append({"article": rel,
                                                      "reason": reason})
            continue

        try:
            loaded = yaml.safe_load(split[0])
        except (yaml.YAMLError, ValueError, OverflowError):
            report["unparseable_frontmatter"].append(rel)
            continue
        if not isinstance(loaded, dict):
            report["unparseable_frontmatter"].append(rel)
            continue

        entries = _entries(loaded.get("sources"))
        if entries is None:
            report["without_sources"].append(rel)
            continue

        packed = sum(1 for entry in entries if len(_paths(entry)) > 1)
        if packed:
            report["comma_packed"]["entries"] += packed
            report["comma_packed"]["articles"].append(rel)

        paths = [p for entry in entries for p in _paths(entry)]
        extra = len(paths) - len(set(paths))
        if extra:
            report["duplicated_paths"]["occurrences"] += extra
            report["duplicated_paths"]["articles"].append(rel)

    return report


def failed(report: dict) -> bool:
    """True when the run being audited carries one of the defects.

    ``without_sources`` and ``delimiter_not_at_byte_0`` are recorded and do not
    fail: an article can legitimately have no sources yet, and a BOM costs no
    reader its keys.
    """
    return bool(report["comma_packed"]["entries"]
                or report["duplicated_paths"]["occurrences"]
                or report["unreachable_frontmatter"]
                or report["unparseable_frontmatter"])


def summary(report: dict) -> str:
    packed = report["comma_packed"]
    dup = report["duplicated_paths"]
    return (f"{report['articles']} articles: "
            f"{packed['entries']} comma-packed entries in "
            f"{len(packed['articles'])}, "
            f"{dup['occurrences']} duplicated paths in {len(dup['articles'])}, "
            f"{len(report['unreachable_frontmatter'])} with unreachable "
            f"frontmatter, "
            f"{len(report['unparseable_frontmatter'])} unparseable, "
            f"{len(report['without_sources'])} without sources")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kb", required=True, help="the KB to audit")
    parser.add_argument("--out", help="write the full report here as JSON")
    args = parser.parse_args(argv)

    report = audit(Path(args.kb))
    print(summary(report))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False,
                                             indent=2) + "\n",
                                  encoding="utf-8")
    return 1 if failed(report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
