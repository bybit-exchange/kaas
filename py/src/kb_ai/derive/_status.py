"""Two read-only checks over a knowledge base's extraction layer (spec F3, F5).

They answer different questions, and both are needed:

- ``check_extractions`` (F3) asks "does this KB's extraction match its own
  document" -- internal consistency. It is the read-side counterpart of the guard
  copy_documents applies, and it is what makes keying extractions by path safe.
- ``check_parent`` (F5) asks "has the parent's version of this document moved
  since I was derived" -- divergence from the source. A derived KB can pass F3 and
  still be months behind.

Both report and never spend: no LLM call, no network, and nothing is rewritten.
Refreshing a derived KB when its source changes stays out of scope, and spending
money on a read path is excluded by design.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from kb_ai._fadvise import read_text_and_evict
from kb_ai.derive._layout import MANIFEST_NAME, read_manifest
from kb_ai.storage import extraction
from kb_ai.storage.store import KBStore, _compute_checksum

# check_parent verdicts.
IN_SYNC = "in_sync"
CHANGED_IN_PARENT = "changed_in_parent"
GONE_FROM_PARENT = "gone_from_parent"
UNKNOWN = "unknown"

# check_extractions verdicts.
MATCHES = "matches"
MISSING = "missing"
MISMATCHED = "mismatched"


@dataclass(frozen=True)
class ExtractionCheck:
    """Per-document verdicts plus the counts a caller wants to print."""

    matches: list[str] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    mismatched: list[tuple[str, str]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.matches) + len(self.missing) + len(self.mismatched)

    def summary(self) -> str:
        return (f"{len(self.matches)} match, {len(self.missing)} missing, "
                f"{len(self.mismatched)} mismatched (of {self.total} documents)")


@dataclass(frozen=True)
class ParentCheck:
    """How a derived KB stands against the parent it was derived from."""

    source_kb: str = ""
    verdict: str = UNKNOWN
    in_sync: list[str] = field(default_factory=list)
    changed_in_parent: list[str] = field(default_factory=list)
    gone_from_parent: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def total(self) -> int:
        return (len(self.in_sync) + len(self.changed_in_parent)
                + len(self.gone_from_parent))

    def summary(self) -> str:
        if self.verdict == UNKNOWN:
            return f"unknown: {self.reason}"
        return (f"{len(self.in_sync)} in sync, {len(self.changed_in_parent)} changed "
                f"in parent, {len(self.gone_from_parent)} gone from parent "
                f"(of {self.total} copied documents)")


def check_extractions(kb_dir: str) -> ExtractionCheck:
    """Compare every document's extraction against the document's own bytes (F3).

    A missing extraction is not a fault -- the next compile pays for it once -- but
    a mismatched one means the file on disk describes different text than the
    document beside it, which is exactly what a content-addressed filename used to
    make impossible.
    """
    store = KBStore(kb_dir, read_only=True)
    matches: list[str] = []
    missing: list[tuple[str, str]] = []
    mismatched: list[tuple[str, str]] = []

    if not store.raw_dir.is_dir():
        return ExtractionCheck()

    for path in store._iter_raw_paths():
        rel_path = str(path.relative_to(store.base_dir))
        header, reason = extraction.load_header(store, rel_path)
        if header is None:
            missing.append((rel_path, reason))
            continue
        recorded = header.get("source_checksum")
        actual = _compute_checksum(read_text_and_evict(path))
        if recorded == actual:
            matches.append(rel_path)
        else:
            mismatched.append(
                (rel_path, f"extraction records {recorded!r}, document hashes to "
                           f"{actual!r}"))
    return ExtractionCheck(matches=matches, missing=missing, mismatched=mismatched)


def check_parent(derived_dir: str) -> ParentCheck:
    """Classify each copied document against the parent's current raw/ (F5).

    The write side already exists: the manifest carries a documents array of
    {rel_path, checksum, size_bytes} per copied document. This is the read side,
    and it rehashes the parent's raw/ rather than trusting anything.

    Degrades to UNKNOWN rather than failing when the parent is unreachable:
    source_kb is stored as an absolute path, and derive is built for parents that
    may be read-only or belong to someone else.
    """
    manifest = read_manifest(Path(derived_dir))
    if not manifest:
        return ParentCheck(reason=f"no readable {MANIFEST_NAME} in {derived_dir}")

    source_kb = str(manifest.get("source_kb") or "")
    if not source_kb:
        return ParentCheck(reason="manifest records no source_kb")

    parent = Path(source_kb).expanduser()
    if not (parent / "raw").is_dir():
        return ParentCheck(source_kb=source_kb,
                           reason=f"parent {source_kb} has no readable raw/")

    parent_store = KBStore(source_kb, read_only=True)
    try:
        current = {meta.rel_path: meta.checksum
                   for meta in parent_store.iter_raw_file_meta()}
    except OSError as e:
        return ParentCheck(source_kb=source_kb,
                           reason=f"parent {source_kb} unreadable: {e}")

    in_sync: list[str] = []
    changed: list[str] = []
    gone: list[str] = []
    for entry in manifest.get("documents") or []:
        rel_path = str(entry.get("rel_path") or "")
        if not rel_path:
            continue
        if rel_path not in current:
            gone.append(rel_path)
        elif current[rel_path] == entry.get("checksum"):
            in_sync.append(rel_path)
        else:
            changed.append(rel_path)

    verdict = IN_SYNC if not changed and not gone else CHANGED_IN_PARENT
    return ParentCheck(source_kb=source_kb, verdict=verdict, in_sync=in_sync,
                       changed_in_parent=changed, gone_from_parent=gone)
