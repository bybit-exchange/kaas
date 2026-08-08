"""Tests for the remaining error/edge branches scattered across small modules.

Each section targets branches the per-module suites leave untouched: defensive
guards, truncation paths, and the "the other side of stdout died" fallbacks.
Everything stays offline — the LLM boundary and the transport are monkeypatched.
"""
from __future__ import annotations

import json
import threading
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import kb_ai.core.extract as ex
import kb_ai.prompts as prompts_mod
from kb_ai import _protocol
from kb_ai import distill as distill_mod
from kb_ai import server_daemon as sd
from kb_ai._protocol import RequestResponseCommand, StreamingCommand
from kb_ai._types import ClassificationResult, CreateTarget, MergeTarget
from kb_ai.core import classify as cl
from kb_ai.core import people
from kb_ai.llm._infra import count_prompt_chars, emit_alert
from kb_ai.prompts.registry import (
    NoActivePromptError,
    PromptError,
    PromptInstance,
    PromptRegistry,
)
from kb_ai.storage.store import KBStore


# ── extract: load_prompt ────────────────────────────────────────────

@pytest.fixture
def packaged_prompts(monkeypatch):
    """Force the registry back to the packaged defaults directory."""
    monkeypatch.delenv("KAAS_PROMPTS_DIR", raising=False)
    monkeypatch.setattr(prompts_mod, "_registry", None)
    return Path(prompts_mod.__file__).parent / "defaults"


def test_load_prompt_returns_the_packaged_prompt_text(packaged_prompts):
    assert ex.load_prompt("summarize") == (packaged_prompts / "summarize.md").read_text(
        encoding="utf-8"
    )


def test_load_prompt_raises_when_a_listed_prompt_has_no_file(packaged_prompts, tmp_path,
                                                             monkeypatch):
    monkeypatch.setenv("KAAS_PROMPTS_DIR", str(tmp_path))
    monkeypatch.setattr(prompts_mod, "_registry", None)
    with pytest.raises(NoActivePromptError, match="prompt file not found"):
        ex.load_prompt("summarize")


# ── extract: _merge_one_group ───────────────────────────────────────

def test_merge_one_group_sends_joined_summaries_to_the_merge_prompt(monkeypatch):
    captured: dict = {}

    monkeypatch.setattr(ex, "load_prompt", lambda name: f"[{name}] instructions")

    def fake_completion(*, model, messages, max_tokens):
        captured.update(model=model, messages=messages, max_tokens=max_tokens)
        return "super summary"

    monkeypatch.setattr(ex, "completion", fake_completion)

    out = ex._merge_one_group(["first", "second", "third"], model="claude-haiku-4-5")

    assert out == "super summary"
    assert captured["model"] == "claude-haiku-4-5"
    assert captured["max_tokens"] == 2048
    assert captured["messages"][0] == {
        "role": "system",
        "content": "[merge-summaries] instructions",
    }
    # Summaries are joined with an explicit separator so the model can tell them apart.
    assert captured["messages"][1] == {
        "role": "user",
        "content": "first\n---\nsecond\n---\nthird",
    }


# ── extract: chunk_transcript buffer flushing ───────────────────────

def _turn(index: int, payload: str) -> str:
    return f"**@alice** 00:00:{index:02d} {payload}"


def test_chunk_transcript_flushes_the_buffer_before_an_oversized_turn():
    """A turn larger than the budget must not be glued onto the pending buffer:
    the buffer is emitted first, then the huge turn is hard-split."""
    short = _turn(1, "hello there")
    huge = _turn(2, "x" * 400)
    body = "# M\n> Title: Sync\n\n" + short + "\n" + huge

    chunks = ex.chunk_transcript(body, {}, max_tokens=25)  # max_chars = 100

    assert len(chunks) > 2
    # First chunk carries only the buffered short turn.
    assert "hello there" in chunks[0]
    assert "x" not in chunks[0].split("---\n", 1)[1]
    # The oversized turn survives in full across the remaining chunks.
    rest = "".join(c.split("---\n", 1)[1] for c in chunks[1:])
    assert rest.count("x") == 400


def test_chunk_transcript_flushes_the_buffer_when_the_next_turn_would_overflow():
    """Turns that individually fit are packed until they would exceed the budget."""
    turns = [_turn(i, f"t{i}-" + "x" * 15) for i in range(1, 5)]  # 38 chars each
    body = "# M\n> Title: Sync\n\n" + "\n".join(turns)

    chunks = ex.chunk_transcript(body, {}, max_tokens=25)  # max_chars = 100

    assert len(chunks) == 2
    assert "t1-" in chunks[0] and "t2-" in chunks[0]
    assert "t3-" not in chunks[0] and "t4-" not in chunks[0]
    assert "t3-" in chunks[1] and "t4-" in chunks[1]


# ── llm/_infra ──────────────────────────────────────────────────────

def test_emit_alert_includes_content_hash_and_caller(capsys):
    emit_alert("timed out", "claude-haiku-4-5", 2, "TIMEOUT",
               content_hash="ab12cd", caller="kb_ai/llm.py:_completion_inner")

    err = capsys.readouterr().err
    assert "[LLM-WARN] TIMEOUT: timed out" in err
    assert "model=claude-haiku-4-5 attempt=2" in err
    assert "content_hash=ab12cd" in err
    assert "caller=kb_ai/llm.py:_completion_inner" in err


def test_emit_alert_omits_optional_fields_when_empty(capsys):
    emit_alert("boom", "m", 1, "ERROR")

    err = capsys.readouterr().err
    assert "content_hash" not in err
    assert "caller" not in err


def test_emit_alert_also_reaches_a_context_sink(capsys, fresh_context):
    """A stalled call has to be findable in the log of the KB being compiled.

    stderr alone loses it: over the HTTP API the backend's stderr is a separate
    stream from the compile log anyone debugging a slow run reads first.
    """
    lines = []
    fresh_context.alert_sink = lines.append

    emit_alert("timed out", "m", 1, "api_timeout_error")

    assert len(lines) == 1
    assert "[LLM-WARN] api_timeout_error: timed out" in lines[0]
    # Still on stderr -- the sink is an addition, not a redirect.
    assert "[LLM-WARN] api_timeout_error: timed out" in capsys.readouterr().err


def test_emit_alert_survives_a_failing_sink(capsys, fresh_context):
    """A closed log file must not turn a retryable timeout into a crash."""
    def boom(_msg):
        raise ValueError("log file is closed")

    fresh_context.alert_sink = boom

    emit_alert("timed out", "m", 1, "api_timeout_error")

    assert "[LLM-WARN] api_timeout_error: timed out" in capsys.readouterr().err


def test_count_prompt_chars_counts_text_parts_of_structured_content():
    messages = [
        {"role": "system", "content": "abcde"},                      # 5
        {"role": "user", "content": [
            {"type": "text", "text": "1234"},                        # 4
            {"type": "text", "text": "678"},                         # 3
            {"type": "image_url", "image_url": {"url": "ignored"}},   # no "text"
            {"type": "text", "text": 12345},                         # non-str, ignored
            "a bare string part",                                    # non-dict, ignored
        ]},
        {"role": "assistant"},                                       # no content
    ]

    assert count_prompt_chars(messages) == 12


# ── prompts/registry ────────────────────────────────────────────────

def test_prompt_render_names_the_missing_variable():
    inst = PromptInstance(id=0, name="classify", version=3, content="{alpha} and {beta}")

    with pytest.raises(KeyError, match="prompt classify#3 missing variable: beta"):
        inst.render(alpha="A")


def test_prompt_render_tolerates_extra_variables():
    inst = PromptInstance(id=0, name="p", version=1, content="{alpha}")
    assert inst.render(alpha="A", unused="B") == "A"


def test_registry_loads_a_yaml_prompt_with_metadata(tmp_path):
    (tmp_path / "classify.yaml").write_text(
        "content: 'classify {x}'\nversion: 7\ndescription: sorts things\nvariables: [x]\n",
        encoding="utf-8",
    )

    inst = PromptRegistry(str(tmp_path)).get("classify")

    assert inst.name == "classify"
    assert inst.version == 7
    assert inst.content == "classify {x}"
    assert inst.meta == {"description": "sorts things", "variables": ["x"]}


def test_registry_yaml_defaults_version_and_metadata(tmp_path):
    (tmp_path / "p.yaml").write_text("content: bare\n", encoding="utf-8")

    inst = PromptRegistry(str(tmp_path)).get("p")

    assert inst.version == 1
    assert inst.meta == {"description": "", "variables": []}


def test_registry_prefers_yaml_over_markdown(tmp_path):
    (tmp_path / "p.yaml").write_text("content: from-yaml\n", encoding="utf-8")
    (tmp_path / "p.md").write_text("from-md", encoding="utf-8")

    assert PromptRegistry(str(tmp_path)).get("p").content == "from-yaml"


def test_registry_rejects_a_yaml_prompt_without_content(tmp_path):
    (tmp_path / "p.yaml").write_text("description: no content here\n", encoding="utf-8")

    with pytest.raises(PromptError, match="missing 'content'"):
        PromptRegistry(str(tmp_path)).get("p")


def test_registry_rejects_a_yaml_prompt_that_is_not_a_mapping(tmp_path):
    (tmp_path / "p.yaml").write_text("- one\n- two\n", encoding="utf-8")

    with pytest.raises(PromptError, match="invalid prompt file"):
        PromptRegistry(str(tmp_path)).get("p")


def test_registry_caches_a_loaded_prompt(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("content: first\n", encoding="utf-8")
    registry = PromptRegistry(str(tmp_path))

    first = registry.get("p")
    path.write_text("content: second\n", encoding="utf-8")

    assert registry.get("p") is first


# ── distill ─────────────────────────────────────────────────────────

def test_raw_rel_falls_back_to_the_bare_filename_outside_the_root():
    rel = distill_mod._raw_rel(Path("/kb/project"), Path("/elsewhere/deep/note.md"))
    # The unrelated directories are dropped — only the bare filename survives.
    assert rel == "raw/project__note.md"


def test_raw_rel_flattens_nested_paths_under_the_root():
    rel = distill_mod._raw_rel(Path("/kb/project"), Path("/kb/project/docs/note.md"))
    assert rel == "raw/project__docs__note.md"


def test_raw_rel_appends_md_to_a_non_markdown_source():
    # KBStore only scans raw/*.md, so a source that is not already markdown has
    # to gain the suffix — which is why the suffix cannot simply be stripped.
    rel = distill_mod._raw_rel(Path("/kb/project"), Path("/kb/project/main.go"))
    assert rel == "raw/project__main.go.md"


def test_raw_rel_still_appends_md_to_an_uppercase_md_source():
    # ingest_paths() lowercases the suffix before deciding to ingest, so an
    # uppercase .MD reaches this function — and must still gain ".md", because
    # KBStore's raw scan globs "*.md" case-sensitively on POSIX. Skipping the
    # append here would ingest a file that never compiles.
    rel = distill_mod._raw_rel(Path("/kb/project"), Path("/kb/project/NOTE.MD"))
    assert rel == "raw/project__NOTE.MD.md"


def test_ingest_paths_skips_a_text_file_with_undecodable_bytes(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.md").write_text("# fine")
    (src / "broken.md").write_bytes(b"\xff\xfe\x00bad utf8")
    kb = tmp_path / "kb"

    report = distill_mod.ingest_paths([str(src)], str(kb))

    assert len(report.ingested) == 1
    assert report.ingested[0].endswith("ok.md")
    assert any(s.endswith("broken.md") for s in report.skipped)
    assert not (kb / "raw" / "src__broken.md").exists()


# ── _types: dict-compatible access ──────────────────────────────────

def _classification() -> ClassificationResult:
    return ClassificationResult(
        merge_into=[MergeTarget(path="wiki/a.md", reason="r")],
        create_new=[CreateTarget(path="wiki/b.md", type="concept", title="B", reason="new")],
    )


def test_classification_result_get_returns_the_dict_view():
    result = _classification()

    assert result.get("merge_into") == [{"path": "wiki/a.md", "reason": "r"}]
    assert result.get("create_new")[0]["title"] == "B"


def test_classification_result_get_returns_the_default_for_unknown_keys():
    assert _classification().get("nope") is None
    assert _classification().get("nope", "fallback") == "fallback"


def test_classification_result_supports_item_access():
    result = _classification()

    assert result["create_new"] == [
        {"path": "wiki/b.md", "type": "concept", "title": "B", "reason": "new"}
    ]
    with pytest.raises(KeyError):
        result["nope"]


def test_classification_result_contains_only_the_two_pipeline_keys():
    result = _classification()

    assert "merge_into" in result
    assert "create_new" in result
    assert "nope" not in result


# ── _protocol: abstract hooks and a dead stdout ─────────────────────

def test_request_response_command_execute_is_abstract():
    with pytest.raises(NotImplementedError):
        RequestResponseCommand().execute({})


def test_request_response_command_without_execute_reports_internal_error(capsys):
    with patch("sys.stdin", StringIO("{}")):
        RequestResponseCommand().run()

    output = json.loads(capsys.readouterr().out.strip())
    assert output["ok"] is False
    assert output["error"]["code"] == "INTERNAL_ERROR"


def test_streaming_command_execute_is_abstract():
    with pytest.raises(NotImplementedError):
        StreamingCommand().execute({}, lambda event: None)


def test_streaming_command_without_execute_emits_internal_error(capsys):
    with patch("sys.stdin", StringIO("{}")):
        StreamingCommand().run()

    output = json.loads(capsys.readouterr().out.strip())
    assert output["type"] == "error"
    assert output["code"] == "INTERNAL_ERROR"


def test_streaming_command_survives_a_dead_stdout_during_error_reporting(monkeypatch, capsys):
    """If the reader is gone, emitting the error event fails too — run() must
    still return instead of taking the process down with it."""
    def dead_stdout(event: dict) -> None:
        raise BrokenPipeError("stdout closed")

    monkeypatch.setattr(_protocol, "stream_emit", dead_stdout)

    class FailingStream(StreamingCommand):
        def execute(self, input_data: dict, emit) -> None:
            raise ValueError("boom")

    with patch("sys.stdin", StringIO("{}")):
        FailingStream().run()  # must not raise

    assert capsys.readouterr().out == ""


# ── server_daemon ───────────────────────────────────────────────────

def _request(cmd: str, request_id: str = "1", **payload) -> dict:
    return {"id": request_id, "cmd": cmd, "payload": payload}


def _events(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def test_dispatch_streaming_routes_pipeline_stream(capsys, monkeypatch):
    import kb_ai.commands.pipeline as pipeline

    def fake(inner, emit=None, cancel_event=None):
        emit({"type": "article", "path": inner["kb_dir"]})
        return [{"path": "a.md"}]

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input", fake)
    registry = {"7": threading.Event()}

    sd._dispatch_streaming(_request("pipeline-stream", "7", kb_dir="/kb"), "pipeline-stream",
                           "7", registry["7"], registry, threading.Lock())

    events = _events(capsys)
    assert [e["event"]["type"] for e in events] == ["article", "done"]
    assert events[0]["event"]["path"] == "/kb"
    assert events[-1]["final"] is True
    assert registry == {}


def test_pipeline_stream_emit_raises_once_cancelled(capsys, monkeypatch):
    """The cancel event must stop the pipeline stream at the next emit."""
    import kb_ai.commands.pipeline as pipeline

    progress = []

    def fake(inner, emit=None, cancel_event=None):
        emit({"type": "article", "path": "a.md"})
        progress.append("first")
        cancel_event.set()
        with pytest.raises(sd.CancelledError):
            emit({"type": "article", "path": "b.md"})
        progress.append("second-blocked")
        return []

    monkeypatch.setattr(pipeline, "run_server_pipeline_with_input", fake)

    sd._handle_pipeline_stream(_request("pipeline-stream"), "1", threading.Event())

    assert progress == ["first", "second-blocked"]
    events = _events(capsys)
    # The cancelled emit produced no event at all.
    assert [e["event"]["type"] for e in events] == ["article", "done"]
    assert events[0]["event"]["path"] == "a.md"


def test_main_keeps_serving_when_the_shutdown_handler_fails(capsys, monkeypatch):
    """A failed shutdown must not silently kill the loop: the error is reported
    and the daemon keeps reading commands."""
    def boom(request_id, executor):
        raise RuntimeError("executor stuck")

    monkeypatch.setattr(sd, "_handle_shutdown", boom)

    lines = [
        json.dumps({"id": "1", "cmd": "shutdown"}),
        json.dumps({"id": "2", "cmd": "ping"}),
    ]
    with patch("sys.stdin", StringIO("".join(line + "\n" for line in lines))):
        sd.main()

    got = _events(capsys)
    assert got[0]["error"]["code"] == "INTERNAL_ERROR"
    assert "executor stuck" in got[0]["error"]["message"]
    assert got[1]["id"] == "2"
    assert got[1]["ok"] is True


# ── core/people ─────────────────────────────────────────────────────

class _StrayRglobDir(Path):
    """wiki_dir whose rglob also reports a file living outside the directory."""

    def __init__(self, *args, stray: Path | None = None):
        super().__init__(*args)
        self._stray = stray

    def rglob(self, pattern, **kwargs):
        return [*super().rglob(pattern, **kwargs), self._stray]


def test_update_people_stubs_skips_files_outside_the_wiki_dir(tmp_path):
    store = KBStore(str(tmp_path))
    store.write_article("wiki/a.md", "[[Grace Hopper]] spoke")
    outside = tmp_path / "outside.md"
    outside.write_text("[[Grace Hopper]] also mentioned here")

    fake_store = SimpleNamespace(
        wiki_dir=_StrayRglobDir(str(store.wiki_dir), stray=outside),
        base_dir=store.base_dir,
    )

    people.update_people_stubs(fake_store, [{"canonical": "Grace Hopper", "aliases": ["Grace Hopper"]}])

    stub = (store.wiki_dir / "people" / "grace-hopper.md").read_text()
    # Only the in-wiki article counts; the stray file is skipped, not crashed on.
    assert "mentions: 1" in stub
    assert "outside.md" not in stub


# ── core/classify ───────────────────────────────────────────────────

def test_classify_article_truncates_oversized_decisions_json(monkeypatch):
    captured: dict = {}

    def fake_completion_json(*, model, messages, max_tokens, cache=None):
        captured["user"] = messages[1]["content"]
        return {"merge_into": [], "create_new": []}

    monkeypatch.setattr(cl, "completion_json", fake_completion_json)
    monkeypatch.setattr(cl, "MAX_PROMPT_CHARS", 4000)

    extraction = ex.ExtractionResult(
        summary="s",
        decisions=[{"title": f"decision {i}", "what": "w" * 200} for i in range(20)],
    )

    cl.classify_article(extraction, [])

    user = captured["user"]
    # The decisions blob is cut so the whole user message lands on the budget.
    assert len(user) == 4000 // 2
    assert "decision 0" in user
    assert not user.rstrip().endswith("]")  # truncated mid-JSON, not a full array
