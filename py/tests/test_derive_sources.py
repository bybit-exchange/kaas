"""Tests for derive/_sources.py -- sources: parsing and document resolution."""
from __future__ import annotations

from pathlib import Path

from kb_ai.derive import _sources
from kb_ai.storage.store import KBStore, _compute_checksum


def _kb(tmp_path: Path) -> KBStore:
    (tmp_path / "wiki").mkdir(parents=True, exist_ok=True)
    (tmp_path / "raw").mkdir(parents=True, exist_ok=True)
    return KBStore(str(tmp_path), read_only=True)


def _article(tmp_path: Path, name: str, frontmatter: str) -> str:
    path = f"wiki/{name}"
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(f"---\n{frontmatter}\n---\n\n# Body\n")
    return path


def _raw(tmp_path: Path, name: str, content: str) -> None:
    p = tmp_path / "raw" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def test_resolves_and_dedupes_across_articles(tmp_path: Path):
    _raw(tmp_path, "a.md", "alpha")
    _raw(tmp_path, "b.md", "beta")
    p1 = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/a.md\n  - raw/b.md')
    p2 = _article(tmp_path, "two.md", 'title: Two\nsources:\n  - raw/b.md')

    docs, skipped_articles, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p1, p2])

    assert [d.rel_path for d in docs] == ["raw/a.md", "raw/b.md"]  # sorted, deduped
    assert skipped_articles == [] and skipped_docs == []
    assert docs[0].checksum == _compute_checksum("alpha")
    assert docs[0].size_bytes == len("alpha".encode())


def test_comma_joined_entry_yields_every_document(tmp_path: Path):
    # A batch merge writes several rels into one sources entry:
    # commands/compile.py passes ", ".join(merge_rels) as source_path.
    _raw(tmp_path, "a.md", "alpha")
    _raw(tmp_path, "b.md", "beta")
    p = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/a.md, raw/b.md')

    docs, _, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/a.md", "raw/b.md"]


def test_scalar_sources_value_is_accepted(tmp_path: Path):
    _raw(tmp_path, "a.md", "alpha")
    p = _article(tmp_path, "one.md", 'title: One\nsources: raw/a.md')
    docs, _, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/a.md"]


def test_no_sources_key(tmp_path: Path):
    p = _article(tmp_path, "one.md", "title: One")
    docs, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert docs == []
    assert [(s.ref, s.reason) for s in skipped_articles] == [(p, "no_sources_key")]


def test_empty_sources_list(tmp_path: Path):
    p = _article(tmp_path, "one.md", "title: One\nsources: []")
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert skipped_articles[0].reason == "empty_sources"


def test_unparseable_frontmatter(tmp_path: Path):
    p = "wiki/bad.md"
    (tmp_path / p).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / p).write_text("no frontmatter here\n")
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert skipped_articles[0].reason == "unparseable_frontmatter"


def test_invalid_yaml_frontmatter(tmp_path: Path):
    p = _article(tmp_path, "bad.md", "title: [unclosed")
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), [p])
    assert skipped_articles[0].reason == "unparseable_frontmatter"


def test_article_unreadable(tmp_path: Path):
    _, skipped_articles, _ = _sources.resolve_documents(_kb(tmp_path), ["wiki/ghost.md"])
    assert skipped_articles[0].reason == "article_unreadable"


def test_escaping_source_entry_is_recorded_not_fatal(tmp_path: Path):
    outside = tmp_path.parent / "secret.md"
    outside.write_text("secret")
    _raw(tmp_path, "ok.md", "fine")
    p = _article(tmp_path, "one.md",
                 'title: One\nsources:\n  - ../secret.md\n  - raw/ok.md')

    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/ok.md"]
    assert [(s.ref, s.reason) for s in skipped_docs] == [("../secret.md", "escapes_kb")]


def test_absolute_source_entry_is_rejected(tmp_path: Path):
    p = _article(tmp_path, "one.md", 'title: One\nsources:\n  - /etc/passwd')
    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert docs == []
    assert skipped_docs[0].reason == "escapes_kb"


def test_missing_document_is_recorded_not_fatal(tmp_path: Path):
    _raw(tmp_path, "ok.md", "fine")
    p = _article(tmp_path, "one.md",
                 'title: One\nsources:\n  - raw/gone.md\n  - raw/ok.md')
    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/ok.md"]
    assert [(s.ref, s.reason) for s in skipped_docs] == [("raw/gone.md", "document_missing")]


def test_unreadable_document_is_recorded(tmp_path: Path, monkeypatch):
    _raw(tmp_path, "a.md", "alpha")
    p = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/a.md')
    store = _kb(tmp_path)

    def boom(rel_path: str) -> str:
        raise OSError("EIO")

    monkeypatch.setattr(store, "read_raw", boom)
    docs, _, skipped_docs = _sources.resolve_documents(store, [p])
    assert docs == []
    assert skipped_docs[0].reason == "document_unreadable"


def test_an_entry_outside_raw_is_skipped_not_copied(tmp_path: Path):
    """sources: is LLM-written, so an entry may name a file outside raw/ (C1).

    Copying wiki/pricing.md into the derived KB would inject an article that was
    never compiled from the derived raw/, so the entry is skipped like any other
    unusable one.
    """
    _raw(tmp_path, "ok.md", "fine")
    p = _article(tmp_path, "one.md",
                 'title: One\nsources:\n  - wiki/pricing.md\n  - raw/ok.md')
    (tmp_path / "wiki" / "pricing.md").write_text("---\ntitle: Pricing\n---\n")

    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert [d.rel_path for d in docs] == ["raw/ok.md"]
    assert [(s.ref, s.reason) for s in skipped_docs] == [
        ("wiki/pricing.md", "not_a_raw_document")]


def test_the_compile_state_file_is_not_a_source_document(tmp_path: Path):
    """Copying .compile-state.json in would make the derived compile a no-op."""
    (tmp_path / ".compile-state.json").write_text('{"files": {}}')
    p = _article(tmp_path, "one.md", 'title: One\nsources:\n  - .compile-state.json')

    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert docs == []
    assert [(s.ref, s.reason) for s in skipped_docs] == [
        (".compile-state.json", "not_a_raw_document")]


def test_an_entry_climbing_out_of_raw_is_skipped(tmp_path: Path):
    """'raw/../wiki/x.md' starts with raw/ lexically but names a wiki article."""
    p = _article(tmp_path, "one.md",
                 'title: One\nsources:\n  - raw/../wiki/pricing.md')
    (tmp_path / "wiki" / "pricing.md").write_text("---\ntitle: Pricing\n---\n")

    docs, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p])
    assert docs == []
    assert skipped_docs[0].reason == "not_a_raw_document"


def test_a_document_skipped_once_is_not_reported_twice(tmp_path: Path):
    p1 = _article(tmp_path, "one.md", 'title: One\nsources:\n  - raw/gone.md')
    p2 = _article(tmp_path, "two.md", 'title: Two\nsources:\n  - raw/gone.md')
    _, _, skipped_docs = _sources.resolve_documents(_kb(tmp_path), [p1, p2])
    assert len(skipped_docs) == 1
