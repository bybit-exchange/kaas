"""Tests for derive/_offtopic.py -- the second (PRECISION) filter pass."""
from __future__ import annotations

from pathlib import Path

from kb_ai.derive import _offtopic
from kb_ai.derive._types import MODE_PRECISION, SelectionResult
from kb_ai.storage.store import KBStore


def _derived(tmp_path: Path, articles: dict[str, str]) -> Path:
    """Build a compiled-looking derived KB: wiki/*.md plus a master index."""
    (tmp_path / "index").mkdir(parents=True, exist_ok=True)
    lines = ["# Knowledge Base Index", ""]
    for rel, title in articles.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\ntitle: {title}\ntags: [t]\n---\n\n# {title}\n\nProse.\n")
        lines.append(f"- [{title}]({rel}) — Prose.")
    (tmp_path / "index" / "master-index.md").write_text("\n".join(lines) + "\n")
    return tmp_path


def _selector(keep: list[str]):
    calls: list[str] = []

    def select(catalog, topic, mode):
        calls.append(mode)
        return SelectionResult(paths=list(keep), batches=1, dropped_invented=0, skipped=[])

    return select, calls


def test_moves_unselected_articles_preserving_their_path(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/concepts/a.md": "A", "wiki/projects/b.md": "B"})
    select, calls = _selector(["wiki/concepts/a.md"])

    moved, warnings = _offtopic.prune(d, "pricing", select)

    assert moved == ["wiki/projects/b.md"]
    assert warnings == []
    assert calls == [MODE_PRECISION]
    assert (d / "_offtopic" / "projects" / "b.md").exists()
    assert not (d / "wiki" / "projects" / "b.md").exists()
    assert (d / "wiki" / "concepts" / "a.md").exists()


def test_moved_article_leaves_the_derived_catalog(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    select, _ = _selector(["wiki/a.md"])

    _offtopic.prune(d, "pricing", select)

    catalog = (d / "index" / "master-index.md").read_text()
    assert "wiki/a.md" in catalog
    assert "wiki/b.md" not in catalog
    # D4: assert against parsed entries (not raw text) so a future glob widening
    # of update_markdown_index would be caught, not silently pass this check.
    entries = KBStore(str(d)).existing_articles()
    assert all("_offtopic" not in e.path for e in entries)


def test_no_offtopic_dir_when_everything_is_selected(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    select, _ = _selector(["wiki/a.md", "wiki/b.md"])

    moved, warnings = _offtopic.prune(d, "pricing", select)

    assert moved == [] and warnings == []
    assert not (d / "_offtopic").exists()


def test_selecting_nothing_leaves_everything_in_place_and_warns(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    select, _ = _selector([])

    moved, warnings = _offtopic.prune(d, "pricing", select)

    assert moved == []
    assert warnings == ["second_pass_selected_nothing"]
    assert (d / "wiki" / "a.md").exists() and (d / "wiki" / "b.md").exists()
    assert not (d / "_offtopic").exists()


def test_empty_derived_catalog_warns_without_calling_the_selector(tmp_path: Path):
    (tmp_path / "index").mkdir(parents=True)
    called: list[str] = []

    def select(catalog, topic, mode):
        called.append(mode)
        raise AssertionError("selector must not be called on an empty catalog")

    moved, warnings = _offtopic.prune(tmp_path, "pricing", select)
    assert moved == []
    assert warnings == ["second_pass_empty_catalog"]
    assert called == []


def test_documents_behind_moved_articles_stay_in_raw(tmp_path: Path):
    d = _derived(tmp_path, {"wiki/a.md": "A", "wiki/b.md": "B"})
    (d / "raw").mkdir(parents=True, exist_ok=True)
    (d / "raw" / "src.md").write_text("body")
    select, _ = _selector(["wiki/a.md"])

    _offtopic.prune(d, "pricing", select)

    assert (d / "raw" / "src.md").read_text() == "body"


def test_traversing_catalog_entry_is_rejected(tmp_path: Path):
    """A hand-tampered master index entry that traverses outside derived_dir
    must be skipped, recorded as a warning, and must not affect any outside file."""
    derived = tmp_path / "derived"
    derived.mkdir()
    (derived / "index").mkdir()
    (derived / "wiki").mkdir()
    # A valid article so the catalog is non-empty and the selector has something to keep.
    (derived / "wiki" / "keep.md").write_text(
        "---\ntitle: Keep\ntags: [t]\n---\n\n# Keep\n\nProse.\n"
    )
    # A file outside derived_dir; the traversal entry below resolves src to this path.
    victim = tmp_path / "victim.md"
    victim.write_text("secret")
    # "wiki/../../victim.md" passes the startswith("wiki/") guard but resolves
    # src to tmp_path/victim.md, which is outside derived/.
    index_text = (
        "# Knowledge Base Index\n\n"
        "- [Keep](wiki/keep.md) — Prose.\n"
        "- [Victim](wiki/../../victim.md) — Prose.\n"
    )
    (derived / "index" / "master-index.md").write_text(index_text)
    # Selector keeps only the legitimate article; the traversal entry would be moved.
    select, _ = _selector(["wiki/keep.md"])

    moved, warnings = _offtopic.prune(derived, "pricing", select)

    # The traversal entry must not appear in moved.
    assert "wiki/../../victim.md" not in moved
    # The outside file must survive untouched.
    assert victim.read_text() == "secret"
    # A warning must document the rejected entry.
    assert any("path_escapes_derived_dir" in w for w in warnings)
