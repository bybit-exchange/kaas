"""A read-only check for names an article asserts that no source of it contains.

Issue #42. Compiling go-zero produced a `MiddlewaresConf` table with an `Auth`
field the framework does not declare and the real `Shedding` renamed `Shedder`,
plus a numbered "applied in this order" middleware chain that appeared in no
extraction at all. The list was 9 of 11 correct, which is the tell: content drawn
from the model's own knowledge of a popular framework rather than from the
material. At query time the fabricated prose beat the correct table in 5 of 5
samples, so this is worse than an omission -- it looks complete enough that nobody
goes looking for the extraction that lost the enumeration (#41).

The grounding constraint in core/merge.py asks the writer not to do it. This is
the part that can tell whether it stopped, and it works on a knowledge base
already on disk rather than only on the next compile.

Reports and never spends: no LLM call, no network, nothing rewritten. Same
contract as the two checks in derive/_status.py.

## What it can and cannot see

Every rule below trades recall for precision, because an operator who meets one
false positive in a 181-article report stops reading the list. That is a bias, not
a promise of a short report: on the reference knowledge base this reports 108
names, and most of them are sound -- see the measurement at the end. The bounds are
deliberate rather than pending:

- A candidate must be a *code span* or *shaped* like an identifier (an internal
  capital, an underscore, a qualifying dot). A bare `Auth` in a table cell is
  invisible to this check, being indistinguishable from the word "Auth" in a
  sentence. Bold does not qualify either: it is how a generated article labels an
  ordinary bullet, and trusting it reported `No`, `Note` and `Acquires`.
- Only table rows and list items are scanned -- the shapes that make a claim about
  a named thing. Fabrication inside a paragraph is out of scope.
- Fenced code blocks are skipped: quoted code is reformatted on the way into an
  article, so a name's absence from the extraction is weaker evidence there.
- Matching is case-insensitive, so a name whose letters appear in the material in
  any casing is treated as sourced.
- An article is skipped, not flagged, when any extraction it names is unreadable.
  Against a partial haystack every name from the missing document reads as
  fabricated, which is a report about the extraction layer (F3's job).

Set membership is the whole mechanism, which bounds what it can find. Of the two
instances in #42 it sees the first -- the invented `Auth`, and `Shedding` renamed
`Shedder` -- and cannot see the second by construction: every member of the
fabricated middleware chain was individually present in the material, and what was
wrong there was the *ordering* and the two omissions. Neither is a membership
question.

Measured against the 181-article go-zero knowledge base from the issue: 108 names
across 55 articles, both #42 field-table findings among them. Around four fifths of
the rest are real identifiers that the document contains and its extraction does
not, so they are true of what this checks and still not inventions -- that is #41
surfacing here, and a re-extract is the answer to both. Expect the ratio to invert
on a knowledge base extracted after #41.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import yaml

from kb_ai._fadvise import read_text_and_evict
from kb_ai._frontmatter import split_frontmatter
from kb_ai.storage import extraction as extraction_layer
from kb_ai.storage.store import KBStore

# The payload fields pooled into the haystack. The rest of the provenance header
# -- model, checksum, timestamps -- stays out, being about the extraction rather
# than about the document. Its `source` is the one exception, added separately by
# _source_tokens.
_PAYLOAD_FIELDS = ("summary", "topics", "concepts", "entities", "decisions",
                   "action_items", "claims", "enumerations")

_FENCE = re.compile(r"^\s*(```|~~~)")
_LIST_ITEM = re.compile(r"^([-*+]|\d+[.)])\s+")
_TABLE_SEPARATOR = re.compile(r"^[\s|:-]+$")

# A code span at the start of a cell or list item, bold wrapping allowed. This is
# the one markup that is the author saying "this is a name", so its content is
# accepted whatever its shape -- which is what makes a `Auth` visible when a bare
# Auth is not. Bold around it does not change that, and the shape occurs on 81
# lines of the go-zero knowledge base.
#
# Bold on its own deliberately does not qualify. It is how a generated article
# labels an ordinary bullet ("- **No torn reads**: ..."), so reading it as a name
# reported `No`, `Note`, `Acquires` and `Ben` -- about a quarter of the findings on
# that knowledge base. Unwrapped bold falls through to the shape rule below, where
# the `**` is stripped as trailing punctuation, so a **MaxConns** is still seen.
_CODE_SPAN = re.compile(r"^(?:\*\*|__)?`([^`]+)`")

# An identifier, possibly dotted.
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")

# A method's receiver group, which precedes the name it declares:
# `func (srv *Server) Start() error`. Dropped before scanning, or the reported
# name is the receiver variable.
_RECEIVER = re.compile(r"^\s*\([^)]*\)\s*")

# Tokens that lead a declaration or stand for a value, never the name of one. A
# code span usually holds the whole declaration, so the first identifier in
# `func NewServer(c RestConf) *Server` is the keyword and not what the row is
# about.
#
# Statement and declaration keywords only, deliberately no type names: `error`,
# `string` and `int` are all plausible names of something a document declares, and
# excluding them would silence a real finding to tidy a hypothetical one.
#
# Matched case-sensitively, which is load-bearing: every keyword here is lowercase
# in the languages that produce these spans, while `Map`, `Type`, `Interface` and
# `Select` are all ordinary names of declared things. Folding case silenced
# `Map[K, V]` entirely. Python's capitalised literals are listed in their own right
# for the same reason.
_NOT_NAMES = frozenset({
    "func", "type", "const", "var", "package", "import", "struct", "interface",
    "map", "chan", "go", "defer", "range", "select", "switch", "if", "for",
    "def", "class", "async", "await", "return", "lambda",
    "let", "new", "export", "default", "public", "private", "protected", "static",
    "true", "false", "nil", "null", "none", "True", "False", "None",
})

# Trailing punctuation an author puts after a name: "MaxConns:", "Gunzip,",
# "Timeout()". Stripped before the membership test so the name is compared, not
# its context.
_TRAILING = ":,.;!?()[]{}\"'`*_—–-"


@dataclass(frozen=True)
class Unsourced:
    """One name an article states that no extraction behind it contains."""

    article: str
    name: str
    line: str


@dataclass(frozen=True)
class GroundingCheck:
    """Per-article verdicts plus the counts a caller wants to print."""

    checked: list[str] = field(default_factory=list)
    unsourced: list[Unsourced] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def flagged(self) -> list[str]:
        """The articles carrying at least one finding, in report order."""
        seen: list[str] = []
        for finding in self.unsourced:
            if finding.article not in seen:
                seen.append(finding.article)
        return seen

    def summary(self) -> str:
        # A run that checked nothing leads with that, not with "0 unsourced names".
        # Every article is skipped on a knowledge base whose extractions predate
        # schema_version 2, and the reassuring phrasing read as a clean bill.
        if not self.checked:
            if not self.skipped:
                return "no articles"
            return f"no articles could be checked ({len(self.skipped)} skipped)"
        return (f"{len(self.unsourced)} unsourced names in {len(self.flagged)} of "
                f"{len(self.checked)} articles ({len(self.skipped)} skipped)")


def named_items(body: str) -> list[tuple[str, str]]:
    """The named things a markdown body asserts, as (name, first line seen).

    Deduplicated on the name, because a field discussed in a table and again in a
    list is one claim and one finding.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    in_fence = False

    for raw_line in body.splitlines():
        if _FENCE.match(raw_line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        line = raw_line.strip()
        for candidate in _candidates(line):
            if candidate not in seen:
                seen.add(candidate)
                out.append((candidate, line))
    return out


def _candidates(line: str) -> list[str]:
    """The name a table row or list item leads with, or nothing."""
    if line.startswith("|"):
        if _TABLE_SEPARATOR.match(line):
            return []
        # The first non-empty cell only. In a table of named things that column
        # holds the name and the rest describe it, so scanning further would read
        # prose about the name as more names.
        cells = (c.strip() for c in line.strip("|").split("|"))
        return _name_of(next((c for c in cells if c), ""))

    item = _LIST_ITEM.match(line)
    if item:
        return _name_of(line[item.end():].strip())
    return []


def _name_of(text: str) -> list[str]:
    """The leading name of a cell or list item, as a 0- or 1-element list."""
    if text.startswith("[["):
        # A wikilink names another article, not something a source declared.
        return []

    code = _CODE_SPAN.match(text)
    if code:
        name = _code_name(code.group(1))
        return [name] if _is_name(name) else []

    # Everything else, bold included, is prose until it looks like an identifier.
    token = text.split()[0].strip(_TRAILING) if text.split() else ""
    if _is_name(token) and _has_identifier_shape(token):
        return [token]
    return []


def _code_name(span: str) -> str:
    """The name a code span is about: its first identifier that is not a keyword.

    Scanned as identifier runs rather than split on whitespace. A signature has no
    space before its parenthesis -- `Set(val bool)` splits into `Set(val`, a token
    that by construction appears in no extraction, which is how one line came to
    account for 182 of 428 findings on the go-zero knowledge base.
    """
    if "/" in span:
        # A path, not a declaration. `/usr/local/bin/myservice` would otherwise be
        # reported as `usr`, which an operator cannot trace back to anything.
        return ""

    first = _IDENTIFIER.search(span)
    if first and first.group() in _NOT_NAMES:
        # Only directly after a leading keyword can a parenthesised group precede
        # the name, so the receiver is stripped here rather than from every span:
        # `Set(val bool)` must keep its own first group. Testing only the *first*
        # identifier matters too -- scanning for any keyword would cut
        # `NewMap(m map[string]int)` at `map` and report `string`.
        span = _RECEIVER.sub("", span[first.end():], count=1)

    for match in _IDENTIFIER.finditer(span):
        token = match.group()
        if token not in _NOT_NAMES:
            return token
    return ""


def _is_name(token: str) -> bool:
    """Shared floor for code-span and bare candidates."""
    if len(token) < 2:
        return False
    if not any(c.isalpha() for c in token):
        return False
    # "1000", "30s", "2.5x": a magnitude, not a name.
    return not re.fullmatch(r"[\d.,]+[A-Za-z]{0,2}", token)


def _has_identifier_shape(token: str) -> bool:
    """Whether an *unmarked* token is one an author meant as an identifier.

    An internal capital, an underscore or a dot. Not a bare capitalised word: that
    rule is what keeps a prose table ("| Request exceeds the limit | ... |") from
    reporting a finding on every row, at the cost of missing a bare `Auth`.

    A dot only counts when both sides of it are more than one character, so `e.g`
    and `i.e` do not read as qualified names while `rest.Config` does.
    """
    if not _IDENTIFIER.fullmatch(token):
        return False
    # No _NOT_NAMES check here: every entry is a lowercase word with no underscore
    # or dot, so the shape rule below already rejects all of them. The set exists
    # for _code_name, where shape is not consulted.
    if "_" in token or any(c.isupper() for c in token[1:]):
        return True
    return "." in token and all(len(part) > 1 for part in token.split("."))


def check_grounding(kb_dir: str) -> GroundingCheck:
    """Compare every article's named items against the extractions behind it."""
    store = KBStore(kb_dir, read_only=True)
    checked: list[str] = []
    unsourced: list[Unsourced] = []
    skipped: list[tuple[str, str]] = []

    if not store.wiki_dir.is_dir():
        return GroundingCheck()

    for path in sorted(store.wiki_dir.rglob("*.md")):
        if path.name.startswith("."):
            continue
        rel_path = str(path.relative_to(store.base_dir))
        try:
            text = read_text_and_evict(path)
        except OSError as e:
            skipped.append((rel_path, f"unreadable: {e}"))
            continue

        split = split_frontmatter(text)
        if split is None:
            skipped.append((rel_path, "no complete YAML frontmatter block"))
            continue

        sources, reason = _sources(split[0])
        if not sources:
            skipped.append((rel_path, reason))
            continue

        haystack, unreadable = _source_text(store, sources)
        if unreadable:
            skipped.append((rel_path, "; ".join(unreadable)))
            continue

        checked.append(rel_path)
        for name, line in named_items(split[1]):
            if not _is_sourced(name, haystack):
                unsourced.append(Unsourced(article=rel_path, name=name, line=line))

    return GroundingCheck(checked=checked, unsourced=unsourced, skipped=skipped)


def _sources(frontmatter_text: str) -> tuple[list[str], str]:
    """The raw documents an article names, or ([], reason).

    Each item is split on commas, because one item can still name several
    documents. Every current write path emits one item per source, but the
    rewrite path's frontmatter is written by the model rather than by us, and an
    article compiled before per-source blocks existed was handed ", ".join(rels)
    as a single source string.
    """
    try:
        header = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as e:
        return [], f"invalid frontmatter YAML: {e}"
    if not isinstance(header, dict):
        return [], "frontmatter is not a mapping"

    value = header.get("sources")
    items = value if isinstance(value, list) else [value] if value else []
    out: list[str] = []
    for item in items:
        for part in str(item).split(","):
            part = part.strip()
            if part and part not in out:
                out.append(part)
    return (out, "") if out else ([], "frontmatter names no sources")


def _source_text(store: KBStore, sources: list[str]) -> tuple[str, list[str]]:
    """The pooled payload of every extraction behind an article.

    Returns (haystack, unreadable reasons). A non-empty reason list means the
    article cannot be checked at all rather than checked against what loaded.
    """
    parts: list[str] = []
    unreadable: list[str] = []
    for source in sources:
        stored, reason = extraction_layer.load(store, source)
        if stored is None:
            unreadable.append(f"{source}: {reason}")
            continue
        parts.append(json.dumps(
            {name: getattr(stored.extraction, name) for name in _PAYLOAD_FIELDS},
            ensure_ascii=False))
        parts.append(_source_tokens(stored.provenance.source))
    return "\n".join(parts), unreadable


def _source_tokens(source: str) -> str:
    """A raw document's path, plus the document's own filename as a token.

    distill flattens a document's original path with "__" (distill.py:53), so
    `rsa.go` inside raw/go-zero__core__codec__rsa.go.md is preceded by an
    underscore -- a word character, which the boundary in _is_sourced rejects.
    Recovering the last segment is what lets an article cite the file it was
    composed from.

    The directories above it are deliberately not recovered. Every segment would
    make `auth` a token for anything under .../auth/..., which would source an
    invented `Auth` -- #42's own name -- from the path alone. Restricting this to
    the filename changes no verdict on the reference knowledge base.
    """
    return source + " " + source.rsplit("__", 1)[-1]


def _is_sourced(name: str, haystack: str) -> bool:
    """Whether the material names this thing.

    Word-bounded so `Shedder` does not match `Shedding`, and case-insensitive
    because a name whose letters appear in the material in any casing is not
    evidence that the writer invented it. \\b is placed by hand rather than via
    \\b...\\b: a name may end in a non-word character, where \\b would demand a
    word character after it and never match.

    A dot is *not* excluded from either boundary, so a bare `Config` is sourced by
    a `rest.Config` in the material. Excluding it would make an ordinary
    abbreviation look like #42's rename shape, and the two need different verdicts.

    That leniency runs both ways: a qualified `syncx.Limit` is sourced when the
    material names `syncx` and names `Limit`, even if it never joins them. An
    article that qualifies a name is being more precise than its source, not
    inventing something, and twelve findings on the go-zero knowledge base were
    exactly that before this branch existed. Every segment has to be present, so a
    `syncx.Auth` cannot launder `Auth` through a package name the material happens
    to mention.
    """
    if _matches(name, haystack):
        return True
    return "." in name and all(_matches(part, haystack)
                               for part in name.split("."))


def _matches(name: str, haystack: str) -> bool:
    pattern = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
    return re.search(pattern, haystack, re.IGNORECASE) is not None
