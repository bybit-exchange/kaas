"""Offline tests for people stub generation (kb_ai.core.people).

Covers the pure helpers (slugging, wikilink target extraction, title/stub
detection) and the update_people_stubs scan, including the rule that a
hand-written biography is never overwritten by a generated stub.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from kb_ai.core import people
from kb_ai.storage.store import KBStore

TODAY = date.today().isoformat()


def _make_kb(tmp_path: Path, articles: dict[str, str]) -> KBStore:
    store = KBStore(str(tmp_path))
    for rel, body in articles.items():
        store.write_article(rel, body)
    return store


def _stub_path(store: KBStore, slug: str) -> Path:
    return store.wiki_dir / "people" / f"{slug}.md"


# ── _slug ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("Grace Hopper", "grace-hopper"),
    ("grace hopper", "grace-hopper"),
    ("Ada Lovelace", "ada-lovelace"),
    ("O'Brien", "obrien"),
    ("Jean-Luc Picard", "jean-luc-picard"),
    ("under_score", "under-score"),
    ("  Padded  Name  ", "padded-name"),
    ("Multiple   Spaces", "multiple-spaces"),
    ("Name123", "name123"),
    ("!!!", ""),
    ("", ""),
])
def test_slug(name, expected):
    assert people._slug(name) == expected


def test_slug_drops_non_alphanumeric_punctuation():
    assert people._slug("Dr. Jane Doe, PhD") == "dr-jane-doe-phd"


# ── _extract_target ─────────────────────────────────────────────────

@pytest.mark.parametrize("body,expected", [
    ("Grace Hopper", "Grace Hopper"),
    ("Grace Hopper|Grace", "Grace Hopper"),
    ("  Padded  ", "Padded"),
    ("Target | Display", "Target"),
    ("a|b|c", "a"),
])
def test_extract_target(body, expected):
    assert people._extract_target(body) == expected


# ── _article_title ──────────────────────────────────────────────────

def test_article_title_from_frontmatter():
    content = '---\ntitle: "My Article"\n---\n\nbody'
    assert people._article_title(Path("/kb/wiki/a.md"), content) == "My Article"


@pytest.mark.parametrize("content", [
    "no frontmatter here",
    "---\nauthor: someone\n---\nbody",          # frontmatter without a title
    "---\nincomplete frontmatter",              # no closing delimiter
    "---\n: : not valid yaml : :\n---\nbody",   # unparseable frontmatter
])
def test_article_title_falls_back_to_filename(content):
    assert people._article_title(Path("/kb/wiki/fallback.md"), content) == "fallback"


def test_article_title_coerces_non_string_title():
    content = "---\ntitle: 2026\n---\nbody"
    assert people._article_title(Path("/kb/wiki/a.md"), content) == "2026"


# ── _is_stub ────────────────────────────────────────────────────────

def test_is_stub_detects_sentinel():
    content = f"---\ntitle: X\n---\n{people.STUB_SENTINEL}\n\nbody"
    assert people._is_stub(content) is True


@pytest.mark.parametrize("content", [
    "no frontmatter",
    "---\ntitle: X\n---\nA hand-written biography.",
    "---\nincomplete",
    f"{people.STUB_SENTINEL}\nno frontmatter around it",
])
def test_is_stub_rejects_non_stubs(content):
    assert people._is_stub(content) is False


# ── _existing_created ───────────────────────────────────────────────

def test_existing_created_reads_frontmatter(tmp_path):
    p = tmp_path / "x.md"
    p.write_text("---\ncreated: 2025-01-01\nupdated: 2026-01-01\n---\nbody")
    assert people._existing_created(p) == "2025-01-01"


@pytest.mark.parametrize("content", [
    "no frontmatter",
    "---\nupdated: 2026-01-01\n---\nbody",   # no created key
    "---\nincomplete",
    "---\n: : bad yaml : :\n---\nbody",
])
def test_existing_created_returns_none(tmp_path, content):
    p = tmp_path / "x.md"
    p.write_text(content)
    assert people._existing_created(p) is None


def test_existing_created_missing_file(tmp_path):
    assert people._existing_created(tmp_path / "nope.md") is None


# ── update_people_stubs ─────────────────────────────────────────────

def test_update_people_stubs_generates_stub(tmp_path):
    store = _make_kb(tmp_path, {
        "wiki/notes/meeting.md": '---\ntitle: "Weekly Sync"\n---\n\n[[Grace Hopper]] led the review.',
    })

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace Hopper"]}])

    stub = _stub_path(store, "grace-hopper")
    assert stub.exists()
    content = stub.read_text()
    assert people.STUB_SENTINEL in content
    assert 'title: "Grace Hopper"' in content
    assert "type: person" in content
    assert "mentions: 1" in content
    assert "[Weekly Sync](wiki/notes/meeting.md)" in content
    assert f"created: {TODAY}" in content
    assert f"updated: {TODAY}" in content


def test_update_people_stubs_matches_aliases_case_insensitively(tmp_path):
    store = _make_kb(tmp_path, {
        "wiki/a.md": "[[grace hopper]] and [[GRACE]] and [[Grace Hopper]]",
    })

    people.update_people_stubs(store, [
        {"canonical": "Grace Hopper", "aliases": ["Grace Hopper", "Grace"]},
    ])

    content = _stub_path(store, "grace-hopper").read_text()
    assert "mentions: 3" in content
    # Aliases are recorded with the casing from config, not from the article.
    assert 'aliases: ["Grace", "Grace Hopper"]' in content


def test_update_people_stubs_counts_every_mention_but_dedupes_sources(tmp_path):
    store = _make_kb(tmp_path, {
        "wiki/a.md": "[[Grace]] met [[Grace]] twice",
        "wiki/b.md": "[[Grace]] once",
    })

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace"]}])

    content = _stub_path(store, "grace-hopper").read_text()
    assert "mentions: 3" in content
    assert content.count("wiki/a.md") == 2   # once under sources, once in the list
    assert content.count("wiki/b.md") == 2


def test_update_people_stubs_resolves_piped_wikilinks(tmp_path):
    store = _make_kb(tmp_path, {"wiki/a.md": "[[Grace Hopper|the architect]] spoke"})

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace Hopper"]}])

    assert _stub_path(store, "grace-hopper").exists()


def test_update_people_stubs_ignores_unlisted_names(tmp_path):
    store = _make_kb(tmp_path, {"wiki/a.md": "[[Someone Else]] appeared"})

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace"]}])

    assert not (store.wiki_dir / "people").exists()


def test_update_people_stubs_skips_people_without_mentions(tmp_path):
    store = _make_kb(tmp_path, {"wiki/a.md": "[[Grace]] only"})

    people.update_people_stubs(store, [
        {"canonical": "Grace Hopper", "aliases": ["Grace"]},
        {"canonical": "Ada Lovelace", "aliases": ["Ada"]},
    ])

    assert _stub_path(store, "grace-hopper").exists()
    assert not _stub_path(store, "ada-lovelace").exists()


def test_update_people_stubs_does_not_scan_the_people_dir(tmp_path):
    """Stubs cross-reference each other; counting those links would inflate
    mention counts on every run."""
    store = _make_kb(tmp_path, {
        "wiki/a.md": "[[Grace]] appears once",
        "wiki/people/ada-lovelace.md": "[[Grace]] mentioned inside another stub",
    })

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace"]}])

    content = _stub_path(store, "grace-hopper").read_text()
    assert "mentions: 1" in content


def test_update_people_stubs_preserves_handwritten_bio(tmp_path):
    store = _make_kb(tmp_path, {"wiki/a.md": "[[Grace]] appears"})
    stub = _stub_path(store, "grace-hopper")
    stub.parent.mkdir(parents=True, exist_ok=True)
    handwritten = "---\ntitle: Grace Hopper\n---\nA carefully written biography."
    stub.write_text(handwritten)

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace"]}])

    assert stub.read_text() == handwritten


def test_update_people_stubs_regenerates_existing_stub_preserving_created(tmp_path):
    store = _make_kb(tmp_path, {"wiki/a.md": "[[Grace]] and [[Grace]] again"})
    stub = _stub_path(store, "grace-hopper")
    stub.parent.mkdir(parents=True, exist_ok=True)
    stub.write_text(
        f"---\ntitle: \"Grace Hopper\"\nmentions: 1\ncreated: 2024-03-01\n"
        f"updated: 2024-03-01\n---\n{people.STUB_SENTINEL}\n\nold body\n"
    )

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace"]}])

    content = stub.read_text()
    assert "created: 2024-03-01" in content     # original creation date kept
    assert f"updated: {TODAY}" in content        # refreshed
    assert "mentions: 2" in content              # recounted
    assert "old body" not in content


@pytest.mark.parametrize("cfg", [None, []])
def test_update_people_stubs_noop_without_config(tmp_path, cfg):
    store = _make_kb(tmp_path, {"wiki/a.md": "[[Grace]] appears"})

    people.update_people_stubs(store, cfg)

    assert not (store.wiki_dir / "people").exists()


def test_update_people_stubs_noop_without_wiki_dir(tmp_path):
    store = KBStore(str(tmp_path))   # nothing written, so wiki/ does not exist

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace"]}])

    assert not store.wiki_dir.exists()


def test_update_people_stubs_handles_person_without_aliases(tmp_path):
    """A config entry with no aliases contributes no lookup keys, so the person
    is never matched — not an error."""
    store = _make_kb(tmp_path, {"wiki/a.md": "[[Grace Hopper]] appears"})

    people.update_people_stubs(store, [{"canonical": "Grace Hopper"}])

    assert not _stub_path(store, "grace-hopper").exists()


def test_update_people_stubs_sorts_sources_by_title(tmp_path):
    store = _make_kb(tmp_path, {
        "wiki/z.md": '---\ntitle: "Alpha"\n---\n[[Grace]]',
        "wiki/a.md": '---\ntitle: "Zulu"\n---\n[[Grace]]',
    })

    people.update_people_stubs(store, [{"canonical": "Grace Hopper", "aliases": ["Grace"]}])

    content = _stub_path(store, "grace-hopper").read_text()
    assert content.index("[Alpha]") < content.index("[Zulu]")
