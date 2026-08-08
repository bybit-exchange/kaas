"""Tests for kb_ai.storage.index — frontmatter skip rules, the primary/longtail
topic split, and the append-only timeline.

All writes land under tmp_path; no network and no real HOME / kb directory.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from kb_ai.core.extract import ExtractionResult
from kb_ai.storage import extraction as exl
from kb_ai.storage import index as index_mod
from kb_ai.storage.index import (
    DOCUMENT_INDEX_NAME,
    build_document_catalog,
    update_document_index,
    update_markdown_index,
    update_timeline,
)
from kb_ai.storage.store import KBStore, _compute_checksum


def _store(tmp_path: Path) -> KBStore:
    return KBStore(str(tmp_path))


def _write(store: KBStore, rel: str, content: str) -> None:
    full = store.base_dir / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")


def _master(store: KBStore) -> str:
    return (store.index_dir / "master-index.md").read_text(encoding="utf-8")


def _topic(store: KBStore) -> str:
    return (store.index_dir / "topic-index.md").read_text(encoding="utf-8")


def _longtail(store: KBStore) -> str:
    return (store.index_dir / "topic-index-longtail.md").read_text(encoding="utf-8")


# ── frontmatter skip rules ──────────────────────────────────────────

def test_index_skips_article_without_frontmatter(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/plain.md", "# Plain\n\nno frontmatter at all")
    _write(store, "wiki/good.md", "---\ntitle: Good\n---\n\nbody")

    update_markdown_index(store)

    assert "Good" in _master(store)
    assert "plain.md" not in _master(store)


def test_index_skips_article_with_unterminated_frontmatter(tmp_path: Path):
    """Starts with --- but never closes the block, so split yields < 3 parts."""
    store = _store(tmp_path)
    _write(store, "wiki/broken.md", "---\ntitle: Broken\nstill frontmatter")
    _write(store, "wiki/good.md", "---\ntitle: Good\n---\n\nbody")

    update_markdown_index(store)

    assert "Good" in _master(store)
    assert "broken.md" not in _master(store)
    assert "Broken" not in _master(store)


def test_index_skips_article_with_invalid_yaml_frontmatter(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/bad.md", "---\ntitle: [unclosed\n---\n\nbody")
    _write(store, "wiki/good.md", "---\ntitle: Good\n---\n\nbody")

    update_markdown_index(store)

    assert "Good" in _master(store)
    assert "bad.md" not in _master(store)


def test_index_survives_all_articles_being_skipped(tmp_path: Path):
    """Every candidate skipped -> still writes an empty-but-valid index set."""
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "no frontmatter")
    _write(store, "wiki/b.md", "---\nunterminated")

    update_markdown_index(store)

    assert _master(store) == "# Knowledge Base Index\n\n"
    assert "- [" not in _topic(store)
    assert "- [" not in _longtail(store)


# ── master index rendering ──────────────────────────────────────────

def test_master_index_sorts_by_title_and_renders_status_marker(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/z.md", "---\ntitle: Zeta\nstatus: draft\n---\n\nzeta summary")
    _write(store, "wiki/a.md", "---\ntitle: Alpha\n---\n\nalpha summary")

    update_markdown_index(store)
    lines = [ln for ln in _master(store).splitlines() if ln.startswith("- [")]

    assert lines == [
        "- [Alpha](wiki/a.md) — alpha summary",
        "- [Zeta](wiki/z.md) [draft] — zeta summary",
    ]


def test_master_index_summary_is_first_paragraph_capped(tmp_path: Path):
    store = _store(tmp_path)
    body = "w" * 400
    _write(store, "wiki/a.md", f"---\ntitle: A\n---\n\n{body}\n\nsecond paragraph")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))
    summary = line.split("—", 1)[1].strip()

    assert summary == "w" * index_mod.SUMMARY_MAX_CHARS
    assert "second paragraph" not in line


def test_master_index_summary_skips_leading_headings(tmp_path: Path):
    """Compiled articles open with a heading, which must not become the summary.

    The catalog summary is the only content-bearing column LLM page selection
    reads; echoing the heading collapses the navigation surface to titles alone.
    """
    store = _store(tmp_path)
    _write(store, "wiki/a.md",
           "---\ntitle: A\n---\n\n# A\n\n## Overview\n\nLoads TOML config and applies env overrides.")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line == "- [A](wiki/a.md) — Loads TOML config and applies env overrides."


def test_master_index_summary_skips_heading_glued_to_its_paragraph(tmp_path: Path):
    """A heading with no blank line after it shares a block with the prose."""
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: A\n---\n\n## Overview\nReal prose here.")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line == "- [A](wiki/a.md) — Real prose here."


def test_master_index_prefers_frontmatter_summary(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md",
           '---\ntitle: A\nsummary: "Declared one-liner."\n---\n\n# A\n\nBody prose.')

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line == "- [A](wiki/a.md) — Declared one-liner."


def test_master_index_frontmatter_summary_is_flattened_and_capped(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", f'---\ntitle: A\nsummary: "{"w" * 400}"\n---\n\nbody')

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line == f"- [A](wiki/a.md) — {'w' * index_mod.SUMMARY_MAX_CHARS}"


def test_master_index_summary_clips_at_a_word_boundary(tmp_path: Path):
    store = _store(tmp_path)
    body = " ".join(["configuration"] * 20)  # 279 chars, boundary before the cap
    _write(store, "wiki/a.md", f"---\ntitle: A\n---\n\n{body}")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))
    summary = line.split("—", 1)[1].strip()

    assert summary == " ".join(["configuration"] * 14) + "…"
    assert len(summary) <= index_mod.SUMMARY_MAX_CHARS


def test_master_index_ignores_blank_frontmatter_summary(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", '---\ntitle: A\nsummary: "   "\n---\n\nBody prose.')

    update_markdown_index(store)

    assert "- [A](wiki/a.md) — Body prose." in _master(store)


def test_master_index_summary_falls_back_to_heading_text_for_heading_only_body(tmp_path: Path):
    """No prose at all -> keep the heading text rather than an empty column."""
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: A\n---\n\n## Overview\n\n### Details")

    update_markdown_index(store)

    assert "- [A](wiki/a.md) — Overview" in _master(store)


# ── configurable summary budget ──────────────────────────────────────

def test_summary_budget_is_configurable_per_call(tmp_path: Path):
    """A knowledge base whose catalog outgrows the selection prompt needs to trade
    summary length for article count without patching the module."""
    store = _store(tmp_path)
    _write(store, "wiki/a.md", f"---\ntitle: A\n---\n\n{'w' * 200}")

    update_markdown_index(store, summary_max_chars=60)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line == f"- [A](wiki/a.md) — {'w' * 60}"


def test_summary_budget_defaults_to_the_module_constant(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", f"---\ntitle: A\n---\n\n{'w' * 400}")

    update_markdown_index(store)
    summary = _master(store).split("—", 1)[1].strip()

    assert len(summary) == index_mod.SUMMARY_MAX_CHARS == 200


def test_summary_budget_also_caps_a_declared_frontmatter_summary(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", f'---\ntitle: A\nsummary: "{"w" * 200}"\n---\n\nbody')

    update_markdown_index(store, summary_max_chars=80)
    summary = _master(store).split("—", 1)[1].strip()

    assert summary == "w" * 80


def test_summary_budget_does_not_affect_the_keys_column(tmp_path: Path):
    """The keys column has its own budget: shrinking summaries to fit a large
    catalog must not throw away the identifiers narrow queries match on."""
    store = _store(tmp_path)
    _write(store, "wiki/a.md",
           f"---\ntitle: A\n---\n\n{'w' * 200}\n\n| `max_zip_entries` | `200` |\n")

    update_markdown_index(store, summary_max_chars=40)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line == f"- [A](wiki/a.md) — {'w' * 40} | keys: max_zip_entries"


# ── keys column ─────────────────────────────────────────────────────

_CONFIG_TABLE = (
    "---\ntitle: Config\n---\n\n## Overview\n\nRuntime settings for the backend.\n\n"
    "| Field            | Default | Description        |\n"
    "|------------------|---------|--------------------|\n"
    "| `max_zip_entries` | `200`  | entries per zip    |\n"
    "| `max_file_size`   | `10MB` | per-file cap       |\n"
)


def test_master_index_lists_table_keys_of_a_reference_article(tmp_path: Path):
    """The values a reference table documents are the retrieval signal, and a
    150-char prose summary cannot carry them."""
    store = _store(tmp_path)
    _write(store, "wiki/config.md", _CONFIG_TABLE)

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line == ("- [Config](wiki/config.md) — Runtime settings for the backend. "
                    "| keys: max_zip_entries, max_file_size")


def test_master_index_omits_the_keys_column_for_prose_articles(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: A\n---\n\nAll prose, no table.")

    update_markdown_index(store)

    assert "- [A](wiki/a.md) — All prose, no table." in _master(store)
    assert "keys:" not in _master(store)


def test_master_index_keys_skip_non_identifier_first_cells(tmp_path: Path):
    """Header rows, separator rows and prose cells are not keys; a backticked
    single token (env var, flag, endpoint) is."""
    store = _store(tmp_path)
    _write(store, "wiki/a.md",
           "---\ntitle: A\n---\n\nprose\n\n"
           "| Setting | Meaning |\n"
           "|---------|---------|\n"
           "| `KAAS_HOME` | state dir |\n"
           "| `--dry-run` | no writes |\n"
           "| plain text | not a key |\n"
           "| `two words here` | not a key either |\n")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line.endswith("| keys: KAAS_HOME, --dry-run")


def test_master_index_keys_dedup_in_document_order(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md",
           "---\ntitle: A\n---\n\nprose\n\n"
           "| `zulu` | x |\n| `alpha` | y |\n| `zulu` | z |\n")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line.endswith("| keys: zulu, alpha")


def test_master_index_keys_are_capped_without_splitting_a_key(tmp_path: Path):
    """A pathological table must not blow up every retrieval prompt, and a
    half-written key would be a false signal rather than a partial one."""
    store = _store(tmp_path)
    rows = "".join(f"| `key_{i:03d}` | v |\n" for i in range(200))
    _write(store, "wiki/a.md", f"---\ntitle: A\n---\n\nprose\n\n{rows}")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))
    keys = line.split("| keys: ", 1)[1]

    assert len(keys) <= index_mod.KEYS_MAX_CHARS
    assert keys.endswith(", …")
    # Every listed key is whole: no "key_0" fragment left by the cut.
    assert all(len(k.strip()) == len("key_000")
               for k in keys.removesuffix(", …").split(","))


def test_master_index_drops_a_single_key_that_exceeds_the_budget(tmp_path: Path):
    """No key fits -> no column, rather than a lone cut marker."""
    store = _store(tmp_path)
    monster = "k" * (index_mod.KEYS_MAX_CHARS + 1)
    _write(store, "wiki/a.md", f"---\ntitle: A\n---\n\nprose\n\n| `{monster}` | v |\n")

    update_markdown_index(store)

    assert "- [A](wiki/a.md) — prose" in _master(store)
    assert "keys:" not in _master(store)


def test_master_index_keys_survive_a_summary_containing_pipes(tmp_path: Path):
    """An article whose first prose block is itself a table row puts pipes in the
    summary; the keys column must still be separable from it."""
    store = _store(tmp_path)
    _write(store, "wiki/a.md",
           "---\ntitle: A\n---\n\n| `alpha` | first row is the only prose |\n")

    update_markdown_index(store)
    line = next(ln for ln in _master(store).splitlines() if ln.startswith("- ["))

    assert line.endswith("| keys: alpha")


def test_master_index_falls_back_to_stem_when_title_missing(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/my-note.md", "---\ntype: concept\n---\n\nbody")

    update_markdown_index(store)

    assert "- [my-note](wiki/my-note.md)" in _master(store)


# ── primary / longtail topic split ──────────────────────────────────

def test_topic_index_splits_primary_and_longtail_by_min_articles(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: A\ntags: [common, rare]\n---\n\na body")
    _write(store, "wiki/b.md", "---\ntitle: B\ntags: [common]\n---\n\nb body")

    update_markdown_index(store, min_articles=2)

    primary = _topic(store)
    longtail = _longtail(store)
    assert "## common (2)" in primary
    assert "## rare" not in primary
    assert "## rare (1)" in longtail
    assert "## common" not in longtail
    # Articles are listed under their tag, title-sorted.
    common_block = primary.split("## common (2)")[1]
    assert common_block.index("[A](wiki/a.md)") < common_block.index("[B](wiki/b.md)")


def test_longtail_tags_are_alphabetical(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: A\ntags: [zebra, apple, mango]\n---\n\nbody")

    update_markdown_index(store, min_articles=2)
    headings = [ln for ln in _longtail(store).splitlines() if ln.startswith("## ")]

    assert headings == ["## apple (1)", "## mango (1)", "## zebra (1)"]


def test_primary_tags_sort_by_count_desc_then_name_asc(tmp_path: Path):
    store = _store(tmp_path)
    # "beta" and "alpha" both have 2 articles; "top" has 3.
    _write(store, "wiki/1.md", "---\ntitle: One\ntags: [top, beta, alpha]\n---\n\nbody")
    _write(store, "wiki/2.md", "---\ntitle: Two\ntags: [top, beta, alpha]\n---\n\nbody")
    _write(store, "wiki/3.md", "---\ntitle: Three\ntags: [top]\n---\n\nbody")

    update_markdown_index(store, min_articles=2)
    headings = [ln for ln in _topic(store).splitlines() if ln.startswith("## ")]

    assert headings == ["## top (3)", "## alpha (2)", "## beta (2)"]


def test_topic_index_headers_mention_min_articles_threshold(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: A\ntags: [x]\n---\n\nbody")

    update_markdown_index(store, min_articles=4)

    assert "at least 4 articles" in _topic(store)
    assert "fewer than 4 articles" in _longtail(store)


def test_index_rebuild_drops_articles_deleted_since_last_run(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: A\ntags: [x]\n---\n\na body")
    _write(store, "wiki/b.md", "---\ntitle: B\ntags: [x]\n---\n\nb body")
    update_markdown_index(store, min_articles=2)
    assert "## x (2)" in _topic(store)

    (store.base_dir / "wiki/b.md").unlink()
    update_markdown_index(store, min_articles=2)

    assert "[B](wiki/b.md)" not in _master(store)
    assert "## x (2)" not in _topic(store)
    assert "## x (1)" in _longtail(store)   # demoted to long tail


def test_index_includes_nested_wiki_subdirectories(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/people/grace.md", "---\ntitle: Grace\n---\n\nprofile")

    update_markdown_index(store)

    assert "- [Grace](wiki/people/grace.md)" in _master(store)


# ── update_timeline ─────────────────────────────────────────────────

class _FrozenNow:
    """Stand-in for `datetime` whose now() is fixed, for stable assertions."""

    @staticmethod
    def now():
        return SimpleNamespace(strftime=lambda _fmt: "2026-01-02 03:04")


def test_timeline_creates_file_with_header_and_entries(tmp_path: Path):
    store = _store(tmp_path)

    update_timeline(store, ["raw/a.md", "raw/b.md"])
    text = (store.index_dir / "timeline.md").read_text(encoding="utf-8")

    assert text.startswith("# Knowledge Timeline\n\n")
    assert "- Compiled: `raw/a.md`\n" in text
    assert "- Compiled: `raw/b.md`\n" in text


def test_timeline_stamps_section_with_current_time(tmp_path: Path, monkeypatch):
    store = _store(tmp_path)
    monkeypatch.setattr(index_mod, "datetime", _FrozenNow)

    update_timeline(store, ["raw/a.md"])

    assert "## 2026-01-02 03:04\n" in (store.index_dir / "timeline.md").read_text(
        encoding="utf-8")


def test_timeline_appends_without_dropping_earlier_sections(tmp_path: Path):
    store = _store(tmp_path)

    update_timeline(store, ["raw/first.md"])
    update_timeline(store, ["raw/second.md"])
    text = (store.index_dir / "timeline.md").read_text(encoding="utf-8")

    assert text.count("# Knowledge Timeline") == 1     # header written once
    assert text.count("## ") == 2                      # one section per run
    assert "raw/first.md" in text and "raw/second.md" in text
    assert text.index("raw/first.md") < text.index("raw/second.md")


def test_timeline_with_no_sources_still_appends_a_section(tmp_path: Path):
    store = _store(tmp_path)

    update_timeline(store, [])
    text = (store.index_dir / "timeline.md").read_text(encoding="utf-8")

    assert text.count("## ") == 1
    assert "Compiled:" not in text


def test_timeline_creates_index_dir_when_absent(tmp_path: Path):
    store = _store(tmp_path)
    assert not store.index_dir.exists()

    update_timeline(store, ["raw/a.md"])

    assert (store.index_dir / "timeline.md").exists()


# ── regression guards for fixed bugs ─────────────────────────────────

def test_index_skips_article_with_empty_frontmatter(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "wiki/empty-fm.md", "---\n---\n\nbody")
    _write(store, "wiki/good.md", "---\ntitle: Good\n---\n\nbody")

    update_markdown_index(store)

    assert "Good" in _master(store)


@pytest.mark.parametrize("bad_frontmatter", [
    "---\n---\n\nbody",            # empty block -> yaml returns None
    "---\njust a scalar\n---\nbody",  # scalar block -> yaml returns str
    "---\n- a\n- b\n---\nbody",    # sequence block -> yaml returns list
])
def test_index_skips_non_mapping_frontmatter_without_losing_good_articles(
    tmp_path: Path, bad_frontmatter: str
):
    """A non-mapping frontmatter used to raise AttributeError and abort the whole
    rebuild; it must be skipped like the other malformed cases instead."""
    store = _store(tmp_path)
    _write(store, "wiki/bad-fm.md", bad_frontmatter)
    _write(store, "wiki/good.md", "---\ntitle: Good\n---\n\nbody")

    update_markdown_index(store)

    index = _master(store)
    assert "Good" in index
    assert "bad-fm" not in index


# ── document index ──────────────────────────────────────────────────

def _documents(store: KBStore) -> str:
    return (store.index_dir / DOCUMENT_INDEX_NAME).read_text(encoding="utf-8")


def _extraction(store: KBStore, rel_path: str, content: str, summary: str) -> None:
    """Seed the extraction file a compiled document would have."""
    exl.persist(store, rel_path, ExtractionResult(summary=summary),
                source_checksum=_compute_checksum(content), extract_model="m")


def test_document_index_prefers_the_extraction_summary(tmp_path: Path):
    """The document-level summary already exists under extraction/; reuse it
    rather than paying an LLM to summarise the document again."""
    store = _store(tmp_path)
    content = "---\ntitle: Weekly Standup\ndate: 2026-06-03\nsource: lark\n---\n\nWe shipped the retry queue."
    _write(store, "raw/2026-06/standup.md", content)
    _extraction(store, "raw/2026-06/standup.md", content,
                "The team shipped the retry queue and deferred the dashboard.")

    update_document_index(store)

    line = _documents(store)
    assert "raw/2026-06/standup.md" in line
    assert "Weekly Standup" in line
    assert "shipped the retry queue and deferred the dashboard" in line


def test_document_index_prefers_a_declared_frontmatter_summary(tmp_path: Path):
    """A hand-written summary beats the extraction: it was written to be the line."""
    store = _store(tmp_path)
    content = "---\ntitle: Standup\nsummary: Retry queue rollout decision\n---\n\nbody text"
    _write(store, "raw/a.md", content)
    _extraction(store, "raw/a.md", content, "extracted wording that should lose")

    update_document_index(store)

    assert "Retry queue rollout decision" in _documents(store)
    assert "extracted wording" not in _documents(store)


def test_document_index_falls_back_to_the_body_when_uncompiled(tmp_path: Path):
    """A KB that was never compiled has no extraction; the catalog must still work."""
    store = _store(tmp_path)
    _write(store, "raw/a.md", "---\ntitle: Notes\n---\n\n# Heading\n\nThe actual first paragraph.")

    update_document_index(store)

    line = _documents(store)
    assert "The actual first paragraph." in line
    assert "Heading" not in line


def test_document_index_carries_date_and_source(tmp_path: Path):
    """date and source are free routing signals: every raw document has them, and
    in a cross-KB merge `source` says which person or channel a document came from."""
    store = _store(tmp_path)
    _write(store, "raw/a.md", "---\ntitle: Sync\ndate: 2026-06-03\nsource: lark\n---\n\nbody")

    update_document_index(store)

    line = _documents(store)
    assert "2026-06-03" in line
    assert "lark" in line


def test_document_index_caps_the_summary(tmp_path: Path):
    store = _store(tmp_path)
    content = "---\ntitle: Long\n---\n\n" + "word " * 500
    _write(store, "raw/a.md", content)

    update_document_index(store, summary_max_chars=80)

    body_line = [ln for ln in _documents(store).splitlines() if ln.startswith("- ")][0]
    assert len(body_line) < 200
    assert body_line.endswith("…")


def test_document_index_skips_the_skipped_dir(tmp_path: Path):
    """raw/_skipped/ holds documents moved out by cost review; they are not compiled
    and must not be selectable either."""
    store = _store(tmp_path)
    _write(store, "raw/keep.md", "---\ntitle: Keep\n---\n\nkeep me")
    _write(store, "raw/_skipped/drop.md", "---\ntitle: Drop\n---\n\ndrop me")

    update_document_index(store)

    assert "raw/keep.md" in _documents(store)
    assert "drop.md" not in _documents(store)


def test_document_index_handles_a_document_without_frontmatter(tmp_path: Path):
    """Unlike wiki articles, a raw document is not required to have frontmatter --
    skipping it would make the document unreachable rather than merely unlabelled."""
    store = _store(tmp_path)
    _write(store, "raw/plain.md", "just prose, no frontmatter at all")

    update_document_index(store)

    line = _documents(store)
    assert "raw/plain.md" in line
    assert "just prose" in line


def test_existing_documents_round_trips_the_written_index(tmp_path: Path):
    store = _store(tmp_path)
    _write(store, "raw/a.md", "---\ntitle: Alpha\nsummary: About alpha\n---\n\nbody")
    _write(store, "raw/b.md", "---\ntitle: Beta\nsummary: About beta\n---\n\nbody")

    update_document_index(store)
    docs = store.existing_documents()

    assert [d.path for d in docs] == ["raw/a.md", "raw/b.md"]
    assert docs[0].title == "Alpha"
    assert "About alpha" in docs[0].summary


def test_existing_documents_without_an_index(tmp_path: Path):
    assert _store(tmp_path).existing_documents() == []


def test_build_document_catalog_needs_no_write_access(tmp_path: Path):
    """derive opens a source KB read-only, and in a cross-KB selection that KB may
    belong to someone else and be genuinely unwritable. The catalog a topic filter
    consumes must therefore be computable without touching the KB at all."""
    store = _store(tmp_path)
    _write(store, "raw/a.md", "---\ntitle: Alpha\nsummary: About alpha\n---\n\nbody")

    catalog = build_document_catalog(KBStore(str(tmp_path), read_only=True))

    assert [d.path for d in catalog] == ["raw/a.md"]
    assert "About alpha" in catalog[0].summary
    assert not (store.index_dir / DOCUMENT_INDEX_NAME).exists()


def test_build_document_catalog_matches_what_the_index_round_trips(tmp_path: Path):
    """The in-memory catalog and the on-disk one must be the same selection input:
    otherwise which of the two derive used would change its results."""
    store = _store(tmp_path)
    _write(store, "raw/a.md", "---\ntitle: Alpha\ndate: 2026-06-03\nsource: lark\n---\n\nbody one")
    _write(store, "raw/b.md", "---\ntitle: Beta\n---\n\nbody two")

    in_memory = build_document_catalog(store)
    update_document_index(store)
    from_disk = store.existing_documents()

    assert [(d.path, d.title, d.summary) for d in in_memory] == \
           [(d.path, d.title, d.summary) for d in from_disk]


def test_index_command_builds_both_catalogs(tmp_path: Path):
    """The document catalog is rebuilt alongside the article one, so it cannot go
    stale relative to raw/ and a later derive pays nothing to read it."""
    from kb_ai.commands.pipeline._entry import run_server_index_with_input

    store = _store(tmp_path)
    _write(store, "wiki/a.md", "---\ntitle: Alpha\nsummary: An article\n---\n\nbody")
    _write(store, "raw/doc.md", "---\ntitle: Doc\n---\n\nA raw document.")

    run_server_index_with_input({"kb_dir": str(tmp_path)})

    assert "wiki/a.md" in _master(store)
    assert "raw/doc.md" in _documents(store)


def test_document_index_tolerates_broken_frontmatter(tmp_path: Path):
    """Malformed YAML must leave the document unlabelled, not unselectable -- the
    opposite of the article index, which skips such a file entirely."""
    store = _store(tmp_path)
    _write(store, "raw/bad.md", "---\ntitle: [unclosed\n---\n\nThe body still routes.")

    update_document_index(store)

    line = _documents(store)
    assert "raw/bad.md" in line
    assert "The body still routes." in line


def test_document_index_reports_documents_with_no_extraction(tmp_path: Path, capsys):
    """E2: the first-paragraph fallback is materially worse, so it is not silent."""
    store = _store(tmp_path)
    content = "---\ntitle: A\n---\n\nfirst paragraph of a"
    _write(store, "raw/a.md", content)
    _write(store, "raw/b.md", "---\ntitle: B\n---\n\nfirst paragraph of b")
    _extraction(store, "raw/a.md", content, "the extracted summary")

    update_document_index(store)

    err = capsys.readouterr().err
    assert "1 of 2 documents have no extraction yet" in err
    line = _documents(store)
    assert "the extracted summary" in line
    assert "first paragraph of b" in line


def test_document_index_ignores_an_orphan_extraction(tmp_path: Path):
    """E1: a lookup keyed by the raw path, not a fold over extraction/.

    A deleted or renamed document leaves its extraction behind, and folding over
    the directory would list it as a document that no longer exists.
    """
    store = _store(tmp_path)
    _write(store, "raw/a.md", "---\ntitle: A\n---\n\nbody a")
    _extraction(store, "raw/gone.md", "old body", "summary of a deleted document")

    update_document_index(store)

    line = _documents(store)
    assert "raw/gone.md" not in line
    assert "summary of a deleted document" not in line


def test_document_index_reads_a_nested_documents_extraction(tmp_path: Path):
    store = _store(tmp_path)
    content = "---\ntitle: Deep\n---\n\nbody"
    _write(store, "raw/2026-06/deep/note.md", content)
    _extraction(store, "raw/2026-06/deep/note.md", content, "nested summary")

    update_document_index(store)

    assert "nested summary" in _documents(store)
