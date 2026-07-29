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
