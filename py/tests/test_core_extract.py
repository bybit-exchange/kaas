"""Offline tests for knowledge extraction (kb_ai.core.extract).

The LLM seams (completion / completion_json) are monkeypatched throughout. The
focus is the logic the ADRs pin down: chunking, transcript handling, the
K-adaptive Phase 2 dispatch thresholds, the L2 merge fanout, and the failure
containment around both.
"""
from __future__ import annotations

import pytest

from kb_ai._errors import ExtractionFailedError
from kb_ai.core import extract as ex
from kb_ai.core.extract import ExtractionResult


# ── parse / serialise ───────────────────────────────────────────────

def test_parse_extraction_result_full():
    raw = {
        "summary": "s",
        "concepts": [{"title": "c"}],
        "entities": [{"name": "e"}],
        "decisions": [{"title": "d"}],
        "action_items": [{"task": "a"}],
        "claims": [{"claim": "cl"}],
        "topics": ["t"],
        "connections": ["conn"],
    }
    out = ex.parse_extraction_result(raw)

    assert out.summary == "s"
    assert out.topics == ["t"]
    assert out.connections == ["conn"]


def test_parse_extraction_result_defaults_missing_fields():
    out = ex.parse_extraction_result({})

    assert out.summary == ""
    for fname in ("concepts", "entities", "decisions", "action_items",
                  "claims", "topics", "connections"):
        assert getattr(out, fname) == []


def test_parse_extraction_result_coerces_none_to_empty():
    """A model returning explicit nulls must not produce None fields, or every
    downstream .extend() would crash."""
    raw = {f: None for f in ("summary", "concepts", "entities", "decisions",
                             "action_items", "claims", "topics", "connections")}
    out = ex.parse_extraction_result(raw)

    assert out.summary == ""
    assert out.concepts == []
    assert out.topics == []


def test_extraction_to_dict_round_trips():
    original = ExtractionResult(summary="s", topics=["t"], concepts=[{"title": "c"}])

    round_tripped = ex.parse_extraction_result(ex.extraction_to_dict(original))

    assert round_tripped.summary == "s"
    assert round_tripped.topics == ["t"]
    assert round_tripped.concepts == [{"title": "c"}]


def test_extraction_to_dict_omits_source_path():
    """source_path is internal bookkeeping and must not reach the wire."""
    d = ex.extraction_to_dict(ExtractionResult(source_path="/kb/raw/a.md"))
    assert "source_path" not in d


def test_extraction_results_do_not_share_mutable_defaults():
    a, b = ExtractionResult(), ExtractionResult()
    a.topics.append("x")
    assert b.topics == []


# ── _bounded_join ───────────────────────────────────────────────────

def test_bounded_join_under_limit_is_a_plain_join():
    assert ex._bounded_join(["a", "b"], "\n", 100) == "a\nb"


def test_bounded_join_truncates_over_limit():
    out = ex._bounded_join(["a" * 50, "b" * 50], "\n", 20)
    assert len(out) == 20
    assert out == "a" * 20


def test_bounded_join_clamps_negative_limit():
    assert ex._bounded_join(["a" * 50], "\n", -10) == ""


def test_bounded_join_exactly_at_limit_is_untouched():
    assert ex._bounded_join(["abc", "de"], "\n", 6) == "abc\nde"


def test_bounded_join_empty_parts():
    assert ex._bounded_join([], "\n", 10) == ""


# ── type-split prompt rendering ─────────────────────────────────────

@pytest.fixture
def stub_prompts(monkeypatch):
    """Replace the prompt registry with a template exposing both placeholders."""
    monkeypatch.setattr(ex, "load_prompt",
                        lambda name: f"[{name}] fields={{FIELDS_LIST}} schema={{TYPES_JSON_SCHEMA}}")


def test_render_type_split_prompt_k2_groups(stub_prompts):
    a = ex._render_type_split_prompt("A", 2)
    b = ex._render_type_split_prompt("B", 2)

    assert "concepts, entities, topics, summary" in a
    assert "claims, decisions, action_items, connections" in b
    # Each group's schema must contain only its own fields.
    assert '"concepts"' in a and '"claims"' not in a
    assert '"claims"' in b and '"concepts"' not in b


def test_render_type_split_prompt_k3_covers_every_field(stub_prompts):
    rendered = [ex._render_type_split_prompt(g, 3) for g in ("A", "B", "C")]

    all_fields = set()
    for group in ex.TYPE_SPLIT_GROUPS_K3.values():
        all_fields.update(group)
    assert all_fields == set(ex._FIELD_JSON_SCHEMAS)

    for fname in all_fields:
        assert any(f'"{fname}"' in r for r in rendered), f"{fname} missing from K=3 prompts"


def test_type_split_groups_partition_fields_without_overlap():
    """Field ownership must be exclusive, or one group's answer would silently
    overwrite another's."""
    for groups in (ex.TYPE_SPLIT_GROUPS_K2, ex.TYPE_SPLIT_GROUPS_K3):
        seen: set[str] = set()
        for fields in groups.values():
            assert not (seen & set(fields)), f"overlapping fields: {seen & set(fields)}"
            seen.update(fields)
        assert seen == set(ex._FIELD_JSON_SCHEMAS)


@pytest.mark.parametrize("k", [0, 1, 4, 5, -1])
def test_render_type_split_prompt_rejects_unsupported_k(stub_prompts, k):
    with pytest.raises(ValueError, match="unsupported K"):
        ex._render_type_split_prompt("A", k)


def test_render_type_split_prompt_rejects_unknown_group(stub_prompts):
    with pytest.raises(ValueError, match="unknown group"):
        ex._render_type_split_prompt("C", 2)   # C only exists for K=3


# ── chunk_content ───────────────────────────────────────────────────

def test_chunk_content_short_input_is_one_chunk():
    assert ex.chunk_content("short text") == ["short text"]


def test_chunk_content_splits_on_line_boundaries():
    # max_tokens=1 -> 4 chars per chunk.
    chunks = ex.chunk_content("aa\nbb\ncc", max_tokens=1)

    assert len(chunks) > 1
    assert "".join(c.replace("\n", "") for c in chunks) == "aabbcc"


def test_chunk_content_splits_an_oversized_single_line():
    """A single line longer than the cap must be hard-split rather than emitted
    whole, which would blow the prompt budget."""
    chunks = ex.chunk_content("x" * 30, max_tokens=1)   # cap 4 chars

    assert all(len(c) <= 4 for c in chunks)
    assert "".join(chunks) == "x" * 30


def test_chunk_content_preserves_all_content():
    content = "\n".join(f"line {i}" for i in range(200))
    chunks = ex.chunk_content(content, max_tokens=10)

    assert "\n".join(chunks) == content


def test_chunk_content_exact_boundary_is_one_chunk():
    assert ex.chunk_content("a" * 4000, max_tokens=1000) == ["a" * 4000]


# ── frontmatter ─────────────────────────────────────────────────────

def test_parse_frontmatter_absent():
    meta, body = ex._parse_frontmatter("no frontmatter\nhere")
    assert meta == {}
    assert body == "no frontmatter\nhere"


def test_parse_frontmatter_present():
    meta, body = ex._parse_frontmatter("---\ntitle: T\nsource: meetings\n---\nbody text")

    assert meta == {"title": "T", "source": "meetings"}
    assert body == "body text"


def test_parse_frontmatter_invalid_yaml_warns_and_degrades(capsys):
    meta, body = ex._parse_frontmatter('---\ntitle: "bad \\ escape\n---\nbody')

    assert meta == {}
    assert "invalid YAML" in capsys.readouterr().err


def test_parse_frontmatter_empty_block():
    meta, body = ex._parse_frontmatter("---\n\n---\nbody")
    assert meta == {}
    assert body == "body"


# ── transcript detection and chunking ───────────────────────────────

def test_is_transcript_requires_both_markers():
    assert ex._is_transcript({"source": "meetings", "artifact_kind": "vc_note_transcript"})
    assert not ex._is_transcript({"source": "meetings"})
    assert not ex._is_transcript({"artifact_kind": "vc_note_transcript"})
    assert not ex._is_transcript({})
    assert not ex._is_transcript({"source": "slack", "artifact_kind": "vc_note_transcript"})


def test_parse_transcript_header_extracts_title_and_time():
    body = (
        "# Meeting\n"
        "> Title: Weekly Sync\n"
        "> Time: 2026-07-31 10:00\n"
        "\n"
        "**@alice** 00:00:01 hello\n"
    )
    info, remaining = ex._parse_transcript_header(body)

    assert info == {"title": "Weekly Sync", "time": "2026-07-31 10:00"}
    assert remaining.startswith("**@alice**")


def test_parse_transcript_header_without_header():
    info, remaining = ex._parse_transcript_header("**@alice** 00:00:01 hi")
    assert info == {}
    assert remaining == "**@alice** 00:00:01 hi"


def test_build_transcript_context_includes_all_known_fields():
    ctx = ex._build_transcript_context(
        meta={"title": "Meta Title", "date": "2026-07-31"},
        header={"title": "Header Title", "time": "10:00-11:00"},
        speakers=["alice", "bob"],
        time_start="00:00:01",
        time_end="00:10:00",
    )

    assert "[会议逐字稿]" in ctx
    assert "主题: Header Title" in ctx
    assert "会议: Meta Title" in ctx
    assert "日期: 2026-07-31" in ctx
    assert "会议时间: 10:00-11:00" in ctx
    assert "当前片段: 00:00:01 - 00:10:00" in ctx
    assert "参会者: alice, bob" in ctx


def test_build_transcript_context_dedupes_identical_titles():
    ctx = ex._build_transcript_context(
        meta={"title": "Same"}, header={"title": "Same"},
        speakers=[], time_start="", time_end="",
    )
    assert "主题: Same" in ctx
    assert "会议: Same" not in ctx


def test_build_transcript_context_minimal():
    ctx = ex._build_transcript_context({}, {}, [], "", "")
    assert ctx.startswith("[会议逐字稿]")


def _transcript_body(turns: int, words_per_turn: int = 1) -> str:
    lines = ["# Meeting", "> Title: Sync", ""]
    for i in range(turns):
        speaker = "alice" if i % 2 == 0 else "bob"
        lines.append(f"**@{speaker}** 00:{i // 60:02d}:{i % 60:02d} " + ("word " * words_per_turn))
    return "\n".join(lines)


def test_chunk_transcript_single_chunk_returns_body_unchanged():
    body = _transcript_body(3)
    assert ex.chunk_transcript(body, {}) == [body]


def test_chunk_transcript_splits_and_injects_context():
    body = _transcript_body(40, words_per_turn=40)
    chunks = ex.chunk_transcript(body, {"title": "Meta", "date": "2026-07-31"}, max_tokens=1)

    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.startswith("[会议逐字稿]")
        assert "主题: Sync" in chunk


def test_chunk_transcript_records_all_speakers_in_context():
    chunks = ex.chunk_transcript(_transcript_body(20, words_per_turn=40), {}, max_tokens=1)

    assert len(chunks) > 1
    assert "参会者: alice, bob" in chunks[0]


def test_chunk_transcript_no_turns_returns_body():
    body = "just prose with no speaker markers"
    assert ex.chunk_transcript(body, {}) == [body]


def test_chunk_transcript_hard_splits_an_oversized_turn():
    body = "# M\n\n**@alice** 00:00:01 " + ("x" * 500)
    chunks = ex.chunk_transcript(body, {}, max_tokens=1)

    # The single huge turn must be broken up rather than returned intact.
    assert len(chunks) > 1


# ── summarize ───────────────────────────────────────────────────────

def test_build_summarize_context_all_fields():
    ctx = ex._build_summarize_context({"title": "T", "source": "slack", "date": "2026-07-31"})

    assert "Title: T" in ctx
    assert "Source: slack" in ctx
    assert "Date: 2026-07-31" in ctx
    assert ctx.endswith("---")


def test_build_summarize_context_empty_frontmatter():
    assert ex._build_summarize_context({}) == ""


def test_summarize_chunk_prefixes_context(monkeypatch, stub_prompts):
    captured = {}

    def fake_completion(*, model, messages, **kwargs):
        captured["user"] = messages[1]["content"]
        captured["model"] = model
        return "a summary"

    monkeypatch.setattr(ex, "completion", fake_completion)

    out = ex.summarize_chunk("chunk text", {"title": "T"}, "sum-model")

    assert out == "a summary"
    assert captured["user"].startswith("Title: T")
    assert "chunk text" in captured["user"]
    assert captured["model"] == "sum-model"


def test_summarize_chunk_without_frontmatter_sends_bare_text(monkeypatch, stub_prompts):
    captured = {}

    def fake_completion(*, model, messages, **kwargs):
        captured["user"] = messages[1]["content"]
        return "s"

    monkeypatch.setattr(ex, "completion", fake_completion)

    ex.summarize_chunk("chunk text", {}, "m")

    assert captured["user"] == "chunk text"


# ── merge_summaries_l2 ──────────────────────────────────────────────

def test_merge_summaries_l2_empty():
    assert ex.merge_summaries_l2([]) == []


def test_merge_summaries_l2_at_or_below_fanout_is_a_noop(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("must not call the LLM at or below fanout")

    monkeypatch.setattr(ex, "_merge_one_group", boom)

    summaries = ["a", "b", "c"]
    assert ex.merge_summaries_l2(summaries, fanout=5) == summaries
    assert ex.merge_summaries_l2(["a"] * 5, fanout=5) == ["a"] * 5


def test_merge_summaries_l2_partitions_by_fanout(monkeypatch):
    seen_groups = []

    def fake_merge(group, model):
        seen_groups.append(list(group))
        return "merged:" + ",".join(group)

    monkeypatch.setattr(ex, "_merge_one_group", fake_merge)

    out = ex.merge_summaries_l2([str(i) for i in range(12)], fanout=5)

    # 12 summaries at fanout 5 -> groups of 5, 5, 2.
    assert len(out) == 3
    assert sorted(len(g) for g in seen_groups) == [2, 5, 5]
    # Order must be preserved despite parallel execution.
    assert out[0] == "merged:0,1,2,3,4"
    assert out[2] == "merged:10,11"


def test_merge_summaries_l2_contains_per_group_failure(monkeypatch, capsys):
    def flaky(group, model):
        if "3" in group:
            raise RuntimeError("haiku down")
        return "merged"

    monkeypatch.setattr(ex, "_merge_one_group", flaky)

    out = ex.merge_summaries_l2([str(i) for i in range(12)], fanout=5)

    # The failing slot survives as a bounded join instead of vanishing.
    assert len(out) == 3
    assert "0\n1\n2\n3\n4" in out[0]
    assert "falling back to bounded join" in capsys.readouterr().err


def test_merge_summaries_l2_bounds_the_fallback_slot(monkeypatch):
    def always_fail(group, model):
        raise RuntimeError("down")

    monkeypatch.setattr(ex, "_merge_one_group", always_fail)

    huge = ["x" * 5000 for _ in range(6)]
    out = ex.merge_summaries_l2(huge, fanout=5)

    for slot in out:
        assert len(slot) <= ex._SUPER_SUMMARY_FALLBACK_LIMIT


# ── type-split extraction ───────────────────────────────────────────

def _group_response(fields: tuple[str, ...], marker: str) -> dict:
    """Build a raw response filling only the given fields."""
    out: dict = {}
    for f in fields:
        if f == "summary":
            out[f] = marker
        elif f in ("topics", "connections"):
            out[f] = [f"{marker}-{f}"]
        else:
            out[f] = [{"marker": marker, "field": f}]
    return out


@pytest.mark.parametrize("k,groups_attr", [
    (2, "TYPE_SPLIT_GROUPS_K2"),
    (3, "TYPE_SPLIT_GROUPS_K3"),
])
def test_extract_knowledge_type_split_merges_by_field_ownership(
    monkeypatch, stub_prompts, k, groups_attr
):
    groups = getattr(ex, groups_attr)

    def fake_completion_json(*, model, messages, **kwargs):
        # Identify the group from the rendered field list in the system prompt.
        system = messages[0]["content"]
        for name, fields in groups.items():
            if f"fields={', '.join(fields)}" in system:
                return _group_response(fields, name)
        raise AssertionError(f"unrecognised prompt: {system}")

    monkeypatch.setattr(ex, "completion_json", fake_completion_json)

    out = ex.extract_knowledge_type_split("content", k=k)

    # Each field must carry the marker of the group that owns it.
    for name, fields in groups.items():
        for fname in fields:
            value = getattr(out, fname)
            if fname == "summary":
                assert value == name
            elif fname in ("topics", "connections"):
                assert value == [f"{name}-{fname}"]
            else:
                assert value[0]["marker"] == name


@pytest.mark.parametrize("k", [0, 1, 4])
def test_extract_knowledge_type_split_rejects_unsupported_k(k):
    with pytest.raises(ValueError, match="unsupported K"):
        ex.extract_knowledge_type_split("content", k=k)


def test_extract_knowledge_type_split_propagates_failure(monkeypatch, stub_prompts):
    def boom(**kwargs):
        raise RuntimeError("sonnet down")

    monkeypatch.setattr(ex, "completion_json", boom)

    with pytest.raises(RuntimeError, match="sonnet down"):
        ex.extract_knowledge_type_split("content", k=2)


# ── _phase2_with_retry ──────────────────────────────────────────────

def test_phase2_retries_once_then_succeeds(monkeypatch, capsys):
    calls = {"n": 0}

    def flaky(content, k, model, max_tokens):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return ExtractionResult(summary="ok")

    monkeypatch.setattr(ex, "extract_knowledge_type_split", flaky)

    out = ex._phase2_with_retry("content", k=2, model="m", max_tokens=100)

    assert out.summary == "ok"
    assert calls["n"] == 2
    assert "retrying once" in capsys.readouterr().err


def test_phase2_propagates_second_failure(monkeypatch):
    calls = {"n": 0}

    def always_fail(content, k, model, max_tokens):
        calls["n"] += 1
        raise RuntimeError(f"attempt {calls['n']}")

    monkeypatch.setattr(ex, "extract_knowledge_type_split", always_fail)

    with pytest.raises(RuntimeError, match="attempt 2"):
        ex._phase2_with_retry("content", k=2, model="m", max_tokens=100)

    assert calls["n"] == 2


def test_phase2_no_retry_on_success(monkeypatch):
    calls = {"n": 0}

    def ok(content, k, model, max_tokens):
        calls["n"] += 1
        return ExtractionResult(summary="fine")

    monkeypatch.setattr(ex, "extract_knowledge_type_split", ok)

    ex._phase2_with_retry("content", k=2, model="m", max_tokens=100)

    assert calls["n"] == 1


# ── K-adaptive dispatch (extract_knowledge_summarized) ──────────────

@pytest.fixture
def spy_phase2(monkeypatch):
    """Record which Phase 2 route each dispatch takes."""
    route: dict = {}

    monkeypatch.setattr(ex, "summarize_chunk",
                        lambda chunk, fm, model: f"summary of {chunk}")

    def fake_extract_knowledge(content, model, prompt_name="extract", max_tokens=16384):
        route["k"] = 1
        route["content"] = content
        return ExtractionResult(summary="k1")

    def fake_phase2(content, k, model, max_tokens):
        route["k"] = k
        route["content"] = content
        return ExtractionResult(summary=f"k{k}")

    def fake_l2(summaries, fanout, model):
        route["l2"] = {"n": len(summaries), "fanout": fanout}
        return ["super"] * 3

    monkeypatch.setattr(ex, "extract_knowledge", fake_extract_knowledge)
    monkeypatch.setattr(ex, "_phase2_with_retry", fake_phase2)
    monkeypatch.setattr(ex, "merge_summaries_l2", fake_l2)
    return route


def test_summarized_empty_chunks_short_circuits():
    out = ex.extract_knowledge_summarized([], {}, "sum", "ext")
    assert out == ExtractionResult()


def test_summarized_all_summaries_failing_raises(monkeypatch, capsys):
    """An empty result here was indistinguishable from "nothing to say".

    Now that extractions are persisted with provenance, that ambiguity would
    become a file that looks fresh and empty forever, so the summarize path
    propagates like the chunked one does.
    """
    def boom(chunk, fm, model):
        raise RuntimeError("summarize down")

    monkeypatch.setattr(ex, "summarize_chunk", boom)

    with pytest.raises(ExtractionFailedError, match="every chunk summarization failed"):
        ex.extract_knowledge_summarized(["a", "b"], {}, "sum", "ext")

    assert "summarization failed" in capsys.readouterr().err


def test_summarized_no_chunks_still_returns_empty(spy_phase2):
    """An empty document honestly extracts to nothing."""
    assert ex.extract_knowledge_summarized([], {}, "sum", "ext") == ExtractionResult()


def test_summarized_skips_failed_chunks_but_keeps_the_rest(monkeypatch, spy_phase2):
    def flaky(chunk, fm, model):
        if chunk == "bad":
            raise RuntimeError("down")
        return f"summary of {chunk}"

    monkeypatch.setattr(ex, "summarize_chunk", flaky)

    ex.extract_knowledge_summarized(["good", "bad"], {}, "sum", "ext")

    assert spy_phase2["k"] == 1
    assert "summary of good" in spy_phase2["content"]
    assert "bad" not in spy_phase2["content"]


@pytest.mark.parametrize("n,expected_k", [
    (1, 1),
    (3, 1),    # boundary: <=3 stays single-shot
    (4, 2),    # boundary: 4 enters K=2
    (7, 2),    # boundary: 7 is the last K=2
    (8, 3),    # boundary: 8 enters K=3
    (19, 3),   # boundary: 19 is the last plain K=3
])
def test_summarized_k_dispatch_thresholds(spy_phase2, n, expected_k):
    ex.extract_knowledge_summarized([f"c{i}" for i in range(n)], {}, "sum", "ext")

    assert spy_phase2["k"] == expected_k
    assert "l2" not in spy_phase2


def test_summarized_uses_l2_merge_at_twenty_chunks(spy_phase2):
    ex.extract_knowledge_summarized([f"c{i}" for i in range(20)], {}, "sum", "ext")

    assert spy_phase2["l2"] == {"n": 20, "fanout": 5}
    assert spy_phase2["k"] == 3


def test_summarized_uses_l2_merge_for_oversized_join(monkeypatch, spy_phase2):
    """Even a small chunk count goes through L2 once the joined summaries would
    blow the Phase 2 budget."""
    monkeypatch.setattr(ex, "summarize_chunk", lambda chunk, fm, model: "x" * 31_000)

    ex.extract_knowledge_summarized(["a", "b", "c"], {}, "sum", "ext")

    assert spy_phase2["l2"]["n"] == 3
    assert spy_phase2["k"] == 3


def test_summarized_caps_phase2_input(monkeypatch, spy_phase2):
    """A join under the L2 trigger but over the prompt cap must be truncated.

    With the default MAX_PROMPT_CHARS (80K) this branch is unreachable — the
    60K L2 trigger always fires first — so shrink the cap to the value a
    KB_AI_MAX_PROMPT_CHARS override would produce.
    """
    monkeypatch.setattr(ex, "MAX_PROMPT_CHARS", 20_000)
    monkeypatch.setattr(ex, "summarize_chunk", lambda chunk, fm, model: "y" * 20_000)

    ex.extract_knowledge_summarized(["a", "b"], {}, "sum", "ext")

    limit = 20_000 - 8000
    assert len(spy_phase2["content"]) == limit


def test_summarized_passes_models_through(monkeypatch):
    seen = {}

    def fake_summarize(chunk, fm, model):
        seen["summarize_model"] = model
        return "s"

    def fake_extract(content, model, prompt_name="extract", max_tokens=16384):
        seen["extract_model"] = model
        return ExtractionResult()

    monkeypatch.setattr(ex, "summarize_chunk", fake_summarize)
    monkeypatch.setattr(ex, "extract_knowledge", fake_extract)

    ex.extract_knowledge_summarized(["a"], {}, "sum-model", "ext-model")

    assert seen == {"summarize_model": "sum-model", "extract_model": "ext-model"}


# ── extract_knowledge_chunked ───────────────────────────────────────

def test_chunked_single_chunk_uses_single_shot(monkeypatch):
    seen = {}

    def fake_extract(content, model, prompt_name="extract", max_tokens=16384):
        seen["content"] = content
        return ExtractionResult(summary="one")

    monkeypatch.setattr(ex, "extract_knowledge", fake_extract)

    out = ex.extract_knowledge_chunked("short content")

    assert out.summary == "one"
    assert seen["content"] == "short content"


def test_chunked_merges_multiple_chunks(monkeypatch):
    def fake_extract(content, model, prompt_name="extract", max_tokens=16384):
        tag = content.strip()[:4]
        return ExtractionResult(
            summary=f"sum-{tag}",
            concepts=[{"c": tag}],
            topics=["shared", f"t-{tag}"],
            connections=["shared-conn"],
        )

    monkeypatch.setattr(ex, "extract_knowledge", fake_extract)
    monkeypatch.setattr(ex, "chunk_content", lambda content: ["aaaa", "bbbb"])

    out = ex.extract_knowledge_chunked("long content")

    assert "sum-aaaa" in out.summary and "sum-bbbb" in out.summary
    assert len(out.concepts) == 2
    # Topics and connections are de-duplicated across chunks.
    assert sorted(out.topics) == ["shared", "t-aaaa", "t-bbbb"]
    assert out.connections == ["shared-conn"]


def test_chunked_routes_transcripts_through_the_turn_chunker(monkeypatch):
    used = {}

    monkeypatch.setattr(ex, "extract_knowledge",
                        lambda content, model, prompt_name="extract", max_tokens=16384:
                        ExtractionResult(summary="s"))

    def fake_chunk_transcript(body, meta):
        used["transcript"] = True
        return ["turn chunk"]

    def fake_chunk_content(content):
        pytest.fail("a transcript must not use the content chunker")

    monkeypatch.setattr(ex, "chunk_transcript", fake_chunk_transcript)
    monkeypatch.setattr(ex, "chunk_content", fake_chunk_content)

    content = "---\nsource: meetings\nartifact_kind: vc_note_transcript\n---\n**@a** 00:00:01 hi"
    ex.extract_knowledge_chunked(content)

    assert used["transcript"] is True


def test_chunked_propagates_worker_failure(monkeypatch):
    """Unlike the summarize path, a failed chunk here is not skipped — the
    caller must see the error rather than a silently partial extraction."""
    def boom(content, model, prompt_name="extract", max_tokens=16384):
        raise RuntimeError("sonnet down")

    monkeypatch.setattr(ex, "extract_knowledge", boom)
    monkeypatch.setattr(ex, "chunk_content", lambda content: ["a", "b"])

    with pytest.raises(RuntimeError, match="sonnet down"):
        ex.extract_knowledge_chunked("content")


# ── extract_knowledge ───────────────────────────────────────────────

def test_extract_knowledge_wraps_content_in_document_tags(monkeypatch, stub_prompts):
    captured = {}

    def fake_completion_json(*, model, messages, max_tokens):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        captured["max_tokens"] = max_tokens
        return {"summary": "s"}

    monkeypatch.setattr(ex, "completion_json", fake_completion_json)

    out = ex.extract_knowledge("my content", model="m", max_tokens=999)

    assert out.summary == "s"
    assert captured["user"] == "<document>\nmy content\n</document>"
    assert captured["max_tokens"] == 999
    assert captured["system"].startswith("[extract]")


def test_extract_knowledge_honours_prompt_name(monkeypatch, stub_prompts):
    captured = {}

    def fake_completion_json(*, model, messages, max_tokens):
        captured["system"] = messages[0]["content"]
        return {}

    monkeypatch.setattr(ex, "completion_json", fake_completion_json)

    ex.extract_knowledge("c", prompt_name="extract-types")

    assert "[extract-types]" in captured["system"]


# ── timeout decorator ───────────────────────────────────────────────

def test_with_extract_timeout_sets_and_restores(monkeypatch):
    from kb_ai.llm import get_call_timeout, set_call_timeout

    observed = {}

    @ex._with_extract_timeout
    def probe():
        observed["inside"] = get_call_timeout()

    set_call_timeout(42.0)
    try:
        probe()
        assert observed["inside"] == ex._EXTRACT_CALL_TIMEOUT_S
        # Restoring to the previous value (not None) keeps nesting safe.
        assert get_call_timeout() == 42.0
    finally:
        set_call_timeout(None)


def test_with_extract_timeout_restores_on_exception():
    from kb_ai.llm import get_call_timeout, set_call_timeout

    @ex._with_extract_timeout
    def boom():
        raise RuntimeError("x")

    set_call_timeout(7.0)
    try:
        with pytest.raises(RuntimeError):
            boom()
        assert get_call_timeout() == 7.0
    finally:
        set_call_timeout(None)


def test_with_extract_timeout_preserves_metadata():
    @ex._with_extract_timeout
    def documented():
        """A docstring."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "A docstring."


# ── one strategy router for both ingestion routes ───────────────────
#
# The CLI used to hardcode "chunked" in its freshness gate while the daemon
# recorded whichever strategy it actually routed to. A deployment configured for
# summarize therefore had every UI-ingested document re-extracted once by the next
# CLI compile and silently downgraded to chunked -- the two routes disagreeing
# about the KB's own configuration. One router, one answer.

def test_chunked_is_the_resolved_strategy_when_chunked_is_asked_for():
    plan = ex.plan_extraction("body", ex.STRATEGY_CHUNKED)
    assert plan.strategy == ex.STRATEGY_CHUNKED


def test_summarize_resolves_without_consulting_the_content():
    """A requested summarize is honoured whatever the document looks like, so the
    gate can compare against it without reading a single document."""
    plan = ex.plan_extraction("tiny", ex.STRATEGY_SUMMARIZE)
    assert plan.strategy == ex.STRATEGY_SUMMARIZE


def test_auto_resolves_to_chunked_for_a_document_that_does_not_split():
    plan = ex.plan_extraction("short body", ex.STRATEGY_AUTO)
    assert plan.strategy == ex.STRATEGY_CHUNKED


def test_auto_resolves_to_summarize_once_the_document_splits_enough():
    """Three chunks is the threshold the daemon has always used."""
    plan = ex.plan_extraction("x\n" * 40_000, ex.STRATEGY_AUTO)
    assert len(plan.chunks) >= 3
    assert plan.strategy == ex.STRATEGY_SUMMARIZE


def test_a_resolved_plan_never_says_auto():
    """persist records the strategy that ran: recording "auto" would make the
    field useless, since the router decides on chunk count."""
    for content in ("short", "x\n" * 40_000):
        assert ex.plan_extraction(content, ex.STRATEGY_AUTO).strategy in (
            ex.STRATEGY_CHUNKED, ex.STRATEGY_SUMMARIZE)


def test_an_unknown_strategy_is_refused_rather_than_treated_as_chunked():
    """Silently falling back is what made this class of bug invisible: a typo in
    the configuration would extract every document under the wrong strategy."""
    with pytest.raises(ValueError, match="unknown extract strategy"):
        ex.plan_extraction("body", "Chunked")


def test_a_transcript_is_chunked_by_speaker_turns_under_auto():
    """chunk_transcript, not chunk_content -- the daemon's routing did this and a
    second implementation would have had to remember to."""
    header = "---\nsource: meetings\nartifact_kind: vc_note_transcript\n---\n"
    body = "**@a.b** 00:00:01\nhello\n" * 500
    plan = ex.plan_extraction(header + body, ex.STRATEGY_AUTO)

    assert ex._is_transcript(plan.meta)
    assert plan.chunks == tuple(ex.chunk_transcript(body, plan.meta))
    assert plan.chunks != tuple(ex.chunk_content(header + body))


def test_running_a_chunked_plan_extracts_from_the_document_itself(monkeypatch):
    seen = {}

    def fake_chunked(content, model="m"):
        seen["content"] = content
        seen["model"] = model
        return ExtractionResult(summary="s")

    monkeypatch.setattr(ex, "extract_knowledge_chunked", fake_chunked)
    plan = ex.plan_extraction("the body", ex.STRATEGY_CHUNKED)

    result = ex.run_planned_extraction(plan, "the body", extract_model="m1")

    assert result.summary == "s"
    assert seen == {"content": "the body", "model": "m1"}


def test_running_a_summarize_plan_goes_through_the_two_phase_path(monkeypatch):
    seen = {}

    def fake_summarized(chunks, meta, summarize_model, extract_model):
        seen.update(chunks=list(chunks), summarize_model=summarize_model,
                    extract_model=extract_model)
        return ExtractionResult(summary="s")

    monkeypatch.setattr(ex, "extract_knowledge_summarized", fake_summarized)
    plan = ex.plan_extraction("body", ex.STRATEGY_SUMMARIZE)

    ex.run_planned_extraction(plan, "body", extract_model="m1",
                              summarize_model="m2")

    assert seen["summarize_model"] == "m2"
    assert seen["extract_model"] == "m1"
    assert seen["chunks"] == list(plan.chunks)
