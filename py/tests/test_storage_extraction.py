"""The extraction layer's file format, provenance and staleness comparison.

Covers spec A1-A6, B1-B17, C1-C2 and H2, H4, H5 of
docs/features/extraction-layer/spec.md. No test here calls an LLM.

The round-trip tests are load-bearing rather than defensive: the body is parsed
back into the objects the write phase composes articles from, so a serializer /
parser asymmetry would show up as an article missing content, with no error.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kb_ai._errors import ExtractionFileError
from kb_ai.core import extract as ex
from kb_ai.core.extract import ExtractionResult
from kb_ai.storage import extraction as exl
from kb_ai.storage.store import KBStore


@pytest.fixture(autouse=True)
def clear_prompt_version_cache():
    """extract_prompt_version() is memoized per process (B12), not per test."""
    ex.extract_prompt_version.cache_clear()
    yield
    ex.extract_prompt_version.cache_clear()


@pytest.fixture
def store(tmp_path) -> KBStore:
    return KBStore(str(tmp_path))


def _full(**overrides) -> ExtractionResult:
    """An extraction with every field populated, CJK throughout."""
    base = dict(
        summary="季度评审的结论：定价改为按席位计费。",
        concepts=[{"title": "按席位计费", "summary": "每个活跃席位每月收费一次。"}],
        entities=[{"name": "Rockman", "type": "person", "context": "提出该方案"}],
        decisions=[{"title": "改为席位制", "what": "2026 Q4 起生效",
                    "why": "用量计费难以预测", "who": ["Ben", "Rockman"]}],
        action_items=[{"task": "更新价格页", "owner": "lucas"}],
        claims=[{"claim": "现有客户中 80% 更偏好席位制", "source": "问卷",
                 "surprising": False}],
        enumerations=[{"name": "席位定价档位", "kind": "option-list",
                       "ordered": True, "items": ["入门", "标准", "企业"]}],
        topics=["pricing", "billing"],
        source_path="raw/notes.md",
    )
    base.update(overrides)
    return ExtractionResult(**base)


def _provenance(**overrides) -> exl.Provenance:
    base = dict(
        source="raw/notes.md",
        source_checksum="0123456789abcdef",
        extract_model="claude-sonnet-4-6",
        extract_strategy=exl.STRATEGY_CHUNKED,
        prompt_version="a1b2c3d4e5f6",
        extracted_at="2026-08-07T11:22:33+00:00",
    )
    base.update(overrides)
    return exl.Provenance(**base)


def _round_trip(result: ExtractionResult, provenance=None) -> ExtractionResult:
    text = exl.serialize(provenance or _provenance(), result)
    return exl.parse(text).extraction


def _assert_round_trips(result: ExtractionResult) -> None:
    """Field-for-field equality, with topics sorted per B17."""
    parsed = _round_trip(result)
    assert parsed.summary == result.summary
    for name in exl.BODY_FIELDS:
        assert getattr(parsed, name) == getattr(result, name), name
    assert parsed.topics == sorted(result.topics, key=str)
    assert parsed.source_path == "raw/notes.md"


# ── A: layout and naming ────────────────────────────────────────────

@pytest.mark.parametrize("raw_rel, expected", [
    ("raw/a.md", "extraction/a.md"),
    ("raw/window-2026-06__docs__day-1.md", "extraction/window-2026-06__docs__day-1.md"),
    ("raw/nested/deeper/note.md", "extraction/nested/deeper/note.md"),
    ("raw/NOTE.MD.md", "extraction/NOTE.MD.md"),
    ("raw/a.b.c.md", "extraction/a.b.c.md"),
])
def test_extraction_rel_path_mirrors_the_relative_path(store, raw_rel, expected):
    assert store.extraction_rel_path(raw_rel) == expected


@pytest.mark.parametrize("bad", [
    "wiki/a.md", "a.md", "", "raw", "/raw/a.md", "raw/../wiki/a.md",
])
def test_extraction_rel_path_rejects_anything_not_under_raw(store, bad):
    with pytest.raises(ValueError):
        store.extraction_rel_path(bad)


def test_extraction_path_resolves_inside_the_kb(store):
    assert store.extraction_path("raw/x.md") == store.base_dir / "extraction" / "x.md"


def test_persist_writes_exactly_one_file_and_overwrites_in_place(store):
    path, existed = exl.persist(store, "raw/a.md", _full(),
                                source_checksum="0" * 16, extract_model="m")
    assert existed is False
    assert [p.name for p in store.extraction_dir.iterdir()] == ["a.md"]

    _path2, existed2 = exl.persist(store, "raw/a.md", _full(summary="second"),
                                   source_checksum="0" * 16, extract_model="m")
    assert existed2 is True
    assert [p.name for p in store.extraction_dir.iterdir()] == ["a.md"]
    assert "second" in path.read_text()


def test_persist_leaves_no_temp_file_behind(store):
    exl.persist(store, "raw/nested/a.md", _full(),
                source_checksum="0" * 16, extract_model="m")
    assert list(store.extraction_dir.rglob("*.tmp")) == []
    assert (store.extraction_dir / "nested" / "a.md").exists()


def test_persist_refuses_a_read_only_store(tmp_path):
    ro = KBStore(str(tmp_path), read_only=True)
    with pytest.raises(PermissionError):
        exl.persist(ro, "raw/a.md", _full(), source_checksum="0" * 16,
                    extract_model="m")


# ── B: file contents and provenance ─────────────────────────────────

def test_file_shape_is_frontmatter_plus_five_pinned_sections(store):
    text = exl.serialize(_provenance(), _full())
    assert text.startswith("---\n")

    headings = [ln for ln in text.splitlines() if ln.startswith("## ")]
    assert headings == ["## Concepts", "## Entities", "## Decisions",
                        "## Action Items", "## Claims", "## Enumerations"]

    header = yaml.safe_load(text.split("---\n")[1])
    # The exact key set, not just the keys this test names: without it a payload
    # field can appear or vanish from the frontmatter and every assertion below
    # still passes. summarize_model is the one conditional key (B15).
    assert set(header) == {
        "source", "source_checksum", "extract_model", "extract_strategy",
        "prompt_version", "extracted_at", "schema_version",
        "summary", "topics", "counts",
    }
    assert header["source"] == "raw/notes.md"
    assert header["source_checksum"] == "0123456789abcdef"
    assert header["extract_model"] == "claude-sonnet-4-6"
    assert header["extract_strategy"] == "chunked"
    assert header["prompt_version"] == "a1b2c3d4e5f6"
    assert header["extracted_at"] == "2026-08-07T11:22:33+00:00"
    assert header["schema_version"] == exl.SCHEMA_VERSION
    # B7: everything selection needs is in the frontmatter.
    assert header["summary"].startswith("季度评审")
    assert header["topics"] == ["billing", "pricing"]
    assert header["counts"] == {"concepts": 1, "entities": 1, "decisions": 1,
                                "action_items": 1, "claims": 1,
                                "enumerations": 1}
    # summarize_model is absent on the chunked path (B15).
    assert "summarize_model" not in header


def test_cjk_is_not_escaped(store):
    assert "按席位计费" in exl.serialize(_provenance(), _full())


def test_body_items_are_labelled_values_not_styling():
    text = exl.serialize(_provenance(), _full())
    assert "- claim: 现有客户中 80% 更偏好席位制" in text
    assert "surprising: false" in text


def test_round_trip_full_fixture():
    _assert_round_trips(_full())


def test_round_trip_colon_space_inside_a_value():
    _assert_round_trips(_full(claims=[{"claim": "decision: ship it",
                                       "source": "note: meeting", "surprising": True}]))


def test_round_trip_double_quote_inside_a_value():
    _assert_round_trips(_full(concepts=[{"title": 'the "seat" unit',
                                         "summary": 'he said "no" twice'}]))


def test_round_trip_string_field_whose_value_is_exactly_no():
    """YAML 1.1 makes no/yes/on/off booleans, so safe_dump must quote them."""
    parsed = _round_trip(_full(action_items=[{"task": "no", "owner": "on"}]))
    assert parsed.action_items == [{"task": "no", "owner": "on"}]
    assert isinstance(parsed.action_items[0]["task"], str)


def test_round_trip_empty_lists_for_every_field():
    result = ExtractionResult(summary="", source_path="raw/notes.md")
    parsed = _round_trip(result)
    for name in exl.BODY_FIELDS:
        assert getattr(parsed, name) == []
    assert parsed.topics == []


def test_round_trip_empty_who_on_a_decision():
    _assert_round_trips(_full(decisions=[{"title": "t", "what": "w", "why": "y",
                                          "who": []}]))


def test_round_trip_summary_long_enough_to_wrap():
    long_summary = " ".join(["决议内容非常长" ] * 200)
    parsed = _round_trip(_full(summary=long_summary))
    assert parsed.summary == long_summary


def test_round_trip_value_containing_a_section_heading():
    """B3a: a heading is recognised at column 0 only.

    safe_dump renders this value as a multi-line quoted scalar whose continuation
    lines are indented, so a strip()-based scanner sees a phantom `entities`
    section and leaves `claims` an unterminated scalar.
    """
    result = _full(claims=[{"claim": "决议如下\n\n## Entities\n\n后半段",
                            "surprising": False}])
    _assert_round_trips(result)

    text = exl.serialize(_provenance(), result)
    # The trap is real: the value does contain an indented heading.
    assert any(line.strip() == "## Entities" and not line.startswith("## ")
               for line in text.splitlines())


def test_round_trip_frontmatter_summary_containing_a_bare_delimiter_line():
    """B6a: split_frontmatter must not close on an indented `---`."""
    result = _full(summary="第一段\n\n---\n\n第二段")
    parsed = _round_trip(result)
    assert parsed.summary == "第一段\n\n---\n\n第二段"
    # And nothing after the truncation point was lost.
    stored = exl.parse(exl.serialize(_provenance(), result))
    assert stored.provenance.prompt_version == "a1b2c3d4e5f6"
    assert stored.extraction.claims == result.claims


def _with_claims_body(text: str, body: str) -> str:
    """Rebuild the file with the claims section's items replaced by `body`.

    Claims is not the last section any more — Enumerations follows it — so the
    surgery has to put the tail back. A plain split would delete that section too,
    and every test below would be asserting against a missing-section error
    instead of the failure it names.
    """
    head, _, rest = text.partition("## Claims\n")
    return head + "## Claims\n" + body + "## Enumerations" + rest.split(
        "## Enumerations", 1)[1]


def _emptied_claims(text: str) -> str:
    """Drop the claims items, leaving a well-formed but empty section.

    This is the failure markdown has without `counts`: the file still parses, and
    the article it composes is just thinner.
    """
    return _with_claims_body(text, "\n[]\n")


def test_a_corrupted_section_count_is_a_parse_error():
    with pytest.raises(ExtractionFileError, match="counts disagree"):
        exl.parse(_emptied_claims(exl.serialize(_provenance(), _full())))


def test_a_half_deleted_item_is_a_parse_error_too():
    text = exl.serialize(_provenance(), _full())
    with pytest.raises(ExtractionFileError):
        exl.parse(text.replace("- claim: 现有客户中 80% 更偏好席位制\n", ""))


def test_a_mistyped_heading_is_a_parse_error_not_an_empty_field():
    text = exl.serialize(_provenance(), _full()).replace("## Claims", "## Clams")
    with pytest.raises(ExtractionFileError, match="missing body section"):
        exl.parse(text)


@pytest.mark.parametrize("text, match", [
    ("no frontmatter here", "no complete YAML frontmatter"),
    ("---\n: :\n---\n", "invalid frontmatter YAML"),
    ("---\njust a string\n---\n", "not a mapping"),
])
def test_parse_rejects_malformed_files(text, match):
    with pytest.raises(ExtractionFileError, match=match):
        exl.parse(text)


def test_a_section_holding_invalid_yaml_is_a_parse_error():
    text = exl.serialize(_provenance(), _full())
    with pytest.raises(ExtractionFileError, match="invalid YAML in section claims"):
        exl.parse(_with_claims_body(text, "\n- claim: 'unterminated\n"))


def test_an_empty_section_whose_count_says_zero_parses():
    text = exl.serialize(_provenance(), _full(claims=[]))
    assert exl.parse(_with_claims_body(text, "\n")).extraction.claims == []


def test_a_section_that_is_not_a_list_is_a_parse_error():
    text = exl.serialize(_provenance(), _full())
    with pytest.raises(ExtractionFileError, match="section claims is dict"):
        exl.parse(_with_claims_body(text, "\nclaim: not a list\n"))


def test_a_future_schema_version_is_not_read_as_the_current_one():
    """staleness() never compares schema_version, so parse() has to reject one.

    Left to parse, a v2 file read by v1 code yields a v1 result and B10 calls it
    fresh: the write phase then composes an article out of a payload this code
    does not understand, and nothing anywhere reports it.
    """
    text = exl.serialize(_provenance(schema_version=exl.SCHEMA_VERSION + 1), _full())
    with pytest.raises(ExtractionFileError, match="unsupported schema_version"):
        exl.parse(text)


def test_a_file_with_no_schema_version_is_a_parse_error():
    """Absent is unknown too. Every file this package writes records the field."""
    text = exl.serialize(_provenance(), _full()).replace(
        f"schema_version: {exl.SCHEMA_VERSION}\n", "")
    with pytest.raises(ExtractionFileError, match="unsupported schema_version"):
        exl.parse(text)


def test_an_unknown_schema_version_reaches_the_gate_as_absent(store):
    """Rejecting the parse is what routes a format bump into B9's re-extract."""
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m")
    path = store.extraction_path("raw/a.md")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"schema_version: {exl.SCHEMA_VERSION}", "schema_version: 99"),
        encoding="utf-8")

    stored, reason = exl.load(store, "raw/a.md")

    assert stored is None
    assert "unsupported schema_version" in reason


def test_a_v1_file_without_the_enumerations_section_reaches_the_gate_as_absent(store):
    """Why SCHEMA_VERSION moved to 2 for a field addition, unlike `connections`.

    Dropping a field was readable in both directions, so that change left the
    version alone. A *required* body section is not: a v1 file has no
    ``## Enumerations`` and this code refuses it, while v1 code reading a v2 file
    fails its own counts check over the extra key. Bumping makes the one message
    a reader gets say which side is which, and routes every pre-#41 extraction
    into B9's re-extract instead of into an article with no enumerations.
    """
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m")
    path = store.extraction_path("raw/a.md")
    v1_text = path.read_text(encoding="utf-8").split("## Enumerations")[0].replace(
        f"schema_version: {exl.SCHEMA_VERSION}", "schema_version: 1")
    path.write_text(v1_text, encoding="utf-8")

    stored, reason = exl.load(store, "raw/a.md")

    assert stored is None
    assert "unsupported schema_version" in reason


def test_an_eleven_item_enumeration_round_trips_complete_and_in_order():
    """The shape issue #41 is about: a struct's whole field list, in declaration
    order. Covered by the BODY_FIELDS loop too, but named here because a
    serializer that reordered or dropped members would be invisible downstream —
    the write phase never re-reads raw.
    """
    items = ["Trace", "Log", "Prometheus", "MaxConns", "Breaker", "Shedding",
             "Timeout", "Recover", "Metrics", "MaxBytes", "Gunzip"]
    parsed = _round_trip(_full(enumerations=[
        {"name": "MiddlewaresConf fields", "kind": "struct-fields",
         "ordered": False, "items": items}]))

    assert parsed.enumerations[0]["items"] == items


def test_extracted_at_is_utc_with_an_offset_and_seconds(store, monkeypatch):
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m")
    stored, reason = exl.load(store, "raw/a.md")
    assert reason == ""
    assert stored.provenance.extracted_at.endswith("+00:00")
    assert len(stored.provenance.extracted_at) == len("2026-08-07T11:22:33+00:00")


def test_summarize_model_is_recorded_on_the_summarize_path_only(store):
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m", extract_strategy=exl.STRATEGY_SUMMARIZE,
                summarize_model="claude-haiku-4-5")
    stored, _ = exl.load(store, "raw/a.md")
    assert stored.provenance.summarize_model == "claude-haiku-4-5"

    exl.persist(store, "raw/b.md", _full(), source_checksum="0" * 16,
                extract_model="m", extract_strategy=exl.STRATEGY_CHUNKED,
                summarize_model="claude-haiku-4-5")
    stored, _ = exl.load(store, "raw/b.md")
    assert stored.provenance.summarize_model == ""


def test_topics_are_sorted_so_two_runs_of_the_same_content_agree():
    one = exl.serialize(_provenance(), _full(topics=["b", "a", "c"]))
    two = exl.serialize(_provenance(), _full(topics=["c", "a", "b"]))
    assert one == two


# ── B9: absent, never empty-but-valid ───────────────────────────────

def test_load_reports_missing(store):
    stored, reason = exl.load(store, "raw/nope.md")
    assert stored is None and reason == "missing"


def test_load_reports_an_invalid_file(store):
    store.extraction_dir.mkdir(parents=True)
    (store.extraction_dir / "a.md").write_text("not an extraction file")
    stored, reason = exl.load(store, "raw/a.md")
    assert stored is None and reason.startswith("invalid:")


def test_load_reports_a_count_mismatch_rather_than_an_empty_extraction(store):
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m")
    path = store.extraction_path("raw/a.md")
    path.write_text(_emptied_claims(path.read_text()))
    stored, reason = exl.load(store, "raw/a.md")
    assert stored is None
    assert "counts disagree" in reason


# ── B10 / H4: the staleness matrix ──────────────────────────────────

_CURRENT = dict(source_checksum="0123456789abcdef", extract_model="claude-sonnet-4-6",
                extract_strategy=exl.STRATEGY_CHUNKED, prompt_version="a1b2c3d4e5f6")


def test_nothing_changed_is_fresh():
    assert exl.staleness(_provenance(), **_CURRENT) == ""


@pytest.mark.parametrize("field, value", [
    ("source_checksum", "ffffffffffffffff"),
    ("extract_model", "gpt-4o-mini"),
    ("extract_strategy", exl.STRATEGY_SUMMARIZE),
    ("prompt_version", "000000000000"),
])
def test_each_provenance_field_changed_independently_is_detected(field, value):
    current = dict(_CURRENT)
    current[field] = value
    reason = exl.staleness(_provenance(), **current)
    assert reason.startswith(field)


def test_summarize_model_change_is_stale_when_summarize_ran():
    prov = _provenance(extract_strategy=exl.STRATEGY_SUMMARIZE,
                       summarize_model="claude-haiku-4-5")
    current = dict(_CURRENT, extract_strategy=exl.STRATEGY_SUMMARIZE,
                   summarize_model="claude-haiku-9")
    assert exl.staleness(prov, **current).startswith("summarize_model")


def test_summarize_model_change_is_fresh_when_chunked_ran():
    """A model that never touched this extraction cannot invalidate it."""
    current = dict(_CURRENT, summarize_model="a-different-model")
    assert exl.staleness(_provenance(), **current) == ""


# ── B11-B14 / H4, H5: prompt_version ────────────────────────────────

def test_prompt_version_is_twelve_hex_digits():
    version = ex.extract_prompt_version()
    assert len(version) == 12
    assert all(c in "0123456789abcdef" for c in version)


def test_prompt_version_is_memoized_within_a_process(monkeypatch):
    calls: list[str] = []
    real = ex.load_prompt

    def counting(name):
        calls.append(name)
        return real(name)

    monkeypatch.setattr(ex, "load_prompt", counting)
    first = ex.extract_prompt_version()
    after_first = len(calls)
    assert ex.extract_prompt_version() == first
    assert len(calls) == after_first


def test_prompt_version_changes_when_only_prompt_content_changed(monkeypatch, tmp_path):
    """H4: nobody bumps a version number, and the hash still moves."""
    before = ex.extract_prompt_version()

    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name in ex.EXTRACT_STAGE_PROMPTS:
        body = "{FIELDS_LIST} {TYPES_JSON_SCHEMA}" if name == "extract-types" else "x"
        (prompts / f"{name}.md").write_text(f"[{name}] {body}")
    monkeypatch.setenv("KAAS_PROMPTS_DIR", str(prompts))
    import kb_ai.prompts as prompts_pkg
    monkeypatch.setattr(prompts_pkg, "_registry", None)

    ex.extract_prompt_version.cache_clear()
    edited = ex.extract_prompt_version()
    assert edited != before

    (prompts / "extract.md").write_text("[extract] x, and one more sentence")
    monkeypatch.setattr(prompts_pkg, "_registry", None)
    ex.extract_prompt_version.cache_clear()
    assert ex.extract_prompt_version() != edited


def test_prompt_version_changes_when_a_type_split_group_changes(monkeypatch):
    """B11: the renderings are hashed, so a code constant is not a blind spot."""
    before = ex.extract_prompt_version()
    moved = {"A": ("concepts",), "B": ("entities", "claims", "decisions",
                                       "action_items", "topics", "summary")}
    monkeypatch.setattr(ex, "TYPE_SPLIT_GROUPS_K2", moved)
    ex.extract_prompt_version.cache_clear()
    assert ex.extract_prompt_version() != before


def test_load_prompt_rejects_a_name_outside_the_extraction_stage():
    """H5: the five stub_prompts tests patch load_prompt itself and bypass this."""
    with pytest.raises(AssertionError, match="EXTRACT_STAGE_PROMPTS"):
        ex.load_prompt("merge-rewrite")


def test_a_missing_prompt_file_raises_rather_than_hashing_to_fresh(monkeypatch, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.setenv("KAAS_PROMPTS_DIR", str(empty))
    import kb_ai.prompts as prompts_pkg
    monkeypatch.setattr(prompts_pkg, "_registry", None)
    ex.extract_prompt_version.cache_clear()

    from kb_ai.prompts import NoActivePromptError
    with pytest.raises(NoActivePromptError):
        ex.extract_prompt_version()


# ── C1: one serializer, one code path ───────────────────────────────

def test_persist_and_load_are_byte_stable_given_one_extraction(store, monkeypatch):
    monkeypatch.setattr(exl, "_now_iso", lambda: "2026-08-07T11:22:33+00:00")
    result = _full()
    exl.persist(store, "raw/a.md", result, source_checksum="0" * 16,
                extract_model="m")
    first = store.extraction_path("raw/a.md").read_text()
    exl.persist(store, "raw/a.md", result, source_checksum="0" * 16,
                extract_model="m")
    assert store.extraction_path("raw/a.md").read_text() == first


# ── B7: the catalog reads the frontmatter only ──────────────────────

def test_load_header_returns_the_provenance_and_flat_payload(store):
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m")

    header, reason = exl.load_header(store, "raw/a.md")

    assert reason == ""
    assert header["source"] == "raw/a.md"
    assert header["summary"].startswith("季度评审")
    assert header["topics"] == ["billing", "pricing"]
    assert "concepts" not in header, "the body is never parsed for a catalog line"


def test_load_header_does_not_apply_the_counts_guard(store):
    """The guard protects the write phase's payload, not a catalog line."""
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m")
    path = store.extraction_path("raw/a.md")
    path.write_text(_emptied_claims(path.read_text()))

    header, reason = exl.load_header(store, "raw/a.md")

    assert reason == ""
    assert header["summary"].startswith("季度评审")
    assert exl.load(store, "raw/a.md")[0] is None


@pytest.mark.parametrize("reader", [exl.load, exl.load_header])
def test_both_readers_report_a_path_outside_raw(store, reader):
    value, reason = reader(store, "wiki/a.md")
    assert value is None
    assert reason.startswith("invalid: not a raw document path")


@pytest.mark.parametrize("reader", [exl.load, exl.load_header])
def test_both_readers_report_an_unreadable_file(store, reader, monkeypatch):
    exl.persist(store, "raw/a.md", _full(), source_checksum="0" * 16,
                extract_model="m")

    def boom(self, *args, **kwargs):
        raise OSError("Permission denied")

    monkeypatch.setattr(Path, "read_text", boom)
    value, reason = reader(store, "raw/a.md")
    assert value is None
    assert reason.startswith("unreadable:")


@pytest.mark.parametrize("text, match", [
    ("no frontmatter", "no complete YAML frontmatter"),
    ("---\n: :\n---\n", "invalid frontmatter YAML"),
    ("---\njust a string\n---\n", "not a mapping"),
])
def test_load_header_reports_a_malformed_header(store, text, match):
    store.extraction_dir.mkdir(parents=True)
    (store.extraction_dir / "a.md").write_text(text)

    header, reason = exl.load_header(store, "raw/a.md")

    assert header is None
    assert match in reason
