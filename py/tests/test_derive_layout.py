"""Tests for derive/_layout.py -- slug rules, directory creation, manifest I/O."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._errors import (
    DeriveError, InvalidSlugError, NestedDeriveError, SlugExistsError, UnknownDerivedKBError,
)
from kb_ai.derive import _layout
from kb_ai.derive._types import DocumentRef
from kb_ai.storage.store import KBStore


@pytest.mark.parametrize("topic,expected", [
    ("pricing and fee structure", "pricing-and-fee-structure"),
    ("Pricing / Fees!", "pricing-fees"),
    ("  spaced  out  ", "spaced-out"),
    ("CJK 定价", "cjk"),
    ("a" * 60, "a" * 40),
    ("x" * 39 + "-tail", "x" * 39),  # truncation must not leave a trailing dash
])
def test_normalise_slug(topic, expected):
    assert _layout.normalise_slug(topic) == expected


@pytest.mark.parametrize("slug", ["", "-", "..", ".", "a/b", "A", "-lead", "x" * 41, "定价",
                                   "pricing\n"])  # trailing newline: re.match allows it, fullmatch must not
def test_validate_slug_rejects(slug):
    with pytest.raises(InvalidSlugError):
        _layout.validate_slug(slug)


def test_validate_slug_accepts():
    _layout.validate_slug("pricing-and-fees")
    _layout.validate_slug("a")
    _layout.validate_slug("x" * 40)


def test_assert_not_nested_rejects_a_derived_kb(tmp_path: Path):
    nested = tmp_path / "derived" / "pricing"
    nested.mkdir(parents=True)
    (nested / "manifest.json").write_text("{}")
    with pytest.raises(NestedDeriveError):
        _layout.assert_not_nested(nested)


def test_assert_not_nested_allows_a_dir_named_derived_without_a_manifest(tmp_path: Path):
    plain = tmp_path / "derived" / "kb"
    plain.mkdir(parents=True)
    _layout.assert_not_nested(plain)  # no manifest -> not a derived KB


def test_create_makes_the_derived_dir(tmp_path: Path):
    out = _layout.create(tmp_path, "pricing", force=False)
    assert out == tmp_path / "derived" / "pricing"
    assert out.is_dir()


def test_create_refuses_an_existing_slug(tmp_path: Path):
    (tmp_path / "derived" / "pricing").mkdir(parents=True)
    with pytest.raises(SlugExistsError):
        _layout.create(tmp_path, "pricing", force=False)


def test_force_replaces_only_a_directory_derive_created(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps({"slug": "pricing"}))
    (target / "stale.txt").write_text("old")

    out = _layout.create(tmp_path, "pricing", force=True)
    assert out.is_dir()
    assert not (out / "stale.txt").exists()


def test_force_refuses_a_directory_with_no_matching_manifest(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "precious.md").write_text("not ours")
    with pytest.raises(SlugExistsError):
        _layout.create(tmp_path, "pricing", force=True)
    assert (target / "precious.md").exists()


def test_force_refuses_a_manifest_naming_another_slug(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text(json.dumps({"slug": "compliance"}))
    with pytest.raises(SlugExistsError):
        _layout.create(tmp_path, "pricing", force=True)


@pytest.mark.parametrize("slug", ["../evil", "/etc/passwd", ""])
def test_create_refuses_hostile_slug_before_touching_filesystem(
    tmp_path: Path, slug: str
):
    """Hostile slugs are caught by validate_slug before any path is built."""
    with pytest.raises(InvalidSlugError):
        _layout.create(tmp_path, slug, force=False)
    assert not (tmp_path / "derived").exists()


def test_create_refuses_derived_dir_symlinked_outside(tmp_path: Path):
    """Layout 1: <kb>/derived itself is a symlink pointing outside the KB.

    Even with --force and a manifest that names the right slug, the containment
    check must raise InvalidSlugError before rmtree runs and the outside directory
    must survive intact.  Checking manifest.json survival rather than the
    directory itself: without the fix, rmtree deletes the contents and mkdir
    recreates an empty dir, so the directory alone is not a reliable sentinel.
    """
    outside = tmp_path / "outside"
    (outside / "pricing").mkdir(parents=True)
    (outside / "pricing" / "manifest.json").write_text(json.dumps({"slug": "pricing"}))
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "derived").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidSlugError):
        _layout.create(kb, "pricing", force=True)

    assert (outside / "pricing" / "manifest.json").exists(), (
        "rmtree must not have run: manifest.json was deleted"
    )


def test_create_refuses_slug_symlinked_to_derived_itself(tmp_path: Path):
    """Layout 3: <kb>/derived/<slug> is a symlink to <kb>/derived itself.

    Without the parent-equality guard, is_relative_to passes (a path is relative
    to itself), so force=True rmtrees <kb>/derived entirely — destroying every
    sibling derived KB — then recreates it empty.  The fix must raise
    InvalidSlugError before any rmtree runs and leave the sibling's manifest.json
    intact.
    """
    kb = tmp_path / "kb"
    derived_root = kb / "derived"
    derived_root.mkdir(parents=True)
    # Sibling derived KB that must survive.
    sibling = derived_root / "compliance"
    sibling.mkdir()
    (sibling / "manifest.json").write_text(json.dumps({"slug": "compliance"}))
    # Trap: pricing → derived/ itself, so resolve() collapses to derived/.
    (derived_root / "pricing").symlink_to(derived_root, target_is_directory=True)
    # Manifest at derived/ so check_slug_available passes force=True through;
    # without the fix, rmtree then deletes the entire derived/ tree.
    (derived_root / "manifest.json").write_text(json.dumps({"slug": "pricing"}))

    with pytest.raises(InvalidSlugError):
        _layout.create(kb, "pricing", force=True)

    assert (sibling / "manifest.json").exists(), (
        "compliance manifest.json was deleted — rmtree must not have run on derived/"
    )


def test_create_refuses_slug_entry_symlinked_outside(tmp_path: Path):
    """Layout 2: <kb>/derived/<slug> is a symlink pointing outside the KB.

    Even with --force and a manifest that names the right slug, the containment
    check must raise InvalidSlugError before rmtree runs and the outside directory
    must survive intact.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text(json.dumps({"slug": "pricing"}))
    kb = tmp_path / "kb"
    (kb / "derived").mkdir(parents=True)
    (kb / "derived" / "pricing").symlink_to(outside, target_is_directory=True)

    with pytest.raises(InvalidSlugError):
        _layout.create(kb, "pricing", force=True)

    assert outside.exists(), "rmtree must not have run on outside"
    assert (outside / "manifest.json").exists()


def test_create_refuses_sibling_symlink(tmp_path: Path):
    """Layout 4: <kb>/derived/<slug> is a symlink to another entry in derived/.

    derived/pricing -> derived/pricing-backup, with pricing-backup holding a
    manifest naming slug 'pricing'.  With the old parent == base guard the
    resolved parent is still derived/, so rmtree deletes pricing-backup/ and
    the manifest is lost.  The exact-path guard must raise InvalidSlugError
    before any deletion and leave pricing-backup/manifest.json intact.
    """
    kb = tmp_path / "kb"
    derived_root = kb / "derived"
    sibling = derived_root / "pricing-backup"
    sibling.mkdir(parents=True)
    (sibling / "manifest.json").write_text(json.dumps({"slug": "pricing"}))
    (derived_root / "pricing").symlink_to(sibling, target_is_directory=True)

    with pytest.raises(InvalidSlugError):
        _layout.create(kb, "pricing", force=True)

    assert (sibling / "manifest.json").exists(), (
        "rmtree must not have run: pricing-backup/manifest.json was deleted"
    )


def test_create_refuses_dangling_symlink(tmp_path: Path):
    """Layout 5: <kb>/derived/<slug> is a dangling symlink.

    derived/pricing -> derived/ghost (nonexistent).  With the old parent == base
    guard the resolved parent is still derived/, so mkdir silently creates
    derived/ghost — diverging from derived_dir().  The exact-path guard must
    raise InvalidSlugError before mkdir runs and leave no derived/ghost behind.
    """
    kb = tmp_path / "kb"
    derived_root = kb / "derived"
    derived_root.mkdir(parents=True)
    ghost = derived_root / "ghost"
    (derived_root / "pricing").symlink_to(ghost, target_is_directory=True)

    with pytest.raises(InvalidSlugError):
        _layout.create(kb, "pricing", force=False)

    assert not ghost.exists(), (
        "mkdir must not have run: derived/ghost directory was created"
    )


def test_copy_documents_copies_content_and_extract_cache(tmp_path: Path):
    src = tmp_path / "src"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "notes.md").write_text("body")
    from kb_ai.storage.store import _compute_checksum
    checksum = _compute_checksum("body")
    cache_dir = src / ".extract-cache"
    cache_dir.mkdir()
    (cache_dir / f"{checksum}.json").write_text('{"summary": "cached"}')

    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)
    copied = _layout.copy_documents(store, derived, [
        DocumentRef(rel_path="raw/notes.md", checksum=checksum, size_bytes=4),
    ])

    assert copied == 1
    assert (derived / "raw" / "notes.md").read_text() == "body"
    assert (derived / ".extract-cache" / f"{checksum}.json").read_text() == '{"summary": "cached"}'


def test_copy_documents_tolerates_a_missing_cache_entry(tmp_path: Path):
    src = tmp_path / "src"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "notes.md").write_text("body")
    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)

    copied = _layout.copy_documents(store, derived, [
        DocumentRef(rel_path="raw/notes.md", checksum="deadbeefdeadbeef", size_bytes=4),
    ])
    assert copied == 1
    assert not (derived / ".extract-cache").exists()


def test_copy_documents_rejects_absolute_rel_path(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)

    with pytest.raises(DeriveError, match="absolute"):
        _layout.copy_documents(store, derived, [
            DocumentRef(rel_path="/etc/passwd", checksum="deadbeefdeadbeef", size_bytes=0),
        ])


def test_copy_documents_rejects_traversal_rel_path(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)

    with pytest.raises(DeriveError, match=r"\.\.|absolute"):
        _layout.copy_documents(store, derived, [
            DocumentRef(rel_path="../escape.md", checksum="deadbeefdeadbeef", size_bytes=0),
        ])


def test_copy_documents_rejects_invalid_checksum(tmp_path: Path):
    src = tmp_path / "src"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "notes.md").write_text("body")
    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)

    with pytest.raises(DeriveError, match="checksum"):
        _layout.copy_documents(store, derived, [
            DocumentRef(rel_path="raw/notes.md", checksum="NOTVALID", size_bytes=4),
        ])


def test_copy_documents_rejects_checksum_with_trailing_newline(tmp_path: Path):
    """'deadbeefdeadbeef\\n' must not pass via re.match's trailing-newline loophole."""
    src = tmp_path / "src"
    (src / "raw").mkdir(parents=True)
    (src / "raw" / "notes.md").write_text("body")
    derived = tmp_path / "derived" / "x"
    derived.mkdir(parents=True)
    store = KBStore(str(src), read_only=True)

    with pytest.raises(DeriveError, match="checksum"):
        _layout.copy_documents(store, derived, [
            DocumentRef(rel_path="raw/notes.md", checksum="deadbeefdeadbeef\n", size_bytes=4),
        ])


def test_manifest_round_trip(tmp_path: Path):
    _layout.write_manifest(tmp_path, {"slug": "pricing", "topic": "pricing"})
    assert _layout.read_manifest(tmp_path)["slug"] == "pricing"


def test_read_manifest_of_a_dir_without_one(tmp_path: Path):
    assert _layout.read_manifest(tmp_path) == {}


def test_read_manifest_returns_empty_for_invalid_utf8(tmp_path: Path):
    """UnicodeDecodeError (invalid UTF-8) is silenced just like JSONDecodeError."""
    (tmp_path / "manifest.json").write_bytes(b"\xff\xfe not valid utf-8 {")
    assert _layout.read_manifest(tmp_path) == {}


def test_resolve_kb_dir_root(tmp_path: Path):
    assert _layout.resolve_kb_dir(str(tmp_path), None) == str(tmp_path.resolve())
    assert _layout.resolve_kb_dir(str(tmp_path), "") == str(tmp_path.resolve())


def test_resolve_kb_dir_derived(tmp_path: Path):
    target = tmp_path / "derived" / "pricing"
    target.mkdir(parents=True)
    (target / "manifest.json").write_text("{}")
    assert _layout.resolve_kb_dir(str(tmp_path), "pricing") == str(target.resolve())


def test_resolve_kb_dir_unknown_slug(tmp_path: Path):
    with pytest.raises(UnknownDerivedKBError):
        _layout.resolve_kb_dir(str(tmp_path), "nope")


def test_resolve_kb_dir_rejects_a_traversal_slug(tmp_path: Path):
    with pytest.raises(InvalidSlugError):
        _layout.resolve_kb_dir(str(tmp_path), "../..")


def test_resolve_kb_dir_rejects_a_symlinked_derived_kb(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text("{}")
    derived_root = tmp_path / "kb" / "derived"
    derived_root.mkdir(parents=True)
    (derived_root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(UnknownDerivedKBError):
        _layout.resolve_kb_dir(str(tmp_path / "kb"), "escape")


def test_list_derived_reads_manifests(tmp_path: Path):
    for slug, topic in (("pricing", "pricing"), ("compliance", "compliance rules")):
        d = tmp_path / "derived" / slug
        d.mkdir(parents=True)
        (d / "manifest.json").write_text(json.dumps({"slug": slug, "topic": topic}))
    (tmp_path / "derived" / "junk").mkdir()  # no manifest -> not listed

    got = _layout.list_derived(str(tmp_path))
    assert [m["slug"] for m in got] == ["compliance", "pricing"]


def test_list_derived_skips_dir_with_trailing_newline_name(tmp_path: Path):
    """A derived/ child whose name has a trailing newline is not listed.

    Pre-fix: list_derived used SLUG_RE.match, which accepts "pricing\\n" because
    Python's $ matches just before a trailing newline (re.match does not require
    consuming the full string). The child therefore passed the filter and its
    manifest appeared in the result.
    Post-fix: SLUG_RE.fullmatch requires the entire string to match the pattern;
    the unconsumed trailing \\n causes it to return None and the child is skipped.
    """
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    bad_name = "pricing\n"  # POSIX allows newlines in directory names
    bad_dir = derived_root / bad_name
    bad_dir.mkdir()
    (bad_dir / "manifest.json").write_text(json.dumps({"slug": "pricing\n"}))

    got = _layout.list_derived(str(tmp_path))
    assert got == [], f"expected [], got {got!r}"


def test_list_derived_skips_symlinked_children(tmp_path: Path):
    """A derived/<slug> that is a symlink pointing outside derived/ is not listed.

    Mirrors the resolve_kb_dir containment check so the two agree on which slugs
    are valid.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text(json.dumps({"slug": "escape"}))
    derived_root = tmp_path / "kb" / "derived"
    derived_root.mkdir(parents=True)
    # Real, legitimate derived KB.
    legit = derived_root / "pricing"
    legit.mkdir()
    (legit / "manifest.json").write_text(json.dumps({"slug": "pricing"}))
    # Symlinked entry pointing outside the KB -- must be skipped.
    (derived_root / "escape").symlink_to(outside, target_is_directory=True)

    got = _layout.list_derived(str(tmp_path / "kb"))
    assert [m["slug"] for m in got] == ["pricing"]
