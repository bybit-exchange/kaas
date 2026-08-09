"""Tests for the kb-ai check CLI: the operator entry point to F3 and F5.

The two checks were reachable only from tests and from a python -c, which is how
a check rots. This command is the surface that makes them runnable; it spends
nothing and rewrites nothing, so it is safe to point at someone else's KB.
"""
from __future__ import annotations

import json
from pathlib import Path

from kb_ai.commands import check as check_cmd
from kb_ai.core import merge as mg
from kb_ai.core.extract import ExtractionResult
from kb_ai.prompts import NoActivePromptError
from kb_ai.storage import extraction as exl
from kb_ai.storage.store import KBStore, _compute_checksum


def _kb(base: Path, docs: dict[str, str]) -> KBStore:
    store = KBStore(str(base))
    for rel, content in docs.items():
        store.write_raw(rel, content)
    return store


def _extract(store: KBStore, rel: str, *, checksum: str | None = None) -> None:
    exl.persist(store, rel, ExtractionResult(summary=f"summary of {rel}"),
                source_checksum=checksum or _compute_checksum(store.read_raw(rel)),
                extract_model="m")


def _derived(base: Path, parent: KBStore, docs: list[str]) -> Path:
    base.mkdir(parents=True)
    (base / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "source_kb": str(parent.base_dir),
        "slug": "topic",
        "documents": [{"rel_path": rel,
                       "checksum": _compute_checksum(parent.read_raw(rel)),
                       "size_bytes": 1} for rel in docs],
    }))
    return base


def _run(monkeypatch, argv) -> dict:
    out: list[str] = []
    monkeypatch.setattr("builtins.print",
                        lambda *a, **kw: out.append(str(a[0])) if a else None)
    check_cmd.run_check(argv)
    return json.loads(out[-1])


def test_defaults_kb_to_dot_kaas():
    assert check_cmd.build_parser().parse_args([]).kb == "./.kaas"


def test_a_kb_whose_extractions_all_match(monkeypatch, tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body", "raw/nested/b.md": "b body"})
    _extract(store, "raw/a.md")
    _extract(store, "raw/nested/b.md")

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    assert resp["ok"] is True
    ext = resp["data"]["extractions"]
    assert ext["matches"] == ["raw/a.md", "raw/nested/b.md"]
    assert ext["missing"] == [] and ext["mismatched"] == []
    assert "2 match" in ext["summary"]


def test_a_mismatched_extraction_carries_the_document_and_the_reason(monkeypatch,
                                                                    tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md", checksum="0" * 16)

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    mismatched = resp["data"]["extractions"]["mismatched"]
    assert len(mismatched) == 1
    assert mismatched[0]["document"] == "raw/a.md"
    assert "document hashes to" in mismatched[0]["reason"]


def test_a_missing_extraction_is_reported_without_being_called_a_fault(monkeypatch,
                                                                     tmp_path):
    """F3: the next compile pays for a missing extraction once. Not an error."""
    _kb(tmp_path, {"raw/a.md": "a body"})

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    assert resp["ok"] is True
    assert resp["data"]["extractions"]["missing"] == [
        {"document": "raw/a.md", "reason": "missing"}]


def test_a_kb_that_was_never_derived_reports_the_parent_check_as_unknown(monkeypatch,
                                                                        tmp_path):
    """F5 degrades rather than failing, so one command covers both kinds of KB."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    parent = resp["data"]["parent"]
    assert parent["verdict"] == "unknown"
    assert "manifest.json" in parent["reason"]


def test_a_derived_kb_reports_both_checks(monkeypatch, tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body", "raw/b.md": "b body"})
    derived_dir = _derived(tmp_path / "derived", parent, ["raw/a.md", "raw/b.md"])
    derived = KBStore(str(derived_dir))
    derived.write_raw("raw/a.md", "a body")
    derived.write_raw("raw/b.md", "b body")
    _extract(derived, "raw/a.md")
    _extract(derived, "raw/b.md")

    resp = _run(monkeypatch, ["--kb", str(derived_dir)])

    assert resp["data"]["extractions"]["matches"] == ["raw/a.md", "raw/b.md"]
    assert resp["data"]["parent"]["verdict"] == "in_sync"
    assert resp["data"]["parent"]["in_sync"] == ["raw/a.md", "raw/b.md"]
    assert resp["data"]["parent"]["source_kb"] == str(parent.base_dir)


def test_a_document_changed_in_the_parent_is_named(monkeypatch, tmp_path):
    parent = _kb(tmp_path / "parent", {"raw/a.md": "a body"})
    derived_dir = _derived(tmp_path / "derived", parent, ["raw/a.md"])
    parent.write_raw("raw/a.md", "a body, revised")

    resp = _run(monkeypatch, ["--kb", str(derived_dir)])

    assert resp["data"]["parent"]["verdict"] == "changed_in_parent"
    assert resp["data"]["parent"]["changed_in_parent"] == ["raw/a.md"]


def test_both_summaries_are_printed_for_an_operator_to_read(tmp_path, capsys):
    """Not via _run: that one replaces print(), which is where these lines go."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")

    check_cmd.run_check(["--kb", str(tmp_path)])

    captured = capsys.readouterr()
    assert "1 match" in captured.err
    assert "unknown" in captured.err
    assert json.loads(captured.out)["ok"] is True


def _composed(store: KBStore, rel: str, *, extract: str, write: str) -> None:
    state = store.load_compile_state()
    state[rel] = {"checksum": _compute_checksum(store.read_raw(rel)),
                  "compiled_at": "2026-08-08T10:00:00",
                  "prompt_version": extract, "write_prompt_version": write}
    store.save_compile_state(state)


def test_check_names_the_documents_behind_the_write_prompt(monkeypatch, tmp_path):
    """The whole point of the write-phase version: editing merge-rewrite.md
    invalidates nothing, so the next compile is a no-op and reports nothing. This
    is where an operator finds out, for free, at any time."""
    store = _kb(tmp_path, {"raw/a.md": "a body", "raw/b.md": "b body"})
    _extract(store, "raw/a.md")
    _extract(store, "raw/b.md")
    _composed(store, "raw/a.md", extract=exl.current_prompt_version(),
              write="an-older-write-prompt")
    _composed(store, "raw/b.md", extract=exl.current_prompt_version(),
              write=mg.write_prompt_version())

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    wiki = resp["data"]["wiki"]
    assert wiki["behind_write_prompt"] == ["raw/a.md"]
    assert wiki["behind_extract_prompt"] == []
    assert "1 behind the write prompt" in wiki["summary"]


def test_check_reports_an_empty_lag_for_a_kb_that_was_never_compiled(monkeypatch,
                                                                    tmp_path):
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")

    resp = _run(monkeypatch, ["--kb", str(tmp_path)])

    assert resp["data"]["wiki"] == {
        "behind_extract_prompt": [], "behind_write_prompt": [],
        "extract_first_run": False, "write_first_run": False,
        "summary": resp["data"]["wiki"]["summary"]}


def test_an_unreadable_prompt_set_still_reports_the_checks_that_do_not_need_it(
        monkeypatch, tmp_path, capsys):
    """F3 and F5 depend on no prompt. Refusing to run them because a prompt
    directory is broken would withhold answers that are still available."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    _composed(store, "raw/a.md", extract="e0", write="w0")

    def boom():
        raise NoActivePromptError("prompt file not found: merge-diff")

    monkeypatch.setattr(check_cmd, "write_prompt_version", boom)

    check_cmd.run_check(["--kb", str(tmp_path)])

    captured = capsys.readouterr()
    resp = json.loads(captured.out)
    assert resp["ok"] is True
    assert resp["data"]["extractions"]["matches"] == ["raw/a.md"]
    assert resp["data"]["wiki"]["behind_write_prompt"] == []
    assert "write prompt version unavailable" in resp["data"]["wiki"]["summary"]
    assert "merge-diff" in captured.err


def test_the_command_neither_spends_nor_rewrites(monkeypatch, tmp_path):
    """F3 and F5 are read-only by design; the entry point must not change that."""
    store = _kb(tmp_path, {"raw/a.md": "a body"})
    _extract(store, "raw/a.md")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    _run(monkeypatch, ["--kb", str(tmp_path)])

    after = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before


def test_a_path_that_is_not_a_knowledge_base_is_an_error_not_a_clean_bill(
        monkeypatch, tmp_path):
    """In the one command built for diagnosis, a typo'd --kb was indistinguishable
    from a healthy empty KB: 0 match / 0 missing / 0 mismatched and ok: true."""
    resp = _run(monkeypatch, ["--kb", str(tmp_path / "nope")])

    assert resp["ok"] is False
    assert resp["error"]["code"] == "NOT_A_KB"
