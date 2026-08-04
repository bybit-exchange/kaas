"""Filesystem layout of a derived knowledge base (spec C1-C5, C7, E1, E2, E4, G4).

Owns every path decision: what a slug may be, where derived/<slug>/ lives, how
documents and their extract-cache entries are copied in, and how the provenance
manifest is read back. resolve_kb_dir() is the one read-path resolver shared by
MCP ask and the HTTP read handlers.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from kb_ai._errors import (
    DeriveError,
    InvalidSlugError,
    NestedDeriveError,
    SlugExistsError,
    UnknownDerivedKBError,
)
from kb_ai.derive._types import DocumentRef
from kb_ai.storage.store import KBStore

# One lower-case path segment, dash-separated, at most 40 chars. Validated
# lexically BEFORE any path is built, so a hostile slug never reaches the
# filesystem -- --force is a recursive delete driven by this string (C3, C4).
#
# Cross-language pair: slugRe in internal/kbpath/kbpath.go (Task 12) and
# slugFillerRe in internal/api/derive.go (Task 16) must match this pattern.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

MANIFEST_NAME = "manifest.json"
DERIVED_DIRNAME = "derived"
OFFTOPIC_DIRNAME = "_offtopic"

_SLUG_MAX = 40
# Spec E4: checksum is the first 16 hex digits of the content hash.
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{16}$")


def normalise_slug(topic: str) -> str:
    """Derive a slug from a topic string (C2).

    Lower-cased, non-alphanumeric runs collapsed to '-', trimmed, truncated to 40
    characters, then trimmed again -- truncation can land on a dash, which
    validate_slug rejects.
    """
    flat = re.sub(r"[^a-z0-9]+", "-", topic.lower())
    return flat.strip("-")[:_SLUG_MAX].strip("-")


def validate_slug(slug: str) -> None:
    """Raise InvalidSlugError unless slug is a single safe path segment (C3)."""
    if not slug or not SLUG_RE.fullmatch(slug):
        raise InvalidSlugError(
            f"invalid slug {slug!r}: expected 1-40 chars matching {SLUG_RE.pattern}"
        )


def assert_not_nested(source_kb: Path) -> None:
    """Refuse to derive from a derived knowledge base (C5).

    A derived KB is exactly '<parent>/derived/<slug>/' holding a manifest.json.
    Requiring the manifest keeps a real KB that merely happens to sit in a
    directory called 'derived' usable. The parent-name check is case-insensitive
    so a source KB at <root>/Derived/<slug> is also rejected on case-folding
    filesystems.
    """
    src = Path(source_kb).expanduser().resolve()
    if src.parent.name.lower() == DERIVED_DIRNAME and (src / MANIFEST_NAME).exists():
        raise NestedDeriveError(
            f"{src} is a derived knowledge base; nesting stops at one level"
        )


def derived_dir(source_kb: Path, slug: str) -> Path:
    """Path of derived/<slug>/ under source_kb. Assumes slug is already valid."""
    return Path(source_kb).expanduser().resolve() / DERIVED_DIRNAME / slug


def check_slug_available(source_kb: Path, slug: str, force: bool) -> None:
    """Raise SlugExistsError now if create() would later refuse (C4).

    Called before the first LLM call so a name clash costs nothing.
    """
    target = derived_dir(source_kb, slug)
    if not target.exists():
        return
    if not force:
        raise SlugExistsError(
            f"{target} already exists; pass --force to replace it"
        )
    manifest = read_manifest(target)
    if manifest.get("slug") != slug:
        # --force replaces a directory derive created. Refusing anything else is
        # what stops a mistyped --kb plus --force from being a data-loss bug.
        raise SlugExistsError(
            f"{target} exists but holds no {MANIFEST_NAME} naming slug {slug!r}; "
            "refusing to replace a directory this command did not create"
        )


def _safe_create_target(source_kb: Path, slug: str) -> Path:
    """Compute the derived target and require it to equal <kb>/derived/<slug> exactly.

    Resolves the filesystem entry at base / slug and compares it to the expected
    path.  Any symlink — whether planted at <kb>/derived/, at <kb>/derived/<slug>,
    or pointing to a dangling target — produces a resolved path that differs from
    the expected one, so all of these are rejected before rmtree or mkdir runs (C4):
    - symlink-outside:  <kb>/derived/<slug> → path outside <kb>/derived/
    - sibling-symlink:  <kb>/derived/<slug> → <kb>/derived/<other>
    - dangling-symlink: <kb>/derived/<slug> → nonexistent path
    - base-itself:      <kb>/derived/<slug> → <kb>/derived
    - base-outside:     <kb>/derived/ itself → outside path
    Raises InvalidSlugError on any mismatch.
    """
    kb_resolved = Path(source_kb).expanduser().resolve()
    # base is <resolved_kb>/derived -- kept unresolved so a symlink at derived/
    # is detected: its resolved target cannot equal base / slug lexically.
    base = kb_resolved / DERIVED_DIRNAME
    expected = base / slug
    target = expected.resolve()
    if target != expected:
        raise InvalidSlugError(
            f"derived target for {slug!r} must resolve to {expected!s} itself; "
            f"resolved to {target!s} instead (possible symlink)"
        )
    return target


def create(source_kb: Path, slug: str, force: bool) -> Path:
    """Create derived/<slug>/, replacing it when force is given (C1, C4)."""
    validate_slug(slug)
    # Containment check before any disk access -- rejects symlinks planted at
    # <kb>/derived or <kb>/derived/<slug> that would let rmtree escape the KB.
    target = _safe_create_target(source_kb, slug)
    check_slug_available(source_kb, slug, force)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    return target


def copy_documents(source_store: KBStore, derived_dir: Path,
                   docs: list[DocumentRef]) -> int:
    """Copy each document into derived_dir keeping its source-relative name (C1).

    The matching .extract-cache/<checksum>.json entry is copied too when it
    exists (C7): the copies are byte-identical, so the content checksum the cache
    keys on matches and the derived compile skips the extract call already paid
    for. A missing entry is not an error. Copied, not symlinked, so deleting the
    source KB cannot invalidate the derived one.

    Caveat: the cache key carries no model or prompt version, so compiling a
    derived KB with a different model than the source reuses the other model's
    extractions. That is already true within one KB today.
    """
    copied = 0
    for doc in docs:
        # Reject absolute rel_path (pathlib would discard derived_dir entirely)
        # and any path that escapes via '..' (spec E4).
        if Path(doc.rel_path).is_absolute() or ".." in Path(doc.rel_path).parts:
            raise DeriveError(
                f"rel_path {doc.rel_path!r} is absolute or contains '..'; "
                "refusing to copy"
            )
        if not _CHECKSUM_RE.fullmatch(doc.checksum):
            raise DeriveError(
                f"checksum {doc.checksum!r} does not match ^[0-9a-f]{{16}}$ "
                "(spec E4)"
            )
        content = source_store.read_raw(doc.rel_path)
        dest = derived_dir / doc.rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        copied += 1

        cache_src = source_store.base_dir / ".extract-cache" / f"{doc.checksum}.json"
        if cache_src.exists():
            cache_dst = derived_dir / ".extract-cache" / f"{doc.checksum}.json"
            cache_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache_src, cache_dst)
    return copied


def write_manifest(derived_dir: Path, payload: dict) -> None:
    """Write manifest.json atomically (E1: before compiling, so a dead run still records intent).

    Uses a sibling temp file + os.replace so a crash mid-write cannot leave a
    truncated manifest -- matching the pattern in storage/store.py.
    """
    target = Path(derived_dir) / MANIFEST_NAME
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    os.replace(str(tmp), str(target))


def read_manifest(derived_dir: Path) -> dict:
    """Read manifest.json, or {} when absent or unparseable (including bad UTF-8)."""
    path = Path(derived_dir) / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        # ValueError catches json.JSONDecodeError and UnicodeDecodeError (invalid
        # UTF-8), both of which indicate an unreadable manifest.
        return {}
    return data if isinstance(data, dict) else {}


def list_derived(root_kb: str) -> list[dict]:
    """Every derived KB's manifest under root_kb, sorted by slug (H2).

    A directory without a readable manifest is not a derived KB and is skipped.
    Entries whose name fails SLUG_RE or that resolve outside derived/ are also
    skipped, so the set of slugs this returns agrees with what resolve_kb_dir
    accepts.
    """
    root = Path(root_kb).expanduser().resolve() / DERIVED_DIRNAME
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if not SLUG_RE.match(child.name):
            continue
        # Reject symlinks pointing outside derived/ -- same containment logic as
        # resolve_kb_dir: compare the resolved path against the unresolved base so
        # a symlink at <kb>/derived or <kb>/derived/<slug> is both caught.
        if not child.resolve().is_relative_to(root):
            continue
        manifest = read_manifest(child)
        if manifest:
            out.append(manifest)
    return out


def resolve_kb_dir(root_kb: str, slug: str | None) -> str:
    """Root KB when slug is empty, else <root>/derived/<slug> (G3, G4, H3).

    Raises InvalidSlugError on a slug failing lexical validation and
    UnknownDerivedKBError when no such derived KB exists. Never falls back to the
    root KB: answering from the wrong corpus silently is worse than an error.

    Containment is checked after resolve(), so a symlink planted under derived/
    that points outside the KB is rejected -- matching KBStore._resolve rather
    than the Go layer's lexical check, on purpose.
    """
    root = Path(root_kb).expanduser().resolve()
    if not slug:
        return str(root)
    validate_slug(slug)
    base = root / DERIVED_DIRNAME
    target = (base / slug).resolve()
    if not target.is_relative_to(base) or not (target / MANIFEST_NAME).exists():
        raise UnknownDerivedKBError(f"no derived knowledge base named {slug!r}")
    return str(target)
