"""Tests for KBStore file-scan and cache paths (kb_ai.storage.store).

Focus: the raw/*.md scan contract (skip rules, streaming meta equivalence with
list_raw_files), the master-index parser's malformed-line handling, and the
cache_enabled=False short circuits. Everything runs under tmp_path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kb_ai.storage.store import KBStore, _compute_checksum


def _write_bytes(base: Path, rel: str, data: bytes) -> Path:
    full = base / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_bytes(data)
    return full


def _write_index(store: KBStore, text: str) -> None:
    store.index_dir.mkdir(parents=True, exist_ok=True)
    (store.index_dir / "master-index.md").write_text(text, encoding="utf-8")


# ── _iter_raw_paths skip rules ──────────────────────────────────────

def test_list_raw_files_skips_dotfiles(tmp_path: Path):
    store = KBStore(str(tmp_path))
    store.write_raw("raw/keep.md", "keep me")
    _write_bytes(store.base_dir, "raw/.hidden.md", b"hidden")

    rels = [f.rel_path for f in store.list_raw_files()]

    assert rels == ["raw/keep.md"]


def test_list_raw_files_skips_the_skipped_subtree(tmp_path: Path):
    store = KBStore(str(tmp_path))
    store.write_raw("raw/keep.md", "keep me")
    store.write_raw("raw/_skipped/dropped.md", "dropped")
    store.write_raw("raw/_skipped/nested/deep.md", "deep")

    rels = [f.rel_path for f in store.list_raw_files()]

    assert rels == ["raw/keep.md"]


def test_skipped_only_matches_a_whole_path_component(tmp_path: Path):
    """'_skipped' is matched against path parts, not as a substring."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/_skipped_notes/a.md", "still compiled")

    rels = [f.rel_path for f in store.list_raw_files()]

    assert rels == ["raw/_skipped_notes/a.md"]


def test_raw_scan_is_sorted_and_recursive(tmp_path: Path):
    store = KBStore(str(tmp_path))
    for rel in ["raw/b.md", "raw/a.md", "raw/sub/c.md"]:
        store.write_raw(rel, rel)

    rels = [f.rel_path for f in store.list_raw_files()]

    assert rels == sorted(rels)
    assert set(rels) == {"raw/a.md", "raw/b.md", "raw/sub/c.md"}


def test_raw_scan_on_missing_raw_dir_is_empty(tmp_path: Path):
    store = KBStore(str(tmp_path))
    assert not store.raw_dir.exists()

    assert store.list_raw_files() == []
    assert list(store.iter_raw_file_meta()) == []


# ── iter_raw_file_meta ──────────────────────────────────────────────

def test_iter_raw_file_meta_matches_list_raw_files(tmp_path: Path):
    store = KBStore(str(tmp_path))
    store.write_raw("raw/a.md", "alpha body")
    store.write_raw("raw/sub/b.md", "beta body with 中文")

    files = {f.rel_path: f for f in store.list_raw_files()}
    metas = {m.rel_path: m for m in store.iter_raw_file_meta()}

    assert metas.keys() == files.keys()
    for rel, meta in metas.items():
        assert meta.checksum == files[rel].checksum
        assert meta.size_bytes == len(files[rel].content.encode("utf-8"))


def test_iter_raw_file_meta_applies_the_same_skip_rules(tmp_path: Path):
    store = KBStore(str(tmp_path))
    store.write_raw("raw/keep.md", "keep")
    store.write_raw("raw/_skipped/gone.md", "gone")
    _write_bytes(store.base_dir, "raw/.hidden.md", b"hidden")

    assert [m.rel_path for m in store.iter_raw_file_meta()] == ["raw/keep.md"]


def test_iter_raw_file_meta_normalizes_crlf_like_read_text(tmp_path: Path):
    """CRLF must collapse to LF so checksum/size match the read_text() path."""
    store = KBStore(str(tmp_path))
    _write_bytes(store.base_dir, "raw/crlf.md", b"line one\r\nline two\r\n")

    meta = next(iter(store.iter_raw_file_meta()))
    raw_file = store.list_raw_files()[0]

    assert raw_file.content == "line one\nline two\n"
    assert meta.size_bytes == 18            # LF-normalized, not the 20 on disk
    assert meta.checksum == _compute_checksum("line one\nline two\n")


def test_iter_raw_file_meta_handles_multibyte_content_across_chunks(tmp_path: Path):
    """>64K chars forces multiple read() chunks; bytes must still add up."""
    store = KBStore(str(tmp_path))
    content = "好" * 70_000            # 70K chars / 210K UTF-8 bytes
    _write_bytes(store.base_dir, "raw/big.md", content.encode("utf-8"))

    meta = next(iter(store.iter_raw_file_meta()))

    assert meta.size_bytes == 210_000
    assert meta.checksum == _compute_checksum(content)


def test_iter_raw_file_meta_on_empty_file(tmp_path: Path):
    store = KBStore(str(tmp_path))
    _write_bytes(store.base_dir, "raw/empty.md", b"")

    meta = next(iter(store.iter_raw_file_meta()))

    assert meta.size_bytes == 0
    assert meta.checksum == _compute_checksum("")


def test_iter_raw_file_meta_is_lazy(tmp_path: Path):
    """It is a generator: nothing is read until the first next()."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/a.md", "body")
    it = store.iter_raw_file_meta()

    (store.base_dir / "raw/a.md").write_text("changed body", encoding="utf-8")

    assert next(it).checksum == _compute_checksum("changed body")


def test_iter_raw_file_meta_raises_on_invalid_utf8(tmp_path: Path):
    store = KBStore(str(tmp_path))
    _write_bytes(store.base_dir, "raw/bad.md", b"ok \xff\xfe not utf8")

    with pytest.raises(UnicodeDecodeError):
        list(store.iter_raw_file_meta())


# ── read_raw ────────────────────────────────────────────────────────

def test_read_raw_returns_content_by_rel_path(tmp_path: Path):
    store = KBStore(str(tmp_path))
    store.write_raw("raw/notes/a.md", "raw body")

    assert store.read_raw("raw/notes/a.md") == "raw body"


def test_read_raw_missing_file_raises(tmp_path: Path):
    store = KBStore(str(tmp_path))

    with pytest.raises(FileNotFoundError):
        store.read_raw("raw/nope.md")


def test_read_raw_is_usable_after_meta_scan(tmp_path: Path):
    """The estimate path streams meta first, then lazily reads by rel_path."""
    store = KBStore(str(tmp_path))
    store.write_raw("raw/a.md", "alpha")

    meta = next(iter(store.iter_raw_file_meta()))

    assert store.read_raw(meta.rel_path) == "alpha"


# ── write guards ────────────────────────────────────────────────────

def test_read_only_store_rejects_writes(tmp_path: Path):
    store = KBStore(str(tmp_path), read_only=True)

    with pytest.raises(PermissionError, match="read-only"):
        store.write_article("wiki/a.md", "x")
    with pytest.raises(PermissionError, match="read-only"):
        store.write_raw("raw/a.md", "x")
    assert not store.wiki_dir.exists()


# ── existing_articles parsing ───────────────────────────────────────

def test_existing_articles_skips_malformed_link_lines(tmp_path: Path):
    """A bullet that looks like an entry but has no '](' must not abort the parse."""
    store = KBStore(str(tmp_path))
    _write_index(store, (
        "# Knowledge Base Index\n\n"
        "- [no closing link — dangling\n"
        "- [Good](wiki/good.md) — good summary\n"
    ))

    articles = store.existing_articles()

    assert [a.path for a in articles] == ["wiki/good.md"]


def test_existing_articles_skips_line_with_unclosed_paren(tmp_path: Path):
    store = KBStore(str(tmp_path))
    _write_index(store, (
        "- [Broken](wiki/broken.md — missing paren\n"
        "- [Good](wiki/good.md) — ok\n"
    ))

    assert [a.title for a in store.existing_articles()] == ["Good"]


def test_existing_articles_keeps_titles_containing_parentheses(tmp_path: Path):
    store = KBStore(str(tmp_path))
    _write_index(store, "- [Kaas (v2)](wiki/kaas.md) — the platform\n")

    art = store.existing_articles()[0]

    assert art.title == "Kaas (v2)"
    assert art.path == "wiki/kaas.md"
    assert art.summary == "the platform"


def test_existing_articles_keeps_a_summary_containing_an_em_dash(tmp_path: Path):
    """Prose summaries contain em dashes; splitting on every one truncates them."""
    store = KBStore(str(tmp_path))
    _write_index(store, "- [Config](wiki/config.md) — Loads TOML — and applies overrides.\n")

    art = store.existing_articles()[0]

    assert art.summary == "Loads TOML — and applies overrides."


def test_existing_articles_keeps_titles_containing_an_em_dash(tmp_path: Path):
    store = KBStore(str(tmp_path))
    _write_index(store, "- [Config — TOML Loading](wiki/config.md) — the summary\n")

    art = store.existing_articles()[0]

    assert art.title == "Config — TOML Loading"
    assert art.summary == "the summary"


def test_existing_articles_without_summary_dash(tmp_path: Path):
    store = KBStore(str(tmp_path))
    _write_index(store, "- [Bare](wiki/bare.md)\n")

    assert store.existing_articles()[0].summary == ""


def test_existing_articles_missing_index_returns_empty(tmp_path: Path):
    assert KBStore(str(tmp_path)).existing_articles() == []


# ── cache short circuits ────────────────────────────────────────────

def test_extract_cache_disabled_neither_reads_nor_writes(tmp_path: Path):
    store = KBStore(str(tmp_path), cache_enabled=False)

    store.save_extract_cache("abc", {"facts": ["x"]})

    assert not (store.base_dir / ".extract-cache").exists()
    assert store.load_extract_cache("abc") is None


def test_extract_cache_disabled_ignores_a_preexisting_entry(tmp_path: Path):
    """A cache written earlier (enabled) must be invisible when disabled."""
    writer = KBStore(str(tmp_path))
    writer.save_extract_cache("abc", {"facts": ["x"]})
    assert writer.load_extract_cache("abc") == {"facts": ["x"]}

    reader = KBStore(str(tmp_path), cache_enabled=False)

    assert reader.load_extract_cache("abc") is None


def test_classify_cache_disabled_neither_reads_nor_writes(tmp_path: Path):
    store = KBStore(str(tmp_path), cache_enabled=False)

    store.save_classify_cache("key1", {"decision": "new"})

    assert not (store.base_dir / ".classify-cache").exists()
    assert store.load_classify_cache("key1") is None


def test_classify_cache_disabled_ignores_a_preexisting_entry(tmp_path: Path):
    writer = KBStore(str(tmp_path))
    writer.save_classify_cache("key1", {"decision": "new"})
    assert writer.load_classify_cache("key1") == {"decision": "new"}

    reader = KBStore(str(tmp_path), cache_enabled=False)

    assert reader.load_classify_cache("key1") is None


def test_classify_cache_serializes_objects_via_to_dict(tmp_path: Path):
    class Typed:
        def to_dict(self):
            return {"decision": "merge", "target": "wiki/a.md"}

    store = KBStore(str(tmp_path))
    store.save_classify_cache("k", Typed())

    assert store.load_classify_cache("k") == {"decision": "merge", "target": "wiki/a.md"}


def test_caches_missing_entry_returns_none(tmp_path: Path):
    store = KBStore(str(tmp_path))

    assert store.load_extract_cache("nope") is None
    assert store.load_classify_cache("nope") is None


# ── compile state ───────────────────────────────────────────────────

def test_compile_state_roundtrip_and_tmp_cleanup(tmp_path: Path):
    store = KBStore(str(tmp_path))

    store.save_compile_state({"raw/a.md": {"checksum": "abc"}})

    assert store.load_compile_state() == {"raw/a.md": {"checksum": "abc"}}
    # os.replace() must leave no .json.tmp behind.
    assert not (store.base_dir / ".compile-state.json.tmp").exists()


def test_compile_state_missing_returns_empty_dict(tmp_path: Path):
    assert KBStore(str(tmp_path)).load_compile_state() == {}


# ── regression guards for fixed bugs ─────────────────────────────────

@pytest.fixture
def kb_with_outside_secret(tmp_path: Path) -> KBStore:
    """A KB directory with a secret file sitting next to it, outside the store."""
    kb = tmp_path / "kb"
    kb.mkdir()
    (tmp_path / "secret.md").write_text("TOPSECRET", encoding="utf-8")
    return KBStore(str(kb))


@pytest.mark.parametrize("escaping_path", [
    "../secret.md",             # relative escape
    "wiki/../../secret.md",     # escape from a legitimate-looking prefix
])
def test_read_article_rejects_relative_escapes(kb_with_outside_secret, escaping_path):
    """rel_path arrives from the MCP ask tool's client-controlled paths argument,
    so an escape here is arbitrary file disclosure, not just a bad read."""
    with pytest.raises(ValueError, match="escapes kb_dir"):
        kb_with_outside_secret.read_article(escaping_path)


def test_read_article_rejects_an_absolute_path(kb_with_outside_secret, tmp_path: Path):
    """pathlib discards the left operand for an absolute right operand, so an
    absolute rel_path would otherwise read straight off the filesystem."""
    with pytest.raises(ValueError, match="escapes kb_dir"):
        kb_with_outside_secret.read_article(str(tmp_path / "secret.md"))


def test_read_raw_rejects_escapes(kb_with_outside_secret):
    with pytest.raises(ValueError, match="escapes kb_dir"):
        kb_with_outside_secret.read_raw("../secret.md")


@pytest.mark.parametrize("writer", ["write_article", "write_raw"])
def test_writes_reject_escapes_without_touching_the_target(kb_with_outside_secret, writer, tmp_path: Path):
    outside = tmp_path / "secret.md"

    with pytest.raises(ValueError, match="escapes kb_dir"):
        getattr(kb_with_outside_secret, writer)("../secret.md", "clobbered")

    assert outside.read_text(encoding="utf-8") == "TOPSECRET"


def test_guard_still_allows_ordinary_paths(kb_with_outside_secret):
    """The guard must not reject the normal case, including redundant segments."""
    kb_with_outside_secret.write_article("wiki/concept/a.md", "body")

    assert kb_with_outside_secret.read_article("wiki/concept/a.md") == "body"
    assert kb_with_outside_secret.read_article("wiki/concept/../concept/a.md") == "body"


def test_guard_rejects_a_symlinked_subtree_escaping_the_kb(tmp_path: Path):
    """_resolve follows symlinks by design: a link planted under the KB is exactly
    the case worth rejecting, and this differs from the Go layer's lexical check."""
    kb = tmp_path / "kb"
    (kb / "wiki").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.md").write_text("OUTSIDE", encoding="utf-8")
    (kb / "wiki" / "linked").symlink_to(outside)
    store = KBStore(str(kb))

    with pytest.raises(ValueError, match="escapes kb_dir"):
        store.read_article("wiki/linked/o.md")


@pytest.mark.parametrize("self_path", ["", ".", "wiki/.."])
def test_guard_rejects_the_kb_root_itself(kb_with_outside_secret, self_path):
    """Every caller addresses a file; resolving to base_dir would let write_article
    replace the KB directory with a regular file."""
    with pytest.raises(ValueError, match="escapes kb_dir"):
        kb_with_outside_secret.read_article(self_path)
