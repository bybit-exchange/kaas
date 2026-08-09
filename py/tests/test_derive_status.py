"""The two read-only checks over the extraction layer (spec F3, F5, F6, F7).

check_extractions asks whether a KB's extractions match its own documents;
check_parent asks whether the parent has moved since a derived KB was built. A
derived KB can pass the first and still be months behind on the second, which is
why both exist. Neither spends anything.
"""
from __future__ import annotations

import json
from pathlib import Path

from kb_ai.core.extract import ExtractionResult
from kb_ai.derive import _status
from kb_ai.storage import extraction as exl
from kb_ai.storage.store import KBStore, _compute_checksum


def _kb(tmp_path: Path, docs: dict[str, str]) -> KBStore:
    store = KBStore(str(tmp_path))
    for rel, content in docs.items():
        store.write_raw(rel, content)
    return store


def _extract(store: KBStore, rel: str, *, checksum: str | None = None) -> None:
    content = store.read_raw(rel)
    exl.persist(store, rel, ExtractionResult(summary=f"summary of {rel}"),
                source_checksum=checksum or _compute_checksum(content),
                extract_model="m")


# ── F3: does this KB's extraction match its own document ────────────

def test_every_extraction_matching_its_document(tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body", "raw/nested/b.md": "b body"})
    _extract(store, "raw/a.md")
    _extract(store, "raw/nested/b.md")

    check = _status.check_extractions(str(store.base_dir))

    assert check.matches == ["raw/a.md", "raw/nested/b.md"]
    assert check.missing == [] and check.mismatched == []
    assert check.total == 2
    assert "2 match" in check.summary()


def test_a_document_with_no_extraction_is_missing_not_mismatched(tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})

    check = _status.check_extractions(str(store.base_dir))

    assert check.matches == []
    assert check.missing == [("raw/a.md", "missing")]


def test_an_extraction_describing_different_text_is_mismatched(tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md", checksum="0" * 16)

    check = _status.check_extractions(str(store.base_dir))

    assert check.matches == []
    assert len(check.mismatched) == 1
    rel, reason = check.mismatched[0]
    assert rel == "raw/a.md"
    assert "document hashes to" in reason


def test_a_kb_with_no_raw_directory_checks_clean(tmp_path):
    check = _status.check_extractions(str(tmp_path))
    assert check.total == 0


def test_a_pre_change_kb_reports_every_document_as_missing(tmp_path):
    """F7: this is exactly what the seven pre-change derived KBs look like."""
    store = _kb(tmp_path, {"raw/a.md": "a", "raw/b.md": "b"})
    (store.base_dir / ".extract-cache").mkdir()
    (store.base_dir / ".extract-cache" / "deadbeefdeadbeef.json").write_text("{}")

    check = _status.check_extractions(str(store.base_dir))

    assert [rel for rel, _ in check.missing] == ["raw/a.md", "raw/b.md"]


# ── F5: has the parent moved since I was derived ────────────────────

def _derived(tmp_path: Path, parent: KBStore, docs: list[str],
             checksums: dict[str, str] | None = None) -> Path:
    derived = tmp_path / "derived" / "topic"
    derived.mkdir(parents=True)
    checksums = checksums or {}
    manifest = {
        "schema_version": 1,
        "source_kb": str(parent.base_dir),
        "slug": "topic",
        "documents": [
            {"rel_path": rel,
             "checksum": checksums.get(rel, _compute_checksum(parent.read_raw(rel))),
             "size_bytes": 1}
            for rel in docs
        ],
    }
    (derived / "manifest.json").write_text(json.dumps(manifest))
    return derived


def test_a_derived_kb_in_sync_with_its_parent(tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body", "raw/b.md": "b body"})
    derived = _derived(tmp_path, parent, ["raw/a.md", "raw/b.md"])

    check = _status.check_parent(str(derived))

    assert check.verdict == _status.IN_SYNC
    assert check.in_sync == ["raw/a.md", "raw/b.md"]
    assert check.source_kb == str(parent.base_dir)
    assert "2 in sync" in check.summary()


def test_a_document_changed_in_the_parent(tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived = _derived(tmp_path, parent, ["raw/a.md"])
    parent.write_raw("raw/a.md", "a body, revised")

    check = _status.check_parent(str(derived))

    assert check.verdict == _status.CHANGED_IN_PARENT
    assert check.changed_in_parent == ["raw/a.md"]
    assert check.in_sync == []


def test_a_document_gone_from_the_parent(tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived = _derived(tmp_path, parent, ["raw/a.md"])
    (parent.base_dir / "raw" / "a.md").unlink()

    check = _status.check_parent(str(derived))

    assert check.verdict == _status.CHANGED_IN_PARENT
    assert check.gone_from_parent == ["raw/a.md"]


def test_an_unreachable_parent_is_unknown_rather_than_an_error(tmp_path):
    """F6: derive is built for parents that may be read-only or someone else's."""
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived = _derived(tmp_path, parent, ["raw/a.md"])
    import shutil
    shutil.rmtree(parent.base_dir)

    check = _status.check_parent(str(derived))

    assert check.verdict == _status.UNKNOWN
    assert "no readable raw/" in check.reason
    assert "unknown" in check.summary()


def test_no_manifest_is_unknown(tmp_path):
    check = _status.check_parent(str(tmp_path))
    assert check.verdict == _status.UNKNOWN
    assert "manifest.json" in check.reason


def test_a_manifest_without_a_source_kb_is_unknown(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"slug": "x"}))
    check = _status.check_parent(str(tmp_path))
    assert check.verdict == _status.UNKNOWN
    assert "no source_kb" in check.reason


def test_check_parent_runs_against_a_pre_change_derived_kb(tmp_path):
    """F7: F5 reads manifest.json and the parent's raw/, nothing else -- so it
    works unchanged on a derived KB built before extraction/ existed."""
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived = _derived(tmp_path, parent, ["raw/a.md"])
    (derived / ".extract-cache").mkdir()

    check = _status.check_parent(str(derived))

    assert check.verdict == _status.IN_SYNC
    # ...while F3 has nothing to work with there.
    assert _status.check_extractions(str(derived)).total == 0


def test_a_manifest_entry_without_a_rel_path_is_skipped(tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived = tmp_path / "derived" / "topic"
    derived.mkdir(parents=True)
    (derived / "manifest.json").write_text(json.dumps({
        "source_kb": str(parent.base_dir),
        "documents": [{"checksum": "x", "size_bytes": 1}, {"rel_path": "raw/a.md",
                       "checksum": _compute_checksum("a body"), "size_bytes": 1}],
    }))

    check = _status.check_parent(str(derived))

    assert check.total == 1
    assert check.in_sync == ["raw/a.md"]


def test_an_unreadable_parent_document_is_unknown(tmp_path, monkeypatch):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived = _derived(tmp_path, parent, ["raw/a.md"])

    def boom(self, *args, **kwargs):
        raise OSError("Input/output error")

    monkeypatch.setattr("builtins.open", boom)
    check = _status.check_parent(str(derived))

    assert check.verdict == _status.UNKNOWN
    assert "unreadable" in check.reason
