"""Integration test for the full pipeline (classify -> dedup -> write).

Mocks the OpenAI client (completion_json) to return canned classification and
merge/create responses, then verifies the pipeline executes end-to-end without
error and emits the expected events.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import kb_ai.core.classify as classify_mod
import kb_ai.core.merge as merge_mod
from kb_ai.commands.pipeline import run_server_pipeline_with_input
from kb_ai.storage.store import KBStore


# ── Fixtures ──────────────────────────────────────────────────────────


def _make_kb(tmp_path: Path) -> str:
    """Create a minimal KB directory with an index and one existing article."""
    store = KBStore(str(tmp_path))
    store.index_dir.mkdir(parents=True, exist_ok=True)
    (store.index_dir / "master-index.md").write_text(
        "# Index\n- [Existing](wiki/concept/existing.md) — an existing article\n"
    )
    store.write_article(
        "wiki/concept/existing.md",
        "---\ntitle: Existing\ntype: concept\n---\n## Overview\n\nExisting content.\n",
    )
    return str(tmp_path)


def _mock_completion_json(**kwargs) -> dict:
    """Return a canned classification response that creates a new article."""
    return {
        "merge_into": [],
        "create_new": [
            {
                "path": "wiki/concept/test-topic.md",
                "type": "concept",
                "title": "Test Topic",
                "reason": "New concept identified",
            }
        ],
    }


def _mock_completion(**kwargs) -> str:
    """Return canned article content for create_new_article / merge_into_article."""
    return (
        '---\ntitle: "Test Topic"\ntype: concept\ntags: [testing]\n'
        "sources:\n  - test-source\ncreated: 2026-07-16\nupdated: 2026-07-16\n---\n"
        "## Overview\n\nThis is a test article about test topic.\n"
    )


@pytest.fixture
def kb_dir(tmp_path: Path) -> str:
    return _make_kb(tmp_path)


@pytest.fixture(autouse=True)
def _mock_llm(monkeypatch):
    """Mock LLM calls for all tests in this module."""
    monkeypatch.setattr(classify_mod, "completion_json", _mock_completion_json)
    monkeypatch.setattr(merge_mod, "completion", _mock_completion)


# ── Tests ─────────────────────────────────────────────────────────────


def test_pipeline_end_to_end_creates_article(kb_dir):
    """Full pipeline with mocked LLM creates an article and emits events."""
    input_data = {
        "kb_dir": kb_dir,
        "model": "claude-sonnet-4-6",
        "classify_model": "claude-sonnet-4-6",
        "categories": ["concept", "project", "decision", "person"],
        "workers": 2,
        "items": [
            {
                "content_hash": "abc123",
                "source_ref": "raw/test-source.md",
                "extraction": {
                    "summary": "A discussion about test topics and patterns",
                    "concepts": [{"title": "Test Topic", "description": "A concept for testing"}],
                    "entities": [],
                    "decisions": [],
                    "action_items": [],
                    "claims": [],
                    "topics": ["testing", "patterns"],
                    "connections": [],
                },
            }
        ],
        "topic_index_min_articles": 3,
        "people": [],
    }

    events: list[dict] = []
    results = run_server_pipeline_with_input(input_data, emit=events.append)

    # Pipeline should complete and return results
    assert isinstance(results, list)
    assert len(results) >= 1

    # The created article should exist on disk
    store = KBStore(kb_dir)
    article_path = "wiki/concept/test-topic.md"
    assert (store.base_dir / article_path).exists()

    # Result should indicate success
    ok_results = [r for r in results if r.get("status") == "ok"]
    assert len(ok_results) >= 1

    # At least one result should show created articles
    created_results = [r for r in results if r.get("created")]
    assert len(created_results) >= 1
    assert article_path in created_results[0]["created"]

    # Events should have been emitted (phase events + per-item result)
    assert len(events) >= 1
    event_types = [e.get("type") for e in events]
    assert "phase" in event_types


def test_pipeline_empty_items_returns_empty(kb_dir):
    """Pipeline with empty items list returns empty results."""
    input_data = {
        "kb_dir": kb_dir,
        "model": "claude-sonnet-4-6",
        "items": [],
        "topic_index_min_articles": 3,
        "people": [],
    }

    results = run_server_pipeline_with_input(input_data)
    assert results == []


def test_pipeline_emits_classify_phase_event(kb_dir):
    """Pipeline emits a classify phase event with duration and cost info."""
    input_data = {
        "kb_dir": kb_dir,
        "model": "claude-sonnet-4-6",
        "items": [
            {
                "content_hash": "def456",
                "source_ref": "raw/src2.md",
                "extraction": {
                    "summary": "Another test",
                    "concepts": [],
                    "entities": [],
                    "decisions": [],
                    "action_items": [],
                    "claims": [],
                    "topics": ["misc"],
                    "connections": [],
                },
            }
        ],
        "topic_index_min_articles": 3,
        "people": [],
    }

    events: list[dict] = []
    run_server_pipeline_with_input(input_data, emit=events.append)

    phase_events = [e for e in events if e.get("type") == "phase"]
    assert len(phase_events) >= 1

    classify_phase = next((e for e in phase_events if e.get("phase") == "classify"), None)
    assert classify_phase is not None
    assert "duration_s" in classify_phase
    assert "items" in classify_phase
    assert "cost" in classify_phase


def test_pipeline_multiple_items_all_processed(kb_dir):
    """Pipeline processes multiple items and returns results for each."""
    input_data = {
        "kb_dir": kb_dir,
        "model": "claude-sonnet-4-6",
        "items": [
            {
                "content_hash": f"hash_{i}",
                "source_ref": f"raw/src{i}.md",
                "extraction": {
                    "summary": f"Test item {i}",
                    "concepts": [],
                    "entities": [],
                    "decisions": [],
                    "action_items": [],
                    "claims": [],
                    "topics": [f"topic{i}"],
                    "connections": [],
                },
            }
            for i in range(3)
        ],
        "topic_index_min_articles": 3,
        "people": [],
    }

    events: list[dict] = []
    results = run_server_pipeline_with_input(input_data, emit=events.append)

    # All items should have results
    assert len(results) >= 3

    # Write phase should report articles written
    write_phases = [e for e in events if e.get("type") == "phase" and e.get("phase") == "write"]
    assert len(write_phases) == 1
    assert write_phases[0]["articles"] >= 1
