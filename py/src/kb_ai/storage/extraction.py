"""The extraction layer: one markdown file per raw document, under extraction/.

Implements section A (layout) and section B (file contents and provenance) of
docs/features/extraction-layer/spec.md, plus C1's single serializer.

The layer exists because extraction is the source of truth for article prose and
for document selection, while it used to be stored in a directory named
".extract-cache". Giving it a name buys three things: a path that mirrors raw/ so
the mapping is readable off the filename, a provenance header that turns "is this
stale, and why" into a field comparison, and a file a maintainer can open in an
editor while tuning the extract prompt.

Format: YAML frontmatter carries the provenance plus the two flat payload fields
(summary, topics) and the per-section counts; the body carries the six
object-list fields as ``## Heading`` sections whose content is ``yaml.safe_dump``
of that field's list. Both halves go through safe_dump, so quoting and escaping
are PyYAML's responsibility rather than hand-written.

Two line-oriented delimiters survive a value that contains a newline only because
both are closed explicitly: a heading is recognised at column 0 only, and
split_frontmatter closes on rstrip() rather than strip(). See B3a and B6a.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

from kb_ai._errors import ExtractionFileError
from kb_ai._frontmatter import split_frontmatter
from kb_ai.core.extract import (
    STRATEGY_CHUNKED,
    STRATEGY_SUMMARIZE,
    ExtractionResult,
    extract_prompt_version,
)
from kb_ai.storage.store import KBStore

# Bumped when the file shape changes incompatibly. Recorded in every file so a
# future reader can tell what it is looking at, and enforced by parse(): any other
# value is refused rather than read as this one.
#
# 2 (issue #41) added the enumerations section. Dropping `connections` in
# 2026-08-08 left this at 1 because a removal reads in both directions; a
# *required* new section does not. Left unbumped, both directions would still have
# refused -- a v1 file on the missing ``## Enumerations``, a v2 file read by v1
# code on its own counts check over the extra key -- so what the bump buys is the
# message: the version check runs first (see parse()), so a reader of either file
# is told the format differs rather than that the payload is corrupt.
SCHEMA_VERSION = 2

# The object-list payload fields, in the order their sections are written.
# Pinned rather than derived from dict iteration, because section order is part
# of the byte-identity the two ingestion routes have to agree on (C2).
BODY_FIELDS = ("concepts", "entities", "decisions", "action_items", "claims",
               "enumerations")

# Flat payload fields that live in the frontmatter, so a reader doing catalog or
# topic-filter work parses the frontmatter only and never the body (B7).
FRONTMATTER_PAYLOAD_FIELDS = ("summary", "topics")

# STRATEGY_CHUNKED and STRATEGY_SUMMARIZE are imported above rather than defined
# here: the router in core/extract.py decides which one runs and this module
# records it, so two bindings would have to agree by convention. Every existing
# `extraction.STRATEGY_CHUNKED` reference keeps working through the import.

# allow_unicode keeps CJK unescaped -- the body is where the CJK-dense values
# live, such as a concept's definition. width bounds every line so PyYAML cannot
# fold a long value, which corrupts silently. default_flow_style keeps lists
# block-style so one item reads as one entry. Matches core/people.py.
_DUMP_OPTS = {"allow_unicode": True, "default_flow_style": False, "width": 10 ** 6}

_HEADING_PREFIX = "## "


@dataclass(frozen=True)
class Provenance:
    """Where one extraction came from (B1).

    Every field is compared by staleness() except source, extracted_at and
    schema_version: source is the key, extracted_at is the audit trail, and
    schema_version records the format rather than the inputs.
    """

    source: str
    source_checksum: str
    extract_model: str
    extract_strategy: str
    prompt_version: str
    extracted_at: str = ""
    schema_version: int = SCHEMA_VERSION
    # Recorded on the summarize path only, where a second model drives the
    # per-chunk pass and the L2 merge. Empty on the chunked path, where no such
    # call happens (B15).
    summarize_model: str = ""


@dataclass(frozen=True)
class StoredExtraction:
    """One extraction file, parsed."""

    provenance: Provenance
    extraction: ExtractionResult


def _now_iso() -> str:
    """UTC with an offset, seconds precision.

    Not naive local time: derived KBs get handed to other machines, and derive
    copies with shutil.copyfile, which does not preserve mtime. The field in the
    file is the only durable answer to "when was this extracted".

    A module-level helper rather than a persist() parameter, so the one caller
    that needs a fixed timestamp (the parity test) monkeypatches it instead of
    the API carrying test scaffolding.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def current_prompt_version() -> str:
    """The prompt_version persist() will record for a new extraction.

    One binding for both sides of the comparison: the writer records what this
    returns and the extraction gate compares against it, so they cannot drift.
    Raises PromptError (NoActivePromptError) when a prompt file is missing or
    invalid -- never a fallback, since "fresh" would keep serving extractions
    produced by the previous prompt.
    """
    return extract_prompt_version()


def heading_for(field_name: str) -> str:
    """Section heading for a body field. Pure function of the name, no table."""
    return field_name.replace("_", " ").title()


def field_for(heading: str) -> str:
    """Inverse of heading_for. Exact, because every field name is lowercase."""
    return heading.strip().lower().replace(" ", "_")


def serialize(provenance: Provenance, extraction: ExtractionResult) -> str:
    """Render one extraction file (B1-B5).

    topics is sorted here: it is built with list(set(...)), and Python randomises
    string hashing per process, so the same content otherwise yields a different
    element order on every run. Sorting is what makes re-extracting an unchanged
    document produce the same lines as before, so a diff between two extraction
    files shows only what changed.
    """
    header: dict = {
        "source": provenance.source,
        "source_checksum": provenance.source_checksum,
        "extract_model": provenance.extract_model,
        "extract_strategy": provenance.extract_strategy,
        "prompt_version": provenance.prompt_version,
        "extracted_at": provenance.extracted_at,
        "schema_version": provenance.schema_version,
        "summary": extraction.summary,
        "topics": _sorted(extraction.topics),
        "counts": {name: len(getattr(extraction, name)) for name in BODY_FIELDS},
    }
    if provenance.summarize_model:
        header["summarize_model"] = provenance.summarize_model

    parts = ["---\n", yaml.safe_dump(header, **_DUMP_OPTS), "---\n"]
    for name in BODY_FIELDS:
        parts.append(f"\n{_HEADING_PREFIX}{heading_for(name)}\n\n")
        parts.append(yaml.safe_dump(list(getattr(extraction, name)), **_DUMP_OPTS))
    return "".join(parts)


def _sorted(values: list) -> list:
    """Stable order for a set-derived list of tags, tolerating non-strings.

    LLM output is not typed, so a topic list can hold a dict; key=str keeps the
    sort total instead of raising TypeError on mixed types.
    """
    return sorted(values, key=str)


def parse(text: str) -> StoredExtraction:
    """Read one extraction file back, or raise ExtractionFileError.

    Never returns a partially-populated result: a file whose section counts
    disagree with its header is corrupt, not empty (B4). Without that check a
    mistyped ``## Claims`` heading would silently yield zero claims and a thinner
    article, with no error anywhere.
    """
    split = split_frontmatter(text)
    if split is None:
        raise ExtractionFileError("no complete YAML frontmatter block")
    try:
        header = yaml.safe_load(split[0])
    except yaml.YAMLError as e:
        raise ExtractionFileError(f"invalid frontmatter YAML: {e}") from e
    if not isinstance(header, dict):
        raise ExtractionFileError("frontmatter is not a mapping")

    # Checked here rather than in staleness(), which compares inputs and would
    # have to call an unreadable format "fresh" or "stale" when it is neither.
    # Refusing the parse routes a format bump into load()'s absent branch, so a
    # v2 file read by v1 code re-extracts instead of composing an article from a
    # payload this code does not understand.
    version = header.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ExtractionFileError(
            f"unsupported schema_version: {version!r}, this code reads "
            f"{SCHEMA_VERSION}")

    sections = _split_sections(split[1])
    payload: dict[str, list] = {}
    for name in BODY_FIELDS:
        if name not in sections:
            raise ExtractionFileError(f"missing body section: {heading_for(name)}")
        payload[name] = _load_section(name, sections[name])

    counts = header.get("counts")
    actual = {name: len(payload[name]) for name in BODY_FIELDS}
    if counts != actual:
        raise ExtractionFileError(
            f"counts disagree with body: header={counts} body={actual}"
        )

    source = _as_str(header.get("source"))
    extraction = ExtractionResult(
        summary=_as_str(header.get("summary")),
        topics=list(header.get("topics") or []),
        # The CLI assigns source_path after extraction and the worker path from
        # source_ref; the parser populates it from the file's own `source`, so a
        # round-trip compares against an original whose source_path was set the
        # same way.
        source_path=source,
        **payload,
    )
    provenance = Provenance(
        source=source,
        source_checksum=_as_str(header.get("source_checksum")),
        extract_model=_as_str(header.get("extract_model")),
        extract_strategy=_as_str(header.get("extract_strategy")),
        prompt_version=_as_str(header.get("prompt_version")),
        extracted_at=_as_str(header.get("extracted_at")),
        schema_version=version,
        summarize_model=_as_str(header.get("summarize_model")),
    )
    return StoredExtraction(provenance=provenance, extraction=extraction)


def _as_str(value) -> str:
    return "" if value is None else str(value)


def _split_sections(body: str) -> dict[str, str]:
    """Locate the ``## `` sections of a body, keyed by field name.

    A heading is recognised at column 0 only -- ``line.startswith``, never
    ``line.strip().startswith``. This is load-bearing rather than stylistic:
    safe_dump renders a string containing a newline as a multi-line quoted
    scalar whose continuation lines are real physical lines indented by at least
    two spaces, so a value holding "\\n## Entities\\n" yields an indented
    ``## Entities``. A strip()-based scanner reads that as a phantom section and
    leaves the enclosing section an unterminated quoted scalar, which makes
    safe_load raise and the document re-extract on every compile forever.
    """
    out: dict[str, str] = {}
    current: str | None = None
    buffer: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.startswith(_HEADING_PREFIX):
            if current is not None:
                out[current] = "".join(buffer)
            current = field_for(line[len(_HEADING_PREFIX):])
            buffer = []
            continue
        buffer.append(line)
    if current is not None:
        out[current] = "".join(buffer)
    return out


def _load_section(name: str, text: str) -> list:
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ExtractionFileError(f"invalid YAML in section {name}: {e}") from e
    if value is None:
        # A blank section. Harmless when counts agrees it is empty, and caught by
        # the counts check when it does not.
        return []
    if not isinstance(value, list):
        raise ExtractionFileError(
            f"section {name} is {type(value).__name__}, expected a list"
        )
    return value


def persist(
    store: KBStore,
    raw_rel: str,
    extraction: ExtractionResult,
    *,
    source_checksum: str,
    extract_model: str,
    extract_strategy: str = STRATEGY_CHUNKED,
    summarize_model: str = "",
) -> tuple[Path, bool]:
    """Write one extraction file. The only writer, on both ingestion routes (C1).

    Returns (path, existed_before). The flag is what lets compile distinguish a
    first extraction from one that overwrote an existing file: those documents
    were revised, and both merge paths are additive, so their articles layered
    new content on top of what the previous version already contributed (C11).

    Atomic: temp file plus os.replace, so a crash mid-write cannot leave a file
    whose header disagrees with its payload. Not retried -- what actually fails
    is ENOSPC, EACCES or EROFS, none of which clears in milliseconds.

    extract_strategy records the strategy that *ran*, never "auto": the router
    resolves that on chunk count, and recording it would make the field useless.
    summarize_model is kept only on the summarize path, so staleness cannot mark a
    chunked extraction stale over a model that never touched it.
    """
    if store.read_only:
        raise PermissionError("KBStore is read-only")

    provenance = Provenance(
        source=raw_rel,
        source_checksum=source_checksum,
        extract_model=extract_model,
        extract_strategy=extract_strategy,
        summarize_model=(summarize_model if extract_strategy == STRATEGY_SUMMARIZE
                         else ""),
        prompt_version=current_prompt_version(),
        extracted_at=_now_iso(),
    )
    target = store.extraction_path(raw_rel)
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    # name + ".tmp" rather than with_suffix: a raw filename may hold several dots,
    # and with_suffix would replace the last one instead of appending.
    tmp = target.parent / (target.name + ".tmp")
    tmp.write_text(serialize(provenance, extraction), encoding="utf-8")
    os.replace(str(tmp), str(target))
    return target, existed


def load(store: KBStore, raw_rel: str) -> tuple[StoredExtraction | None, str]:
    """Read the extraction for a raw document.

    Returns (stored, "") on success and (None, reason) otherwise, with reason one
    of "missing", "unreadable: ...", "invalid: ...". Never an empty-but-valid
    result: composing an article from one would produce an article with no
    content and no error (B9).
    """
    text, reason = _read(store, raw_rel)
    if text is None:
        return None, reason
    try:
        return parse(text), ""
    except ExtractionFileError as e:
        return None, f"invalid: {e}"


def _read(store: KBStore, raw_rel: str) -> tuple[str | None, str]:
    """The file's text, or (None, reason) in load()'s reporting style."""
    try:
        path = store.extraction_path(raw_rel)
    except ValueError as e:
        return None, f"invalid: {e}"
    if not path.exists():
        return None, "missing"
    try:
        return path.read_text(encoding="utf-8"), ""
    except OSError as e:
        return None, f"unreadable: {e}"


def load_header(store: KBStore, raw_rel: str) -> tuple[dict | None, str]:
    """Read only an extraction file's frontmatter (B7).

    Everything selection needs -- the summary, topics and the whole provenance
    header -- lives there, and the body holds the object lists a catalog never
    looks at. Worth its own function rather than load(): the
    document catalog is rebuilt over every document in the KB on every compile,
    and the counts guard load() applies protects the write phase's payload, which
    is not what a catalog line reads.

    Same reporting contract as load(): (header, "") or (None, reason).
    """
    text, reason = _read(store, raw_rel)
    if text is None:
        return None, reason
    split = split_frontmatter(text)
    if split is None:
        return None, "invalid: no complete YAML frontmatter block"
    try:
        header = yaml.safe_load(split[0])
    except yaml.YAMLError as e:
        return None, f"invalid: invalid frontmatter YAML: {e}"
    if not isinstance(header, dict):
        return None, "invalid: frontmatter is not a mapping"
    return header, ""


def staleness(
    provenance: Provenance,
    *,
    source_checksum: str,
    extract_model: str,
    prompt_version: str,
    extract_strategy: str = STRATEGY_CHUNKED,
    summarize_model: str = "",
) -> str:
    """Why this extraction is stale, or "" when it is fresh (B10).

    A plain field comparison: no LLM call, no network, no special values and no
    exemptions. The comparison set is the fields the *recorded* strategy actually
    used -- four for chunked, five for summarize -- so a summarize_model change
    cannot mark a chunked extraction stale over a model that never touched it.

    prompt_version is passed in rather than computed here: the caller computes it
    once per run (it is a per-process constant) and can report the one failure
    mode, a missing or invalid prompt file, without this returning "fresh".
    """
    for name, recorded, current in (
        ("source_checksum", provenance.source_checksum, source_checksum),
        ("extract_model", provenance.extract_model, extract_model),
        ("extract_strategy", provenance.extract_strategy, extract_strategy),
        ("prompt_version", provenance.prompt_version, prompt_version),
    ):
        if recorded != current:
            return f"{name} changed: {recorded!r} -> {current!r}"
    if (provenance.extract_strategy == STRATEGY_SUMMARIZE
            and provenance.summarize_model != summarize_model):
        return (f"summarize_model changed: {provenance.summarize_model!r} -> "
                f"{summarize_model!r}")
    return ""
