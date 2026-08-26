"""Tests for kb_ai.core.classify — verifies new import paths and basic logic."""
from __future__ import annotations

from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core.classify import (
    CATEGORY_DEFINITIONS,
    DEFAULT_CATEGORIES,
    category_definitions_block,
    classify_article,
    classify_cache_key,
    classify_inputs_hash,
    dedup_create_new,
    hash_existing_articles,
    resolve_categories,
)
from kb_ai.core.extract import ExtractionResult
from kb_ai import prompts as prompts_module
from kb_ai.prompts import default_registry
from kb_ai.storage.store import ArticleMeta, KBStore


def test_classify_importable_from_core():
    """classify_article is importable from kb_ai.core.classify."""
    assert callable(classify_article)


def test_default_categories_hold_the_measured_six():
    """The default menu is the six measured in docs/classify-taxonomy-measurements.md.

    `reference` and `guide` were absent from the original four despite taking the
    right documents; `person` is retained for core/people.py even though a
    docs-only corpus never selects it.
    """
    assert DEFAULT_CATEGORIES == [
        "concept", "decision", "project", "reference", "guide", "person",
    ]
    # categories[0] is substituted into the prompt's example path, so the first
    # entry has to be a real category name.
    assert DEFAULT_CATEGORIES[0] in CATEGORY_DEFINITIONS


def test_every_default_category_has_a_definition():
    """A default category without a definition would leave the model guessing."""
    missing = [c for c in DEFAULT_CATEGORIES if c not in CATEGORY_DEFINITIONS]
    assert missing == []


def test_definitions_block_covers_only_known_categories():
    """A custom menu gets no definitions rather than wrong ones."""
    block = category_definitions_block(["concept", "sprint", "okr"])
    assert "concept:" in block
    assert "sprint" not in block and "okr" not in block


def test_definitions_block_is_empty_for_a_wholly_custom_menu():
    """Nothing is injected when no active category has a known definition."""
    assert category_definitions_block(["sprint", "okr"]) == ""


def test_classify_prompt_renders_the_definitions():
    """The rendered prompt carries the definitions and keeps its placeholder."""
    rendered = default_registry().get("classify").render(
        categories_str=", ".join(DEFAULT_CATEGORIES),
        categories=DEFAULT_CATEGORIES,
        category_definitions=category_definitions_block(DEFAULT_CATEGORIES),
    )
    assert "Category definitions" in rendered
    assert CATEGORY_DEFINITIONS["project"] in rendered
    assert "{ARTICLES_PLACEHOLDER}" in rendered


def test_dedup_create_new_no_overlap():
    """dedup_create_new keeps items with no title overlap."""
    classification = ClassificationResult(
        create_new=[CreateTarget(title="Brand New Topic", path="wiki/concept/new.md")],
        merge_into=[],
    )
    existing = [ArticleMeta(title="Unrelated", path="wiki/concept/old.md")]
    result = dedup_create_new(classification, existing)
    assert len(result.create_new) == 1
    assert result.create_new[0].title == "Brand New Topic"


def test_hash_existing_articles_deterministic():
    """hash_existing_articles produces consistent hash for same input."""
    articles = [
        ArticleMeta(title="A", path="wiki/a.md", summary="x"),
        ArticleMeta(title="B", path="wiki/b.md", summary="y"),
    ]
    h1 = hash_existing_articles(articles)
    h2 = hash_existing_articles(articles)
    assert h1 == h2
    assert len(h1) == 12


def test_classify_cache_key_format():
    """classify_cache_key joins components with dashes."""
    key = classify_cache_key("abc123", "art456", "cat789")
    assert key == "abc123-art456-cat789"


# ── classify_inputs_hash: what must move the cache ──────────────────

def test_inputs_hash_is_stable_for_the_same_categories():
    assert classify_inputs_hash(["concept"]) == classify_inputs_hash(["concept"])


def test_inputs_hash_moves_when_the_category_list_changes():
    assert classify_inputs_hash(["concept"]) != classify_inputs_hash(["concept", "guide"])


def test_inputs_hash_treats_an_empty_category_list_as_the_defaults():
    """compile_kb passes categories=None and hashed it as `[]`, but
    classify_article falls back to the defaults -- so the old key described a run
    that never happened. Both falsy forms must hash as the defaults."""
    assert classify_inputs_hash(None) == classify_inputs_hash(DEFAULT_CATEGORIES)
    assert classify_inputs_hash([]) == classify_inputs_hash(DEFAULT_CATEGORIES)


def test_inputs_hash_moves_when_the_prompt_text_changes(monkeypatch, tmp_path):
    """Editing classify.md must invalidate the cache. Without this, a prompt-only
    edit leaves every cached classification in place and the edit does nothing."""
    before = classify_inputs_hash(["concept"])

    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    original = default_registry().get("classify").content
    (prompts_dir / "classify.md").write_text(
        original + "\nAn extra instruction that changes the model's behaviour.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KAAS_PROMPTS_DIR", str(prompts_dir))
    monkeypatch.setattr(prompts_module, "_registry", None)

    assert classify_inputs_hash(["concept"]) != before


def test_inputs_hash_moves_when_a_category_definition_changes(monkeypatch):
    """The definitions live in code, not in the prompt file, and the old
    categories-only hash could not see an edit to them."""
    before = classify_inputs_hash(["concept"])
    monkeypatch.setitem(CATEGORY_DEFINITIONS, "concept", "a completely different meaning")

    assert classify_inputs_hash(["concept"]) != before


# ── resolve_categories: freeze at creation, warn on conflict ─────────

def test_resolve_freezes_the_defaults_on_a_kb_without_config(tmp_path):
    store = KBStore(str(tmp_path))

    resolved = resolve_categories(store, None)

    assert resolved == DEFAULT_CATEGORIES
    assert store.load_config()["categories"] == DEFAULT_CATEGORIES


def test_resolve_freezes_an_explicit_set_on_a_kb_without_config(tmp_path):
    store = KBStore(str(tmp_path))

    resolved = resolve_categories(store, ["concept", "guide"])

    assert resolved == ["concept", "guide"]
    assert store.load_config()["categories"] == ["concept", "guide"]


def test_resolve_records_when_the_set_was_frozen(tmp_path):
    store = KBStore(str(tmp_path))
    resolve_categories(store, ["concept"])

    assert store.load_config()["categories_frozen_at"]


def test_resolve_returns_the_frozen_set_when_the_caller_passes_none(tmp_path):
    """The whole point of freezing: later runs inherit the creation-time set
    rather than silently picking up a changed DEFAULT_CATEGORIES."""
    store = KBStore(str(tmp_path))
    store.save_config({"categories": ["concept", "guide"]})

    assert resolve_categories(store, None) == ["concept", "guide"]


def test_resolve_does_not_rewrite_an_existing_frozen_set(tmp_path):
    store = KBStore(str(tmp_path))
    store.save_config({"categories": ["concept"], "categories_frozen_at": "2020-01-01T00:00:00Z"})

    resolve_categories(store, None)

    assert store.load_config()["categories_frozen_at"] == "2020-01-01T00:00:00Z"


def test_resolve_honours_a_conflicting_explicit_set_but_warns(tmp_path, capsys):
    store = KBStore(str(tmp_path))
    store.save_config({"categories": ["concept"]})

    resolved = resolve_categories(store, ["project", "guide"])

    assert resolved == ["project", "guide"]
    err = capsys.readouterr().err
    assert "[config]" in err
    assert "concept" in err and "project" in err
    assert store.load_config()["categories"] == ["concept"], "a conflict must not re-freeze"


def test_resolve_is_quiet_when_the_explicit_set_matches_the_frozen_one(tmp_path, capsys):
    store = KBStore(str(tmp_path))
    store.save_config({"categories": ["concept", "guide"]})

    resolve_categories(store, ["concept", "guide"])

    assert capsys.readouterr().err == ""


def test_resolve_treats_category_order_as_significant(tmp_path, capsys):
    """Order reaches the prompt, so a reordered list is a different prompt and
    must not be treated as the same set."""
    store = KBStore(str(tmp_path))
    store.save_config({"categories": ["concept", "guide"]})

    resolve_categories(store, ["guide", "concept"])

    assert "[config]" in capsys.readouterr().err


def test_resolve_does_not_fail_on_a_read_only_store(tmp_path, capsys):
    """The MCP server opens the KB read-only; resolving must not try to freeze."""
    store = KBStore(str(tmp_path), read_only=True)

    assert resolve_categories(store, None) == DEFAULT_CATEGORIES
    assert store.load_config() == {}


def test_resolve_does_not_conjure_a_kb_directory_that_does_not_exist(tmp_path):
    """A mistyped --kb path must not be left looking like a real KB. Compare
    commit 5d580b4, which made distill fail on a path that does not exist."""
    store = KBStore(str(tmp_path / "typo"))

    assert resolve_categories(store, None) == DEFAULT_CATEGORIES
    assert not store.base_dir.exists()
