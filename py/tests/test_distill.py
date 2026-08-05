from __future__ import annotations

import json
from pathlib import Path

import pytest

from kb_ai.commands.compile import compile_kb
from kb_ai.storage.store import KBStore
from kb_ai.distill import ingest_paths, IngestReport, run_distill


def _run_distill(monkeypatch, argv):
    out: list[str] = []
    monkeypatch.setattr("builtins.print", lambda *a, **kw: out.append(str(a[0])) if a else None)
    run_distill(argv)
    return json.loads(out[-1])


def test_distill_reports_a_path_that_does_not_exist(monkeypatch, tmp_path):
    """A mistyped or wrongly-relative path must fail loudly, not be dropped.

    ingest_paths() walks each path and yields nothing for one that is absent, so
    a run naming ten paths of which nine are absent used to report ok=true for
    the one that resolved -- and silently distilled the wrong corpus.
    """
    real = tmp_path / "kept.md"
    real.write_text("real content")

    payload = _run_distill(monkeypatch, [
        str(real), str(tmp_path / "gone.md"), str(tmp_path / "also-gone"),
        "--kb", str(tmp_path / "kb"),
    ])

    assert payload["ok"] is False
    assert payload["error"]["code"] == "PATH_NOT_FOUND"
    assert "gone.md" in str(payload["error"]["paths"])
    assert "also-gone" in str(payload["error"]["paths"])
    # Nothing was ingested: the run stopped before touching the KB.
    assert not (tmp_path / "kb" / "raw").exists()


def test_compile_kb_empty_kb_returns_nothing_to_compile(tmp_path: Path):
    (tmp_path / "raw").mkdir()
    result = compile_kb(str(tmp_path))
    assert result == {"compiled": 0, "message": "nothing to compile"}


def test_write_raw_creates_file_under_base(tmp_path):
    store = KBStore(str(tmp_path))
    store.write_raw("raw/sub/note.md", "hello")
    assert (tmp_path / "raw" / "sub" / "note.md").read_text() == "hello"


def test_write_raw_blocked_when_read_only(tmp_path):
    store = KBStore(str(tmp_path), read_only=True)
    with pytest.raises(PermissionError):
        store.write_raw("raw/x.md", "no")


def test_ingest_paths_wraps_text_skips_binary(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("# Alpha")
    (src / "b.py").write_text("print('x')")
    (src / "c.pdf").write_bytes(b"%PDF-1.4 binary")
    kb = tmp_path / "kb"

    report = ingest_paths([str(src)], str(kb))

    assert isinstance(report, IngestReport)
    raw_files = sorted(p.name for p in (kb / "raw").rglob("*.md"))
    assert len(raw_files) == 2  # a.md and b.py -> two raw .md files
    assert len(report.ingested) == 2
    assert any(s.endswith("c.pdf") for s in report.skipped)
    # source marker preserved
    assert any("<!-- source:" in p.read_text() for p in (kb / "raw").rglob("*.md"))


def test_ingest_paths_single_file(tmp_path):
    f = tmp_path / "solo.txt"
    f.write_text("solo content")
    kb = tmp_path / "kb"
    report = ingest_paths([str(f)], str(kb))
    assert len(report.ingested) == 1
    assert report.skipped == []


import kb_ai.distill as distill_mod


def test_run_distill_ingests_and_compiles(tmp_path, monkeypatch, capsys):
    src = tmp_path / "docs"
    src.mkdir()
    (src / "note.md").write_text("# Note\nbody")
    kb = tmp_path / "kb"

    calls = {}

    def fake_compile_kb(data_dir, **kwargs):
        calls["data_dir"] = data_dir
        return {"compiled": 1, "errors": []}

    monkeypatch.setattr(distill_mod, "compile_kb", fake_compile_kb)

    distill_mod.run_distill([str(src), "--kb", str(kb)])

    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert calls["data_dir"] == str(kb)
    assert (kb / "raw").exists()


def test_run_distill_errors_when_no_readable_files(tmp_path, monkeypatch, capsys):
    src = tmp_path / "bin"
    src.mkdir()
    (src / "x.pdf").write_bytes(b"%PDF")
    kb = tmp_path / "kb"
    monkeypatch.setattr(distill_mod, "compile_kb", lambda *a, **k: {"compiled": 0})

    distill_mod.run_distill([str(src), "--kb", str(kb)])

    out = capsys.readouterr().out
    assert '"ok": false' in out


def test_run_distill_passes_llm_model_env(tmp_path, monkeypatch, capsys):
    src = tmp_path / "docs"; src.mkdir()
    (src / "n.md").write_text("# N\nbody")
    kb = tmp_path / "kb"
    captured = {}
    def fake_compile_kb(data_dir, **kwargs):
        captured.update(kwargs); return {"compiled": 1}
    monkeypatch.setattr(distill_mod, "compile_kb", fake_compile_kb)
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")
    distill_mod.run_distill([str(src), "--kb", str(kb)])
    assert captured["extract_model"] == "gpt-4o-mini"
    assert captured["compile_model"] == "gpt-4o-mini"
    assert captured["write_model"] == "gpt-4o-mini"


def test_run_distill_defaults_model_when_env_absent(tmp_path, monkeypatch):
    src = tmp_path / "docs"; src.mkdir()
    (src / "n.md").write_text("# N\nbody")
    kb = tmp_path / "kb"
    captured = {}
    monkeypatch.setattr(distill_mod, "compile_kb", lambda data_dir, **kw: captured.update(kw) or {"compiled": 1})
    monkeypatch.delenv("LLM_MODEL", raising=False)
    distill_mod.run_distill([str(src), "--kb", str(kb)])
    assert captured["extract_model"] == "gpt-4o-mini"


def test_ingest_paths_prunes_ignored_dirs(tmp_path):
    from kb_ai.distill import ingest_paths
    src = tmp_path / "proj"; src.mkdir()
    (src / "keep.md").write_text("# keep")
    (src / ".git").mkdir(); (src / ".git" / "config").write_text("[core]")
    (src / "node_modules").mkdir(); (src / "node_modules" / "dep.js").write_text("x")
    (src / ".venv").mkdir(); (src / ".venv" / "lib.py").write_text("y")
    kb = tmp_path / "kb"
    report = ingest_paths([str(src)], str(kb))
    assert len(report.ingested) == 1
    # ignored dirs are pruned entirely — not ingested and not in skipped
    joined = " ".join(report.ingested + report.skipped)
    assert ".git" not in joined and "node_modules" not in joined and ".venv" not in joined


@pytest.mark.slow
def test_distill_end_to_end_produces_article(tmp_path):
    """Real LLM compile. Requires LLM_API_KEY in env; skips otherwise."""
    import os
    if not (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")):
        pytest.skip("no LLM credentials in env")

    src = tmp_path / "docs"
    src.mkdir()
    (src / "topic.md").write_text(
        "# Project Zephyr\n\nZephyr is a caching layer. "
        "Decision: use LRU eviction. Owner: Dana."
    )
    kb = tmp_path / "kb"

    distill_mod.run_distill([str(src), "--kb", str(kb)])

    wiki_files = list((kb / "wiki").rglob("*.md"))
    assert wiki_files, "expected at least one compiled wiki article"


# ── --categories ────────────────────────────────────────────────────

def _capture_compile(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        distill_mod, "compile_kb",
        lambda data_dir, **kw: captured.update(kw) or {"compiled": 1},
    )
    return captured


def test_run_distill_passes_no_categories_by_default(tmp_path, monkeypatch):
    """Omitting the flag must mean "whatever the KB already froze", not the
    defaults -- otherwise distill would override every custom KB's taxonomy."""
    src = tmp_path / "docs"; src.mkdir()
    (src / "n.md").write_text("# N\nbody")
    captured = _capture_compile(monkeypatch)

    distill_mod.run_distill([str(src), "--kb", str(tmp_path / "kb")])

    assert captured["categories"] is None


def test_run_distill_forwards_a_category_list(tmp_path, monkeypatch):
    src = tmp_path / "docs"; src.mkdir()
    (src / "n.md").write_text("# N\nbody")
    captured = _capture_compile(monkeypatch)

    distill_mod.run_distill([
        str(src), "--kb", str(tmp_path / "kb"), "--categories", "concept,guide,reference",
    ])

    assert captured["categories"] == ["concept", "guide", "reference"]


def test_run_distill_tolerates_spaces_and_trailing_commas(tmp_path, monkeypatch):
    src = tmp_path / "docs"; src.mkdir()
    (src / "n.md").write_text("# N\nbody")
    captured = _capture_compile(monkeypatch)

    distill_mod.run_distill([
        str(src), "--kb", str(tmp_path / "kb"), "--categories", " concept , guide ,",
    ])

    assert captured["categories"] == ["concept", "guide"]


def test_run_distill_rejects_an_empty_category_list(tmp_path, monkeypatch, capsys):
    """`--categories ,,` must not silently fall back to the defaults: the caller
    clearly meant to set something."""
    src = tmp_path / "docs"; src.mkdir()
    (src / "n.md").write_text("# N\nbody")
    _capture_compile(monkeypatch)

    distill_mod.run_distill([str(src), "--kb", str(tmp_path / "kb"), "--categories", " , "])

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "EMPTY_CATEGORIES"
