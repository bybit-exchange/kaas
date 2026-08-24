"""Which raw documents are versions of one another (supersession spec RP3, RP4).

Shape B lineage: a document ingested twice as v1 and v2 under two Lark documents,
so the ``id`` differs and only the title says they are the same thing. Shape A --
one document re-fetched after an edit, same ``id`` -- is not this module's
business; the revised report already names those articles (RP2).

**This never reaches a prompt (RP5).** The rule is a heuristic over titles, and a
heuristic that steers what gets written is the thing D2's gate on build path B
exists to refuse. It informs an operator, who can read the article and decide. So
nothing here is imported by ``core.merge``, and the report is built after the last
write op rather than beside the payload -- there is no code path from a group to a
model.

The rule was validated on a 996-document corpus before it was code, which is why
it carries two exclusions that look arbitrary until you meet the data, and why the
marker is deliberately narrower than "a trailing number".

What the rule cannot do, stated because the report's usefulness depends on it: a
recurring meeting series has one fixed title and a new ``id`` per occurrence, so it
is indistinguishable from a version chain by title alone. Of the 41 (article, group)
pairs the rule reports on the reference corpus, 37 are recurring series and 4 are
real version chains -- the ``versioned`` flag is what separates them, and it is
reported rather than filtered on, because three of the six shape-B fixture positives
carry no marker either. Nothing cheaper works: comparing the members' extracted
claims fires on 35 of the 35 checkable pairs at every threshold from 0.55 up (median
best-match similarity 0.47 on real version pairs against 0.36 on recurring series --
no separation), and "the later member asserts fewer claims" filters out P6, the one
adjudicated success.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

import yaml

from kb_ai._frontmatter import as_day, read_document_frontmatter, split_frontmatter

# A trailing version marker: `v1.7`, `V15`, `-v2`, `v1.0.0`, `(v3)`, `（V3）`.
#
# The `v` is required. Stripping a bare trailing number would collapse "Cost
# Report 2025" and "Cost Report 2026" into one chain, and an operator cannot tell
# that error from a real group -- whereas failing to strip one leaves two titles
# that simply do not match, which is the state the report was in before it existed.
#
# Any number of dotted components, and either bracket form, because the corpus holds
# both `(v3)` and `v1.0.0` -- and the script that first measured this rule matched
# the bracketed one while missing the three-part one, so it silently found one group
# fewer than the data has.
_MARKER_RE = re.compile(r"[\s\-–—_]*[（(\[]?[vV]\d+(?:\.\d+)*[)）\]]?\s*$")


@dataclass(frozen=True)
class DocumentFacts:
    """What lineage needs from one raw document's frontmatter.

    A value object rather than a store read, so the rule is a pure function of
    facts: the exclusions are the part that has to be pinned by tests, and neither
    of them is about I/O.
    """

    rel_path: str
    title: str = ""
    doc_id: str = ""
    source: str = ""
    date: _date | None = None


@dataclass(frozen=True)
class LineageGroup:
    """Documents that look like versions of one thing, oldest member first."""

    title: str
    source: str
    members: tuple[str, ...]
    # True when some member's title carried a version marker. Not a filter: it is
    # the operator's triage key, since an unmarked group is as likely to be a
    # recurring meeting series as a version chain.
    versioned: bool


def strip_version_marker(title: str) -> str:
    """The title with its trailing version marker and stray whitespace removed."""
    return _MARKER_RE.sub("", " ".join(str(title).split())).strip()


def read_document_facts(read_raw: Callable[[str], str], rel_path: str) -> DocumentFacts:
    """Read one document's lineage facts, degrading to bare facts on any failure.

    Same treatment a missing date gets at write time: a document that cannot be
    read contributes no title, so it joins no group. An unreadable document must
    not fail the compile it is reported at the end of.
    """
    try:
        content = read_raw(rel_path)
    except (OSError, ValueError):
        return DocumentFacts(rel_path=rel_path)
    frontmatter, _body = read_document_frontmatter(content)
    return DocumentFacts(
        rel_path=rel_path,
        title=str(frontmatter.get("title") or ""),
        doc_id=str(frontmatter.get("id") or ""),
        source=str(frontmatter.get("source") or ""),
        date=as_day(frontmatter.get("date")),
    )


# Where a KB keeps its person pages. Two names because the category is named
# `person` by DEFAULT_CATEGORIES and `people` by the stub generator's own scan
# (core/people.py), and a KB converted from an older layout has the plural one.
_PERSON_DIRS = ("person", "people")


def known_person_names(wiki_dir: Path, people_cfg: Iterable[dict] = ()) -> set[str]:
    """The names a document title must not simply be, for the RP4 exclusion.

    Two sources, because neither alone covers the run that needs it. The person
    pages on disk are what the reference corpus had and cost one read each; the
    configured allowlist is what a *first* compile has, since the stubs are
    generated by a later phase and a one-to-one ingested today would otherwise be
    read as a version chain until the next run.

    Aliases count as names: an allowlist entry exists precisely because the same
    person is written several ways, and a meeting titled with the alias is the same
    recurring one-to-one as one titled with the canonical name.
    """
    names: set[str] = set()
    for person in people_cfg or ():
        if not isinstance(person, dict):
            continue
        for name in (person.get("canonical"), *(person.get("aliases") or [])):
            if name:
                names.add(str(name))

    for directory in _PERSON_DIRS:
        for page in sorted((wiki_dir / directory).glob("*.md")):
            names.add(page.stem.replace("-", " "))
            split = split_frontmatter(page.read_text(encoding="utf-8", errors="replace"))
            if split is None:
                continue
            try:
                fm = yaml.safe_load(split[0])
            except (yaml.YAMLError, ValueError, OverflowError):
                continue
            if isinstance(fm, dict) and fm.get("title"):
                names.add(str(fm["title"]))
    return names


def lineage_groups(documents: Iterable[DocumentFacts],
                   person_names: Iterable[str] = ()) -> list[LineageGroup]:
    """Group documents that share a title modulo a version marker (RP4).

    Two exclusions, both forced out by the corpus rather than chosen:

    - **Cross-source collisions.** ``raw/docs/`` and ``raw/meetings/`` hold a design
      document and the recording of the meeting that discussed it under one title.
      Neither supersedes the other, so ``source`` is part of the grouping key. That
      excludes the pairing without excluding the title: two recordings of one
      meeting share a source and stay a group.
    - **Person names.** A recurring one-to-one is titled with the person's name, so
      three meetings called ``Cara`` collide under the title rule while being
      unrelated conversations. A title that *is* a person's name groups with
      nothing; one that merely contains it is untouched.
    """
    excluded = {str(name).casefold().strip() for name in person_names}
    excluded = {strip_version_marker(name).casefold() for name in excluded if name}

    by_key: dict[tuple[str, str], list[DocumentFacts]] = {}
    for facts in documents:
        title = strip_version_marker(facts.title)
        if not title or title.casefold() in excluded:
            continue
        by_key.setdefault((title.casefold(), facts.source), []).append(facts)

    groups: list[LineageGroup] = []
    for (_key, source), members in by_key.items():
        if len(members) < 2:
            continue
        # Two ingests of one document are shape A however many files they occupy,
        # and shape A is the revised report's subject (RP2). One repeated id among
        # three members still leaves a version pair, so this counts distinct ids
        # rather than rejecting any repeat.
        if len({m.doc_id for m in members}) < 2:
            continue
        ordered = _oldest_first(members)
        groups.append(LineageGroup(
            title=strip_version_marker(ordered[0].title),
            source=source,
            members=tuple(m.rel_path for m in ordered),
            versioned=any(strip_version_marker(m.title) != " ".join(m.title.split())
                          for m in members),
        ))
    # Sorted so two runs over one KB report the same thing in the same order; the
    # log is read by a person and diffed by nobody, but a stable order is what
    # makes it diffable at all.
    return sorted(groups, key=lambda g: (g.title.casefold(), g.source))


def _oldest_first(members: list[DocumentFacts]) -> list[DocumentFacts]:
    """Dated members oldest first, then undated ones in path order (WP5's order).

    The same order the writer's source blocks run in, so the report and the payload
    cannot disagree about which member is the later one.
    """
    dated = sorted((m for m in members if m.date is not None),
                   key=lambda m: (m.date, m.rel_path))
    undated = sorted((m for m in members if m.date is None), key=lambda m: m.rel_path)
    return dated + undated
