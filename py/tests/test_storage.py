"""Tests for the kb_ai.storage package — verifies new import paths work."""
from __future__ import annotations

from pathlib import Path

import pytest

from kb_ai.storage.store import KBStore, ArticleMeta, RawFile, RawFileMeta


def test_kbstore_importable_from_storage():
    """KBStore is importable from kb_ai.storage.store."""
    assert KBStore is not None


def test_article_meta_importable_from_storage():
    """ArticleMeta is importable from kb_ai.storage.store."""
    meta = ArticleMeta(title="Test", path="wiki/test.md")
    assert meta.title == "Test"
    assert meta.path == "wiki/test.md"


def test_storage_index_importable():
    """update_markdown_index importable from kb_ai.storage.index."""
    from kb_ai.storage.index import update_markdown_index, update_timeline
    assert callable(update_markdown_index)
    assert callable(update_timeline)


def test_store_roundtrip_via_new_path(tmp_path: Path):
    """KBStore from storage package works for read/write."""
    store = KBStore(str(tmp_path))
    store.write_article("wiki/concept/test.md", "# Test\nbody")
    assert store.read_article("wiki/concept/test.md") == "# Test\nbody"


def test_render_catalog_line_without_keys():
    from kb_ai.storage.store import ArticleMeta, render_catalog_line

    a = ArticleMeta(title="Pricing Model", path="wiki/pricing.md",
                    summary="How fees are computed.")
    assert render_catalog_line(a) == "- wiki/pricing.md — Pricing Model: How fees are computed."


def test_render_catalog_line_appends_keys_column():
    from kb_ai.storage.store import KEYS_MARKER, ArticleMeta, render_catalog_line

    a = ArticleMeta(title="Limits", path="wiki/limits.md",
                    summary="Configured ceilings.", keys="max_zip_entries, max_body")
    line = render_catalog_line(a)
    assert line.endswith(f"{KEYS_MARKER}max_zip_entries, max_body")
    assert line.startswith("- wiki/limits.md — Limits: Configured ceilings.")
