"""Tests for the FX4 arm driver (spec FX4, FX5).

The driver this covers replaces four shell scripts that were never committed and
were lost when ``/tmp`` was cleared on 2026-08-19, taking the scored baseline arm
with them (docs/features/supersession/scoring.md). So the policy those scripts
carried is what these tests pin: wait for the endpoint before every compile, retry
a stage *in place* before the next one is staged, a residual recorded rather than
raised, and a ``wiki/`` snapshot per stage so Size has a basis at all. The retry
ceiling is 3 rather than the policy's "one retry" -- the baseline got three passes
at stage 2 by hand, and an arm given fewer attempts than the arm it is compared
against confounds FX7.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_fx4_arm as arm  # noqa: E402

_FIXTURE = Path(__file__).resolve().parents[2] / "data" / "kb-supersession-fixture"
# Captured at import, before the autouse fixture below narrows it, so the
# production value can be asserted on.
_SHIPPED_VOLATILE = tuple(arm._VOLATILE)


@pytest.fixture(autouse=True)
def tmpdir_is_not_the_refused_one(monkeypatch):
    """pytest's ``tmp_path`` lives under ``$TMPDIR``, which the driver refuses on
    purpose. Drop that entry so the rest of the suite can use ``tmp_path``; the
    rule itself is covered by the test that names it, which puts one back.
    """
    monkeypatch.setattr(arm, "_VOLATILE", ("/tmp", "/private/tmp"))


def write(path: Path, text: str = "body\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def ok(compiled: int, cost: float = 1.0, calls: int = 10, errors=None) -> dict:
    return {"ok": True, "data": {"compiled": compiled, "errors": errors or [],
                                 "cost": {"total_cost_usd": cost, "calls": calls}}}


def case(chain: list[str]) -> dict:
    return {"shape": "A", "title": "Plan", "chain": chain, "n": len(chain)}


# ── coverage: the cases file is a rebuild, so it has to be proved ──────

def test_coverage_holds_when_the_chains_are_exactly_the_kb(tmp_path):
    write(tmp_path / "raw" / "a1.md")
    write(tmp_path / "raw" / "a2.md")

    report = arm.verify_coverage([case(["raw/a1.md", "raw/a2.md"])], tmp_path)

    assert report["ok"] is True
    assert (report["chains"], report["documents"]) == (1, 2)


def test_a_chain_naming_a_document_the_kb_does_not_have_fails(tmp_path):
    """The rebuilt file is only usable if every member resolves: ``materialize``
    raises on the first one that does not, halfway through staging.
    """
    write(tmp_path / "raw" / "a1.md")

    report = arm.verify_coverage([case(["raw/a1.md", "raw/gone.md"])], tmp_path)

    assert report["ok"] is False
    assert report["missing"] == ["raw/gone.md"]


def test_a_document_in_no_chain_is_an_orphan(tmp_path):
    """An orphan is a document the fixture holds and no stage would ever compile,
    so the arm would score a corpus smaller than the one test-set.md describes.
    """
    write(tmp_path / "raw" / "a1.md")
    write(tmp_path / "raw" / "a2.md")
    write(tmp_path / "raw" / "loose.md")

    report = arm.verify_coverage([case(["raw/a1.md", "raw/a2.md"])], tmp_path)

    assert report["ok"] is False
    assert report["orphans"] == ["raw/loose.md"]


def test_a_document_two_chains_both_claim_is_reported(tmp_path):
    write(tmp_path / "raw" / "a.md")
    write(tmp_path / "raw" / "b.md")
    write(tmp_path / "raw" / "c.md")

    report = arm.verify_coverage([case(["raw/a.md", "raw/b.md"]),
                                  case(["raw/b.md", "raw/c.md"])], tmp_path)

    assert report["shared"] == ["raw/b.md"]


def test_dotfiles_under_raw_are_not_documents(tmp_path):
    """``select_cases`` skips them, so counting them here would report an orphan
    for every one and fail a coverage check that is actually clean.
    """
    write(tmp_path / "raw" / "a1.md")
    write(tmp_path / "raw" / "a2.md")
    write(tmp_path / "raw" / ".DS_Store.md")

    assert arm.verify_coverage([case(["raw/a1.md", "raw/a2.md"])], tmp_path)["ok"]


@pytest.mark.skipif(not _FIXTURE.is_dir(), reason="fixture KB not in this checkout")
def test_the_real_fixture_rebuilds_to_18_chains_over_all_38_documents():
    """The claim the 2026-08-19 ledger entry got wrong. ``cases.json`` was recorded
    as unrecoverable because ``select_cases.py`` emits 131 candidates -- but that is
    the count against ``data/kb-knowledge``. Run against the fixture it emits the
    curated 18, and this is the test that keeps the rebuild honest.
    """
    cases = arm.rebuild_cases(_FIXTURE)
    report = arm.verify_coverage(cases, _FIXTURE)

    assert (len(cases), report["documents"]) == (18, 38)
    assert report["ok"] is True
    assert [len(members) for members in arm.stage_plan(cases)] == [18, 18, 1, 1]


# ── the endpoint wait: the guard the first driver lacked ───────────────

def test_a_live_endpoint_is_not_waited_for():
    slept = []

    assert arm.wait_for_endpoint(lambda: True, deadline_s=600, interval_s=15,
                                 sleep=slept.append, clock=lambda: 0.0)
    assert slept == []


def test_the_wait_rides_out_an_outage_and_returns_when_it_ends():
    """Both of 2026-08-18's outages were transient -- one lasted ten minutes -- and
    the driver that gave up immediately is the one that scored the wrong thing.
    """
    now = [0.0]
    probes = [False, False, False, True]

    def sleep(seconds):
        now[0] += seconds

    assert arm.wait_for_endpoint(lambda: probes.pop(0), deadline_s=600,
                                 interval_s=15, sleep=sleep, clock=lambda: now[0])
    assert now[0] == 45.0


def test_the_wait_gives_up_at_the_deadline():
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    assert not arm.wait_for_endpoint(lambda: False, deadline_s=30, interval_s=15,
                                     sleep=sleep, clock=lambda: now[0])
    assert now[0] <= 30.0


def test_a_probe_that_raises_counts_as_down_rather_than_crashing_the_arm():
    """A connection error mid-outage is HTTP 000's Python spelling. Letting it
    propagate would end an arm that is 8 USD in.
    """
    def probe():
        raise OSError("connection refused")

    assert not arm.wait_for_endpoint(probe, deadline_s=0, interval_s=15,
                                     sleep=lambda _s: None, clock=lambda: 0.0)


# ── what counts as a stage that has to be retried ─────────────────────

def test_a_stage_whose_every_member_is_recorded_compiled_is_done():
    assert not arm.stage_needs_retry(ok(18), missing=[])


def test_a_stage_with_a_member_the_kb_never_recorded_is_retried():
    """Stage 2's real history: 18 staged, 16 compiled across three passes."""
    assert arm.stage_needs_retry(ok(14), missing=["raw/a.md", "raw/b.md"])


def test_a_protocol_failure_is_a_retry():
    assert arm.stage_needs_retry({"ok": False, "error": {"code": "X"}},
                                 missing=[])


def test_errors_about_other_documents_do_not_retry_a_finished_stage():
    """A compile recomposes earlier stages' residual too, so its ``errors`` list
    can be entirely about documents this stage never staged. An error on a member
    of this stage leaves that member missing, which is what forces the retry --
    so ``missing`` is the trigger and the errors are recorded rather than acted on.
    """
    assert not arm.stage_needs_retry(ok(18, errors=[{"file": "raw/old.md"}]),
                                     missing=[])


def test_progress_is_read_by_name_so_a_retry_does_not_look_like_a_shortfall():
    """A retry compiles only what is left, so its own ``compiled`` is small by
    construction -- reading it would retry a stage that had just finished.
    """
    assert not arm.stage_needs_retry(ok(4), missing=[])


def test_the_shortfall_is_the_members_the_state_has_no_compiled_at_for():
    state = {"raw/a.md": {"compiled_at": "2026-08-19T00:00:00"},
             # completed some ops and then failed: the shape gate 2 re-queues
             "raw/b.md": {"completed_ops": ["wiki/x.md"]},
             "raw/c.md": {"compiled_at": None}}

    assert arm.stage_shortfall(["raw/a.md", "raw/b.md", "raw/c.md", "raw/d.md"],
                               state) == ["raw/b.md", "raw/c.md", "raw/d.md"]


# ── the run: sequence, retry-in-place, residual, spend ────────────────

def hooks(events, responses, *, compiled=None, wait=True):
    """Record the order of everything the arm does, and answer its compiles.

    ``compiled`` is what the KB's compile state reports after each attempt, as a
    list of path lists. That -- not the compile's own count -- is what decides
    whether a stage finished, so the fake has to model it.
    """
    recorded: set[str] = set()
    progress = list(compiled or [])

    def compile_stage(stage, attempt):
        events.append(f"compile{stage}.{attempt}")
        if progress:
            recorded.update(progress.pop(0))
        return responses.pop(0)

    return arm.Hooks(
        materialize=lambda stage, members: events.append(f"stage{stage}"),
        wait=lambda: (events.append("wait"), wait)[1],
        compile=compile_stage,
        snapshot=lambda stage: events.append(f"snap{stage}"),
        compile_state=lambda: {rel: {"compiled_at": "2026-08-19T00:00:00"}
                               for rel in recorded},
    )


def test_each_stage_is_staged_waited_compiled_and_snapshotted_in_that_order():
    events: list[str] = []
    report = arm.run_arm([["raw/a1.md"], ["raw/a2.md"]],
                         hooks(events, [ok(1), ok(1)],
                               compiled=[["raw/a1.md"], ["raw/a2.md"]]),
                         log=lambda _m: None)

    assert events == ["stage1", "wait", "compile1.1", "snap1",
                      "stage2", "wait", "compile2.1", "snap2"]
    assert report["residual"] == []


def test_a_failed_stage_is_retried_before_the_next_stage_is_staged():
    """"Retry in place" is the whole policy: staging stage 2 first would compile
    stage 1's leftovers against an article stage 2's documents had already moved.
    """
    events: list[str] = []
    arm.run_arm([["raw/a1.md", "raw/b1.md"], ["raw/a2.md"]],
                hooks(events, [ok(1), ok(1), ok(1)],
                      compiled=[["raw/a1.md"], ["raw/b1.md"], ["raw/a2.md"]]),
                log=lambda _m: None)

    assert events == ["stage1", "wait", "compile1.1", "wait", "compile1.2",
                      "snap1", "stage2", "wait", "compile2.1", "snap2"]


def test_a_retry_that_finishes_the_stage_leaves_no_residual():
    report = arm.run_arm([["raw/a1.md", "raw/b1.md"]],
                         hooks([], [ok(1), ok(1)],
                               compiled=[["raw/a1.md"], ["raw/b1.md"]]),
                         log=lambda _m: None)

    assert report["stages"][0]["compiled"] == 2
    assert report["residual"] == []


def test_a_stage_is_not_done_because_another_stages_leftovers_compiled():
    """The defect a count-based completion test has, and it is not hypothetical.
    ``compiled`` is KB-wide: gate 2 (compile.py:312-317) re-queues every document
    whose state carries no ``compiled_at``, so stage 3's compile also recomposes
    stage 2's residual. The baseline left 2 documents residual in stage 2 and
    stages 3 and 4 stage exactly 1 document each -- so a count of 3 against 1
    staged would declare stage 3 done on another stage's work, with no retry and
    nothing in the report.
    """
    events: list[str] = []
    report = arm.run_arm(
        [["raw/p3.md"]],
        hooks(events, [ok(3), ok(2)],
              compiled=[["raw/left1.md", "raw/left2.md"], ["raw/left1.md"]]),
        attempts=2, log=lambda _m: None)

    assert events.count("compile1.1") == 1 and events.count("compile1.2") == 1
    assert report["residual"] == [{"stage": 1, "staged": 1, "compiled": 0,
                                   "missing": ["raw/p3.md"], "failures": []}]


def test_one_retry_only_and_the_shortfall_is_recorded_not_raised():
    events: list[str] = []
    report = arm.run_arm([["raw/a1.md", "raw/b1.md"]],
                         hooks(events, [ok(0), ok(1)], compiled=[[], ["raw/a1.md"]]),
                         attempts=2, log=lambda _m: None)

    assert events.count("compile1.1") == 1 and events.count("compile1.2") == 1
    assert report["residual"] == [{"stage": 1, "staged": 2, "compiled": 1,
                                   "missing": ["raw/b1.md"], "failures": []}]
    assert report["stages"][0]["attempts"] == 2


def test_the_attempt_ceiling_is_configurable_because_the_baseline_needed_three():
    """Stage 2 of the baseline reached 16 of 18 over three passes (5.99 + 2.36 +
    0.03 USD), driven by hand from three separate recovery scripts. Giving the A1
    arm strictly fewer attempts than the baseline got would confound FX7, so the
    ceiling is a recorded knob rather than a constant.
    """
    events: list[str] = []
    arm.run_arm([["raw/a1.md"]], hooks(events, [ok(0), ok(0), ok(1)],
                                       compiled=[[], [], ["raw/a1.md"]]),
                attempts=3, log=lambda _m: None)

    assert [e for e in events if e.startswith("compile")] == ["compile1.1",
                                                             "compile1.2",
                                                             "compile1.3"]


def test_the_report_is_checkpointed_after_every_stage():
    """Asserted on the real ``run_arm``, not on a stub that calls the callback
    itself: the record of a stage already paid for must reach disk before the next
    stage can lose it.
    """
    seen = []
    arm.run_arm([["raw/a1.md"], ["raw/a2.md"]],
                hooks([], [ok(1), ok(1)], compiled=[["raw/a1.md"], ["raw/a2.md"]]),
                on_stage=lambda report: seen.append(len(report["stages"])),
                log=lambda _m: None)

    assert seen == [1, 2]


def test_a_stage_blocked_between_attempts_still_snapshots_what_it_wrote():
    """An arm blocked mid-stage has articles on disk from its earlier attempts --
    the 2026-08-18 shape exactly -- and Size is the reason the snapshots exist.
    """
    events: list[str] = []
    waits = [True, False]
    stage_hooks = hooks(events, [ok(0)], compiled=[[]])
    stage_hooks.wait = lambda: (events.append("wait"), waits.pop(0))[1]

    arm.run_arm([["raw/a1.md"]], stage_hooks, attempts=2, log=lambda _m: None)

    assert events == ["stage1", "wait", "compile1.1", "wait", "snap1"]


def test_an_attempt_index_travels_with_every_recorded_error():
    """Otherwise "one document failed twice" and "two documents failed" serialise
    identically, which is the ambiguity that made the baseline's write history a
    hand reconstruction.
    """
    report = arm.run_arm(
        [["raw/a1.md"]],
        hooks([], [ok(0, errors=[{"file": "raw/a1.md", "error": "timeout"}]),
                   ok(0, errors=[{"file": "raw/a1.md", "error": "timeout"}])]),
        attempts=2, log=lambda _m: None)

    assert [e["attempt"] for e in report["stages"][0]["errors"]] == [1, 2]


def test_spend_accumulates_over_every_attempt_of_every_stage():
    report = arm.run_arm([["raw/a1.md", "raw/b1.md"], ["raw/a2.md"]],
                         hooks([], [ok(1, cost=2.5, calls=30),
                                    ok(1, cost=0.5, calls=6),
                                    ok(1, cost=1.0, calls=12)],
                               compiled=[["raw/a1.md"], ["raw/b1.md"],
                                         ["raw/a2.md"]]),
                         log=lambda _m: None)

    assert report["cost_usd"] == pytest.approx(4.0)
    assert report["calls"] == 48


def test_an_endpoint_that_never_returns_aborts_before_spending():
    events: list[str] = []
    report = arm.run_arm([["raw/a1.md"], ["raw/a2.md"]],
                         hooks(events, [], wait=False), log=lambda _m: None)

    assert events == ["stage1", "wait"]
    assert report["blocked_at_stage"] == 1
    assert report["cost_usd"] == 0.0
    assert report["residual"] == [{"stage": 1, "staged": 1, "compiled": 0,
                                   "missing": ["raw/a1.md"], "failures": []}]


def test_a_protocol_failure_leaves_the_error_on_the_stage_record():
    report = arm.run_arm([["raw/a1.md"]],
                         hooks([], [{"ok": False, "error": {"code": "NO_KEY"}},
                                    {"ok": False, "error": {"code": "NO_KEY"}}]),
                         attempts=2, log=lambda _m: None)

    assert report["stages"][0]["failures"] == ["NO_KEY", "NO_KEY"]
    assert report["residual"] == [{"stage": 1, "staged": 1, "compiled": 0,
                                   "missing": ["raw/a1.md"],
                                   "failures": ["NO_KEY", "NO_KEY"]}]


def test_a_stage_that_recovered_records_its_failures_without_a_shortfall():
    """A residual keyed on a shortfall must not claim one that did not happen: the
    first attempt's failure is worth keeping, and ``missing`` empty is what says
    the stage finished anyway.
    """
    report = arm.run_arm([["raw/a1.md"]],
                         hooks([], [{"ok": False, "error": {"code": "TIMEOUT"}},
                                    ok(1)], compiled=[[], ["raw/a1.md"]]),
                         log=lambda _m: None)

    assert report["residual"] == []
    assert report["stages"][0] == {"stage": 1, "staged": 1, "compiled": 1,
                                   "attempts": 2, "failures": ["TIMEOUT"],
                                   "missing": [], "errors": []}


def test_per_document_compile_errors_are_kept_on_the_stage_record():
    """The baseline's write history had to be reconstructed by hand from driver log
    lines, because only counts were kept. These entries carry file and reason.
    """
    failure = {"file": "raw/a1.md", "error": "write timeout after 3 attempts"}
    report = arm.run_arm([["raw/a1.md"]],
                         hooks([], [ok(0, errors=[failure]), ok(0, errors=[failure])]),
                         attempts=2, log=lambda _m: None)

    assert report["stages"][0]["errors"] == [{"attempt": 1, **failure},
                                             {"attempt": 2, **failure}]


# ── the real side effects ──────────────────────────────────────────────

def test_an_http_error_means_the_gateway_is_up(monkeypatch):
    """A 401 is an answer. Treating it as down would wait out the full deadline
    against a healthy endpoint and then abort the arm.
    """
    def urlopen(_request, timeout=None):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(arm.urllib.request, "urlopen", urlopen)

    assert arm._endpoint_probe("https://gw.example/v1", "k")()


def test_a_gateway_that_answers_cleanly_is_up(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setattr(arm.urllib.request, "urlopen",
                        lambda _request, timeout=None: Response())

    assert arm._endpoint_probe("https://gw.example/v1", "k")()


def test_a_transport_failure_propagates_so_the_wait_can_catch_it(monkeypatch):
    """``wait_for_endpoint`` owns the retry, so the probe must not swallow this."""
    def urlopen(_request, timeout=None):
        raise urllib.error.URLError("no route")

    monkeypatch.setattr(arm.urllib.request, "urlopen", urlopen)

    with pytest.raises(OSError):
        arm._endpoint_probe("https://gw.example/v1", "k")()


def test_the_model_catalog_is_read_from_the_endpoint_the_arm_will_use(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def read(self):
            return b'{"data": [{"id": "claude-sonnet-4-6"}]}'

    def urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr(arm.urllib.request, "urlopen", urlopen)

    assert arm._model_catalog("https://gw.example/v1/", "k") == {
        "data": [{"id": "claude-sonnet-4-6"}]}
    assert seen == {"url": "https://gw.example/v1/models", "auth": "Bearer k"}


@pytest.mark.parametrize("failure", [
    urllib.error.HTTPError("u", 404, "Not Found", {}, None),
    urllib.error.URLError("no route"),
    ValueError("not json"),
])
def test_a_gateway_that_will_not_answer_the_question_reads_as_unknown(monkeypatch,
                                                                     failure):
    """Unlike the probe, this must not propagate. It runs once before the arm
    starts, and a gateway that is briefly down, hides ``/models`` behind a 404 or
    answers it with HTML is not a gateway missing the model -- ``wait_for_endpoint``
    owns outages, and refusing here on no evidence would block a working arm.
    """
    def urlopen(_request, timeout=None):
        raise failure

    monkeypatch.setattr(arm.urllib.request, "urlopen", urlopen)

    assert arm._model_catalog("https://gw.example/v1", "k") is None


def test_the_compile_response_is_the_last_line_of_stdout(tmp_path, monkeypatch):
    """The protocol prints one JSON line, but the compile logs whatever a model
    wrote before it -- and one of those lines can itself be JSON.
    """
    def run(_cmd, **_kwargs):
        return subprocess.CompletedProcess(
            _cmd, 0, stdout='{"ok": false, "note": "log line"}\n'
                           '{"ok": true, "data": {"compiled": 3}}\n',
            stderr="phase log\n")

    monkeypatch.setattr(arm.subprocess, "run", run)
    runner = arm._compile_runner(tmp_path, tmp_path / "kb", tmp_path, 4, arm._models("m"))

    assert runner(1, 1) == {"ok": True, "data": {"compiled": 3}}
    assert (tmp_path / "stage1-attempt1.stderr.log").read_text() == "phase log\n"


def test_a_compile_that_printed_nothing_is_a_failure_not_a_crash(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(arm.subprocess, "run",
                        lambda _cmd, **_kw: subprocess.CompletedProcess(
                            _cmd, 1, stdout="", stderr="killed\n"))
    runner = arm._compile_runner(tmp_path, tmp_path / "kb", tmp_path, 4, arm._models("m"))

    assert runner(2, 1)["error"]["code"] == "NO_RESPONSE"


def test_unparseable_stdout_is_a_failure_the_stage_can_retry(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(arm.subprocess, "run",
                        lambda _cmd, **_kw: subprocess.CompletedProcess(
                            _cmd, 0, stdout="Traceback…\n", stderr=""))
    runner = arm._compile_runner(tmp_path, tmp_path / "kb", tmp_path, 4, arm._models("m"))

    assert runner(1, 2)["error"]["code"] == "UNPARSEABLE_RESPONSE"


@pytest.mark.parametrize("url", ["gw.example/v1", "https//gw.example",
                                 "htp://gw.example", "http:/gw.example",
                                 "http://gw .example", "", "ftp://gw.example/v1"])
def test_an_unusable_base_url_is_rejected_before_the_arm_waits_on_it(url):
    """A config error is not an outage, and the exception classes do not separate
    them: measured, ``gw.example/v1`` raises ValueError, ``htp://gw.example``
    raises URLError (an OSError, so ``wait_for_endpoint`` reads it as an outage and
    burns the 900 s deadline before aborting with a misleading reason), and
    ``http://gw .example`` raises http.client.InvalidURL, which is neither and
    would crash the arm. So the URL is checked once, up front, by shape.
    """
    assert arm.unusable_base_url(url)


@pytest.mark.parametrize("url", ["https://gw.example/v1", "http://127.0.0.1:4000/v1",
                                 "https://gw.example/v1/"])
def test_a_usable_base_url_passes(url):
    assert arm.unusable_base_url(url) is None


def test_the_catalog_names_the_models_the_gateway_serves():
    catalog = {"object": "list", "data": [{"id": "claude-sonnet-4-6"},
                                          {"id": "gpt-4o-mini"}]}

    assert arm.served_model_ids(catalog) == ["claude-sonnet-4-6", "gpt-4o-mini"]


def test_a_gateway_serving_nothing_is_read_as_serving_nothing():
    """Distinct from an unreadable answer: an empty list is an answer, and it
    cannot serve the write model, so the arm must refuse rather than continue.
    """
    assert arm.served_model_ids({"data": []}) == []


@pytest.mark.parametrize("catalog", [
    {},                                  # no data key
    {"data": {}},                        # data is not a list
    {"data": [{"name": "claude"}]},      # entries carry no id
    {"data": ["claude-sonnet-4-6"]},     # entries are not objects
    [],                                  # payload is not an object
    "claude-sonnet-4-6",
    None,
])
def test_a_payload_that_is_not_a_model_list_reads_as_unknown_not_as_empty(catalog):
    """The difference decides whether the arm aborts. An unrecognised shape means
    this gateway does not answer the question, which is not evidence that it
    cannot serve the model -- so it must not read as "serves nothing".
    """
    assert arm.served_model_ids(catalog) is None


def test_a_half_written_state_file_reads_as_nothing_compiled(tmp_path):
    """The safe direction: an unreadable state file retries the stage rather than
    declaring it finished on no evidence.
    """
    (tmp_path / ".compile-state.json").write_text('{"raw/a.md": ', encoding="utf-8")

    assert arm._compile_state_reader(tmp_path)() == {}


def test_a_state_file_holding_a_list_is_not_read_as_a_map(tmp_path):
    (tmp_path / ".compile-state.json").write_text("[]", encoding="utf-8")

    assert arm._compile_state_reader(tmp_path)() == {}


def test_the_state_reader_returns_what_the_compile_recorded(tmp_path):
    (tmp_path / ".compile-state.json").write_text(
        json.dumps({"raw/a.md": {"compiled_at": "2026-08-19T00:00:00"}}),
        encoding="utf-8")

    assert arm.stage_shortfall(["raw/a.md", "raw/b.md"],
                               arm._compile_state_reader(tmp_path)()) == ["raw/b.md"]


def test_each_stage_snapshot_is_a_separate_copy_of_wiki(tmp_path):
    """Size is defined against the pre-run article, so one snapshot per stage is
    the whole point -- a single directory overwritten each time measures nothing.
    """
    kb, logs = tmp_path / "kb", tmp_path / "logs"
    write(kb / "wiki" / "a.md", "v1\n")
    logs.mkdir()
    snapshot = arm._snapshotter(kb, logs)

    snapshot(1)
    write(kb / "wiki" / "a.md", "v1 and v2\n")
    snapshot(2)

    assert (logs / "stage1-wiki" / "a.md").read_text() == "v1\n"
    assert (logs / "stage2-wiki" / "a.md").read_text() == "v1 and v2\n"


def test_a_stage_that_wrote_no_wiki_yet_snapshots_nothing(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()

    arm._snapshotter(tmp_path / "kb", logs)(1)

    assert list(logs.iterdir()) == []


# ── plan mode: the default, because an arm costs about 18 USD ──────────

def test_the_plan_names_every_stage_and_spends_nothing(tmp_path, capsys):
    write(tmp_path / "raw" / "a1.md")
    write(tmp_path / "raw" / "a2.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md", "raw/a2.md"])]),
                          encoding="utf-8")

    code = arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                     "--cases", str(cases_path), "--workers", "4"])

    out = capsys.readouterr()
    assert code == 0
    assert "stage 1: +1 document" in out.out and "stage 2: +1 document" in out.out
    # The printed command has to be the command --execute runs: an operator who
    # pastes it without a worker count gets compile.py's default of 16 instead.
    assert '"workers": 4' in out.out
    assert not (tmp_path / "arm").exists()


def test_the_plan_refuses_a_cases_file_that_does_not_cover_the_fixture(tmp_path):
    write(tmp_path / "raw" / "a1.md")
    write(tmp_path / "raw" / "orphan.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")

    assert arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                     "--cases", str(cases_path)]) == 1


def test_execute_refuses_without_gateway_credentials(tmp_path, monkeypatch):
    """The write phase is what an arm buys; an unset key fails every one of them
    after the extract and classify phases have already been paid for.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")
    for name in ("LLM_BASE_URL", "LLM_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    code = arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                     "--cases", str(cases_path), "--execute"])

    assert code == 1
    assert not (tmp_path / "arm").exists()


def test_execute_refuses_a_gateway_that_does_not_serve_the_write_model(
        tmp_path, monkeypatch, capsys):
    """The MiniMax hour, made unrepeatable. ``OPENAI_BASE_URL`` on the laptop that
    ran both arms points at a gateway serving eight MiniMax models and no Claude
    model, and KaaS falls back to that pair when ``LLM_*`` is unset. An arm launched
    there 400s on every call and reports a full residual at 0.00 USD, which reads
    like a catastrophic writer failure rather than a misconfiguration.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.minimax.io/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(arm, "_model_catalog", lambda *_a: {
        "data": [{"id": "MiniMax-M2"}, {"id": "MiniMax-Text-01"}]})
    monkeypatch.setattr(arm, "run_arm", lambda *_a, **_kw: pytest.fail(
        "the arm must not spend against a gateway missing its write model"))

    code = arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                     "--cases", str(cases_path), "--execute"])

    assert code == 1
    message = capsys.readouterr().err
    assert "claude-sonnet-4-6" in message  # what it needs
    assert "MiniMax-M2" in message         # what it found, so the fix is obvious
    assert not (tmp_path / "arm" / "kb").exists()


def test_a_gateway_that_cannot_be_asked_warns_and_runs_anyway(tmp_path,
                                                              monkeypatch, capsys):
    """The check is a guard, not a gate on the arm's right to run: a gateway that
    does not expose ``/models`` would otherwise be unusable for an arm even though
    every write would have succeeded.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(arm, "_model_catalog", lambda *_a: None)
    monkeypatch.setattr(arm, "run_arm", lambda *_a, **_kw: {
        "stages": [], "cost_usd": 1.0, "calls": 4, "residual": [],
        "blocked_at_stage": None})

    code = arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                     "--cases", str(cases_path), "--execute"])

    assert code == 0
    assert "could not" in capsys.readouterr().err  # said so rather than stayed silent
    config = json.loads(
        (tmp_path / "arm" / "logs" / "arm-report.json").read_text())["config"]
    assert config["models_verified"] is False


def test_a_verified_gateway_records_that_it_was_verified(tmp_path, monkeypatch):
    """Which the report needs for the same reason it records the models: an arm
    that produced a residual has to be readable as a writer failure or as a
    gateway that was never confirmed to serve the model.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(arm, "_model_catalog", lambda *_a: {
        "data": [{"id": "claude-sonnet-4-6"}]})
    monkeypatch.setattr(arm, "run_arm", lambda *_a, **_kw: {
        "stages": [], "cost_usd": 1.0, "calls": 4, "residual": [],
        "blocked_at_stage": None})

    arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
              "--cases", str(cases_path), "--execute"])

    config = json.loads(
        (tmp_path / "arm" / "logs" / "arm-report.json").read_text())["config"]
    assert config["models_verified"] is True


def test_an_executed_arm_leaves_its_cases_file_and_its_report_on_disk(
        tmp_path, monkeypatch):
    """The loss this driver exists to prevent. Both files are the arm's record, so
    they are written under ``--out`` and not held in the session that ran it.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(arm, "_model_catalog", lambda *_a: None)
    monkeypatch.setattr(arm, "run_arm", lambda *_a, **_kw: {
        "stages": [], "cost_usd": 3.5, "calls": 40, "residual": [],
        "blocked_at_stage": 2})

    code = arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                     "--cases", str(cases_path), "--execute"])

    logs = tmp_path / "arm" / "logs"
    assert code == 1  # a blocked arm is not a successful one
    assert json.loads((logs / "cases.json").read_text())[0]["chain"] == ["raw/a1.md"]
    assert json.loads((logs / "arm-report.json").read_text())["cost_usd"] == 3.5


@pytest.mark.parametrize("out", ["/tmp/kaas-a1", "/private/tmp/kaas-a1",
                                 "/tmp/./kaas-a1", "/tmp/../tmp/kaas-a1",
                                 "../../../../../../../../tmp/kaas-a1"])
def test_the_out_directory_may_not_be_under_tmp(tmp_path, out):
    """The one lesson the lost arm cost 18 USD to learn. The relative spelling is
    the one a literal prefix check misses, and it names the same directory.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")

    with pytest.raises(SystemExit):
        arm.main(["--fixture", str(tmp_path), "--out", out,
                  "--cases", str(cases_path)])


def test_the_out_directory_may_not_be_the_per_user_temp_directory(tmp_path,
                                                                  monkeypatch):
    """macOS clears ``$TMPDIR`` on its own schedule, which is the same failure the
    ``/tmp`` clear already cost this branch once.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")
    monkeypatch.setattr(arm, "_VOLATILE", ("/tmp", str(tmp_path)))

    with pytest.raises(SystemExit):
        arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                  "--cases", str(cases_path)])


def test_the_shipped_refusal_list_includes_the_per_user_temp_directory():
    """Asserted on the value the script ships with, not the narrowed one the
    autouse fixture installs -- otherwise the rule above is pinned by a fixture
    rather than by the driver.
    """
    assert tempfile.gettempdir() in _SHIPPED_VOLATILE
    assert "/tmp" in _SHIPPED_VOLATILE


def test_a_directory_that_merely_starts_with_the_same_letters_is_fine(tmp_path):
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")

    assert arm.main(["--fixture", str(tmp_path), "--out", "/tmpfoo/arm",
                     "--cases", str(cases_path)]) == 0


# ── the executed arm, wired for real ──────────────────────────────────

def execute(tmp_path, monkeypatch, *, responses, extra=(), git_sha="abc1234",
            record_bodies=None):
    """Run ``main --execute`` with only the gateway faked out.

    Everything else is real: the fixture is staged by ``stage_fixture.materialize``
    into a real KB, the snapshots are real copies, and the compile state is a real
    file. An argument swapped between ``fixture`` and ``kb`` would copy an empty KB
    over the fixture, which no test with ``run_arm`` monkeypatched can see.

    The faked gateway answers no model list -- which is the honest stand-in for a
    host that does not exist, keeps these tests off the network, and lets the one
    that overrides ``--model`` run unchanged. Both branches of the model check have
    their own tests above.
    """
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(arm, "_endpoint_probe", lambda *_a: (lambda: True))
    monkeypatch.setattr(arm, "_model_catalog", lambda *_a: None)

    kb = tmp_path / "arm" / "kb"
    answers = list(responses)

    def fake_compile(_cmd, **_kwargs):
        """Stand in for the compile: write what a compile would leave behind."""
        if _cmd[0] == "git":  # _arm_config reads the arm's own SHA
            return subprocess.CompletedProcess(_cmd, 0, stdout=f"{git_sha}\n",
                                               stderr="")
        if record_bodies is not None:
            record_bodies.append(json.loads(_kwargs["input"]))
        response, compiled = answers.pop(0)
        state = json.loads((kb / ".compile-state.json").read_text()) \
            if (kb / ".compile-state.json").exists() else {}
        for rel in compiled:
            state[rel] = {"checksum": "c", "compiled_at": "2026-08-19T00:00:00"}
            (kb / "wiki").mkdir(parents=True, exist_ok=True)
            (kb / "wiki" / "article.md").write_text(
                f"sources: {sorted(state)}\n", encoding="utf-8")
        (kb / ".compile-state.json").write_text(json.dumps(state),
                                                encoding="utf-8")
        return subprocess.CompletedProcess(_cmd, 0, stdout=json.dumps(response),
                                           stderr="")

    monkeypatch.setattr(arm.subprocess, "run", fake_compile)
    code = arm.main(["--fixture", str(tmp_path / "fixture"),
                     "--out", str(tmp_path / "arm"), "--execute", *extra])
    return code, tmp_path / "arm"


def fixture_of(tmp_path, *rels):
    for rel in rels:
        write(tmp_path / "fixture" / rel, f"---\ntitle: {rel}\n---\nbody\n")
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([case(list(rels))]), encoding="utf-8")
    return ["--cases", str(cases)]


def test_an_executed_arm_stages_each_version_into_the_kb_the_last_stage_wrote(
        tmp_path, monkeypatch):
    """FX2's whole point: stage 2 must merge into the article stage 1 wrote, so the
    KB accumulates rather than being rebuilt, and the fixture is never written to.
    """
    cases_arg = fixture_of(tmp_path, "raw/a1.md", "raw/a2.md")

    code, out = execute(tmp_path, monkeypatch, extra=cases_arg, responses=[
        ({"ok": True, "data": {"compiled": 1, "errors": [],
                               "cost": {"total_cost_usd": 1.0, "calls": 5}}},
         ["raw/a1.md"]),
        ({"ok": True, "data": {"compiled": 1, "errors": [],
                               "cost": {"total_cost_usd": 2.0, "calls": 7}}},
         ["raw/a2.md"]),
    ])

    assert code == 0
    assert sorted(p.name for p in (out / "kb" / "raw").iterdir()) == ["a1.md",
                                                                     "a2.md"]
    assert sorted(p.name for p in (tmp_path / "fixture" / "raw").iterdir()) == [
        "a1.md", "a2.md"]  # the fixture is read-only to an arm
    assert (out / "logs" / "stage1-wiki").is_dir()
    assert (out / "logs" / "stage2-wiki" / "article.md").read_text() != \
        (out / "logs" / "stage1-wiki" / "article.md").read_text()


def test_the_report_describes_the_arm_and_not_only_its_totals(tmp_path,
                                                              monkeypatch):
    """FX7 compares the A1 arm against a written baseline whose worker count and
    models are unrecoverable. This arm's own record has to be self-describing.
    """
    cases_arg = fixture_of(tmp_path, "raw/a1.md")

    _code, out = execute(tmp_path, monkeypatch, extra=[*cases_arg, "--workers", "4"],
                         responses=[
        ({"ok": True, "data": {"compiled": 1, "errors": [],
                               "cost": {"total_cost_usd": 1.0, "calls": 5}}},
         ["raw/a1.md"]),
    ])

    report = json.loads((out / "logs" / "arm-report.json").read_text())
    assert report["config"]["workers"] == 4
    # 3, not the constant: the choice is that an arm compared against one which
    # got three hand-driven passes must not be given fewer.
    assert report["config"]["attempts"] == 3
    assert report["config"]["repo_head"] == "abc1234"  # the code that wrote them
    assert report["config"]["fixture"].endswith("fixture")
    # The models the compile was actually told to use, not an environment variable
    # it ignores: run_compile defaults all three to claude-sonnet-4-6 and reads
    # LLM_MODEL only for the summarize fallback, so recording that would publish a
    # model that wrote nothing.
    assert report["config"]["models"] == {"extract_model": "claude-sonnet-4-6",
                                          "compile_model": "claude-sonnet-4-6",
                                          "write_model": "claude-sonnet-4-6"}


def test_the_compile_is_told_which_models_to_use_rather_than_inheriting_them(
        tmp_path, monkeypatch):
    """So the report's model record is the truth and the arm is reproducible: the
    same three names go into the request body that go into the config block.
    """
    cases_arg = fixture_of(tmp_path, "raw/a1.md")
    bodies: list[dict] = []

    _code, out = execute(tmp_path, monkeypatch,
                         extra=[*cases_arg, "--model", "claude-opus-5"],
                         responses=[
        ({"ok": True, "data": {"compiled": 1, "errors": [],
                               "cost": {"total_cost_usd": 1.0, "calls": 5}}},
         ["raw/a1.md"]),
    ], record_bodies=bodies)

    assert bodies[0]["write_model"] == "claude-opus-5"
    assert bodies[0]["extract_model"] == "claude-opus-5"
    report = json.loads((out / "logs" / "arm-report.json").read_text())
    assert set(report["config"]["models"].values()) == {"claude-opus-5"}


def test_an_arm_may_not_run_with_no_attempts(tmp_path):
    """``--attempts 0`` would snapshot every stage, call nothing, and write a report
    claiming a full four-stage residual at 0.00 USD -- a completed-looking arm that
    never ran.
    """
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")

    for bad in (["--attempts", "0"], ["--workers", "0"]):
        with pytest.raises(SystemExit):
            arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                      "--cases", str(cases_path), *bad])


def test_execute_refuses_a_base_url_that_cannot_be_reached_by_shape(tmp_path,
                                                                   monkeypatch):
    """Checked in main, before any hook is built, so the arm fails in a second
    with the reason rather than after the 900 s wait with the wrong one.
    """
    cases_arg = fixture_of(tmp_path, "raw/a1.md")
    monkeypatch.setenv("LLM_BASE_URL", "htp://gw.example")
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setattr(arm, "run_arm", lambda *_a, **_kw: pytest.fail(
        "an unusable base URL must be caught before the arm starts"))

    assert arm.main(["--fixture", str(tmp_path / "fixture"), *cases_arg,
                     "--out", str(tmp_path / "arm"), "--execute"]) == 1


def test_an_unknown_repo_head_is_recorded_as_unknown(tmp_path, monkeypatch):
    """A detached or missing checkout must not make the report silently claim a
    SHA, since ``repo_head`` is what pins which code wrote the articles.
    """
    cases_arg = fixture_of(tmp_path, "raw/a1.md")

    _code, out = execute(tmp_path, monkeypatch, extra=cases_arg, git_sha="",
                         responses=[
        ({"ok": True, "data": {"compiled": 1, "errors": [],
                               "cost": {"total_cost_usd": 1.0, "calls": 5}}},
         ["raw/a1.md"]),
    ])

    report = json.loads((out / "logs" / "arm-report.json").read_text())
    assert report["config"]["repo_head"] == "unknown"


def test_the_report_survives_a_stage_that_never_finishes(tmp_path, monkeypatch):
    """Written per stage, not once at the end: a crash or a Ctrl-C mid-arm must not
    take the record of the stages already paid for.
    """
    cases_arg = fixture_of(tmp_path, "raw/a1.md", "raw/a2.md")
    monkeypatch.setattr(arm, "run_arm", _exploding_run_arm)

    with pytest.raises(RuntimeError):
        execute(tmp_path, monkeypatch, extra=cases_arg, responses=[])

    report = json.loads(
        (tmp_path / "arm" / "logs" / "arm-report.json").read_text())
    assert report["stages"][0]["compiled"] == 1
    assert report["cost_usd"] == 1.25


def _exploding_run_arm(_staged, _hooks, *, attempts=2, log=print, on_stage=None):
    """One stage lands and is checkpointed, then the arm dies."""
    report = {"stages": [{"stage": 1, "staged": 1, "compiled": 1, "attempts": 1,
                          "failures": [], "missing": [], "errors": []}],
              "cost_usd": 1.25, "calls": 9, "residual": [],
              "blocked_at_stage": None}
    if on_stage:
        on_stage(report)
    raise RuntimeError("endpoint died mid-arm")


def test_a_second_run_into_a_used_directory_is_refused(tmp_path, monkeypatch):
    """``materialize`` is additive and the report is written by name, so a re-run
    resumes on top of old state, overwrites the previous report and merges into the
    old snapshots -- silently, and after the first run's spend is already gone.
    """
    cases_arg = fixture_of(tmp_path, "raw/a1.md")
    (tmp_path / "arm" / "kb" / "raw").mkdir(parents=True)
    write(tmp_path / "arm" / "kb" / "raw" / "a1.md")
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.setenv("LLM_API_KEY", "k")

    def must_not_run(*_a, **_kw):
        raise AssertionError("a used --out must be refused before any spend")

    monkeypatch.setattr(arm, "run_arm", must_not_run)

    assert arm.main(["--fixture", str(tmp_path / "fixture"), *cases_arg,
                     "--out", str(tmp_path / "arm"), "--execute"]) == 1


def test_resume_is_how_a_blocked_arm_is_continued(tmp_path, monkeypatch):
    cases_arg = fixture_of(tmp_path, "raw/a1.md")
    (tmp_path / "arm" / "kb" / "raw").mkdir(parents=True)
    write(tmp_path / "arm" / "kb" / "raw" / "a1.md")

    code, _out = execute(tmp_path, monkeypatch, extra=[*cases_arg, "--resume"],
                         responses=[
        ({"ok": True, "data": {"compiled": 1, "errors": [],
                               "cost": {"total_cost_usd": 0.1, "calls": 2}}},
         ["raw/a1.md"]),
    ])

    assert code == 0
