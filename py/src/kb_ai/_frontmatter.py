"""Split a leading YAML frontmatter block from a markdown body.

The delimiter is a line that is exactly ``---``. Every reader in this package
used to do ``content.split("---", 2)`` instead, which splits on the first three
dashes *anywhere*: a frontmatter value containing ``---`` -- a raw filename like
``meeting---part-2.md``, or a horizontal rule in a summary -- was cut in half,
silently losing the rest of that value, every key after it, and leaking the
remains into the body.

``read_document_frontmatter`` layers the looser contract a *raw document* gets on
top of that split. It lived in storage.index while the catalog was its only
reader; the write phase reads a document's date at compose time (supersession
spec RT6, D4), and duplicating the skip rules is how the two would drift.
"""
from __future__ import annotations

import re

import yaml

_DELIM = "---"

# HTML comments occupying the start of a raw document, blank lines included, so
# what follows them starts at line 0 for split_frontmatter. Repeated, because
# re-ingesting a file that distill already ingested stacks a second comment above
# the first. DOTALL because one comment may span lines: it holds a path, and a
# POSIX filename is allowed to contain a newline.
#
# Blank lines are consumed, a non-blank line's own indentation is not, so what
# reaches split_frontmatter is byte-for-byte what follows the comments.
_LEADING_COMMENTS_RE = re.compile(
    r"\A(?:<!--.*?-->[ \t]*\r?\n(?:[ \t]*\r?\n)*)+", re.DOTALL)

# The UTF-8 BOM a Windows editor leaves at the head of a file. It is an encoding
# artefact rather than content, and leaving it in front of the opening delimiter
# made a BOM'd document read as having no frontmatter at all -- which is worse
# than cosmetic: the Go submit writer asks this same question before deciding
# whether it may stamp the ingest clock, so a shadowed block let the clock
# overwrite a date the document had authored.
_BOM = "\ufeff"

# What safe_load raises on frontmatter nobody can parse. ValueError belongs here
# because the timestamp constructor is not YAML-aware about calendars: `date:
# 0000-01-01` is well-formed YAML that datetime refuses ("year 0 is out of
# range"), and it escaped yaml.YAMLError to take down the catalog for every
# document beside it. OverflowError is the same defect one release earlier:
# PyYAML 6.0 subtracted a timestamp's UTC offset instead of attaching it as
# tzinfo, so `0001-01-01T00:00:00+02:00` -- a date the submit route's year guard
# accepts -- overflowed datetime.min. uv.lock pins 6.0.3, where it does not, but
# pyproject allows >=6.0 and one word covers both.
_UNPARSEABLE = (yaml.YAMLError, ValueError, OverflowError)


def split_frontmatter(content: str) -> tuple[str, str] | None:
    """Return (frontmatter_text, body), or None when there is no complete block.

    None covers both shapes the callers treat as "no frontmatter": content that
    does not open with a delimiter line, and a block that is never closed.

    The closing delimiter is matched on ``rstrip()``, not ``strip()``, so an
    *indented* ``---`` does not close the block. PyYAML renders a string value
    containing a line that is exactly ``---`` as a multi-line quoted scalar whose
    continuation lines are indented by at least two spaces, and ``strip()`` read
    that continuation as the end of the frontmatter: the block was truncated
    mid-scalar, ``safe_load`` raised ScannerError, and every key after the
    truncation point was lost. ``rstrip()`` still tolerates trailing whitespace
    on a real delimiter -- the only case ``strip()`` was buying -- while rejecting
    an indented one, which is never a legitimate delimiter.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIM:
        return None
    for i in range(1, len(lines)):
        if lines[i].rstrip() == _DELIM:
            return "".join(lines[1:i]), "".join(lines[i + 1:])
    return None


def _opens_with_a_frontmatter_mapping(content: str) -> bool:
    """True when content opens with a complete frontmatter block holding a mapping."""
    split = split_frontmatter(content)
    if split is None:
        return False
    try:
        return isinstance(yaml.safe_load(split[0]), dict)
    except _UNPARSEABLE:
        return False


def read_document_frontmatter(content: str) -> tuple[dict, str]:
    """Split a raw document into (frontmatter, body), tolerating both absences.

    Unlike a wiki article, a raw document is not required to carry frontmatter --
    and a malformed one must not make the document unselectable, only unlabelled.
    So where update_markdown_index skips, this degrades to ({}, whole content).

    Leading HTML comments are skipped before parsing: ``distill`` prepends
    ``<!-- source: ... -->`` to every file it ingests (``distill.py:82``), which
    pushed each document's own frontmatter off line 0 and left the whole catalog
    without a date, without a source and titled by filename -- 0 of 108 lines
    carried a date on the reference KB. Skipped here rather than widened into
    split_frontmatter so only raw documents get the looser contract: extraction
    files and articles are written by this package and are always
    frontmatter-first, and a phantom delimiter on that path truncates a payload
    (see storage/extraction.py's B3a/B6a).

    The skip is adopted only when it reveals a mapping, because a comment above a
    horizontal rule would otherwise read the first paragraph as frontmatter and
    return a body missing everything above the second rule. Losing content is
    worse than the labels this recovers. Two bounds on that guard, both inherited
    from what a raw document already means here rather than introduced by the skip:
    a rule-delimited block whose own lines parse as a mapping (``From:``/``Date:``
    export headers) is consumed like frontmatter, exactly as it already is in a
    document that has no comment; and when no mapping is found the comments stay in
    the returned body, so a document with neither frontmatter nor an extraction can
    still show one as its first-paragraph summary.

    A leading BOM is dropped before any of that, from the returned body as well:
    it is an encoding artefact, not content, and every reader downstream of here
    would otherwise carry it into a summary or a title. ``ExtractTitle`` on the Go
    side has always done the same.

    A ``date`` here is whatever YAML resolved it to -- ``datetime.date`` for an ISO
    day, ``datetime.datetime`` for a stamp, ``str`` for anything unparseable, and
    ``None`` for a declared-but-empty key. Callers test the value, not the key.
    """
    content = content.removeprefix(_BOM)

    if not _opens_with_a_frontmatter_mapping(content):
        uncommented = _LEADING_COMMENTS_RE.sub("", content, count=1)
        if uncommented != content and _opens_with_a_frontmatter_mapping(uncommented):
            content = uncommented

    split = split_frontmatter(content)
    if split is None:
        return {}, content
    try:
        fm = yaml.safe_load(split[0])
    except _UNPARSEABLE:
        return {}, split[1]
    return (fm if isinstance(fm, dict) else {}), split[1]
