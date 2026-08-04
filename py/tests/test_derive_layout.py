"""Tests for derive/_layout.py -- slug rules, directory creation, manifest I/O."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai._errors import (
    InvalidSlugError, NestedDeriveError, SlugExistsError, UnknownDerivedKBError,
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


@pytest.mark.parametrize("slug", ["", "-", "..", ".", "a/b", "A", "-lead", "x" * 41, "定价"])
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


def test_manifest_round_trip(tmp_path: Path):
    _layout.write_manifest(tmp_path, {"slug": "pricing", "topic": "pricing"})
    assert _layout.read_manifest(tmp_path)["slug"] == "pricing"


def test_read_manifest_of_a_dir_without_one(tmp_path: Path):
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
