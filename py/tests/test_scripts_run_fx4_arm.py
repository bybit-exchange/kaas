"""Tests for the FX4 arm driver (spec FX4, FX5).

The driver this covers replaces four shell scripts that were never committed and
were lost when ``/tmp`` was cleared on 2026-08-19, taking the scored baseline arm
with them (docs/features/supersession/scoring.md). So the policy those scripts
carried is what these tests pin: wait for the endpoint before every compile, one
retry per stage taken *in place* before the next stage is staged, a residual
recorded rather than raised, and a ``wiki/`` snapshot per stage so Size has a
basis at all.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_fx4_arm as arm  # noqa: E402

_FIXTURE = Path(__file__).resolve().parents[2] / "data" / "kb-supersession-fixture"


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

def test_a_stage_that_compiled_everything_cleanly_is_done():
    assert not arm.stage_needs_retry(ok(18), compiled_so_far=18, staged=18)


def test_a_stage_that_left_documents_uncompiled_is_retried():
    """Stage 2's real history: 18 staged, 16 compiled across three passes."""
    assert arm.stage_needs_retry(ok(14), compiled_so_far=14, staged=18)


def test_errors_are_a_retry_even_when_the_count_is_complete():
    assert arm.stage_needs_retry(ok(18, errors=["boom"]), compiled_so_far=18,
                                 staged=18)


def test_a_protocol_failure_is_a_retry():
    assert arm.stage_needs_retry({"ok": False, "error": {"code": "X"}},
                                 compiled_so_far=0, staged=18)


def test_progress_is_counted_across_a_stage_attempts_not_within_one():
    """A retry compiles only what is left, so its own ``compiled`` is small by
    construction -- reading it alone would retry a stage that had just finished.
    """
    assert not arm.stage_needs_retry(ok(4), compiled_so_far=18, staged=18)


# ── the run: sequence, retry-in-place, residual, spend ────────────────

def hooks(events, responses, wait=True):
    """Record the order of everything the arm does, and answer its compiles."""
    return arm.Hooks(
        materialize=lambda stage, members: events.append(f"stage{stage}", ),
        wait=lambda: (events.append("wait"), wait)[1],
        compile=lambda stage, attempt: (events.append(f"compile{stage}.{attempt}"),
                                        responses.pop(0))[1],
        snapshot=lambda stage: events.append(f"snap{stage}"),
    )


def test_each_stage_is_staged_waited_compiled_and_snapshotted_in_that_order():
    events: list[str] = []
    report = arm.run_arm([["raw/a1.md"], ["raw/a2.md"]],
                         hooks(events, [ok(1), ok(1)]), log=lambda _m: None)

    assert events == ["stage1", "wait", "compile1.1", "snap1",
                      "stage2", "wait", "compile2.1", "snap2"]
    assert report["residual"] == []


def test_a_failed_stage_is_retried_before_the_next_stage_is_staged():
    """"Retry in place" is the whole policy: staging stage 2 first would compile
    stage 1's leftovers against an article stage 2's documents had already moved.
    """
    events: list[str] = []
    arm.run_arm([["raw/a1.md", "raw/b1.md"], ["raw/a2.md"]],
                hooks(events, [ok(1), ok(1), ok(1)]), log=lambda _m: None)

    assert events == ["stage1", "wait", "compile1.1", "wait", "compile1.2",
                      "snap1", "stage2", "wait", "compile2.1", "snap2"]


def test_a_retry_that_finishes_the_stage_leaves_no_residual():
    """The stage's progress is the sum of its attempts. Reading the retry's own
    ``compiled`` instead would record a residual for a stage that had completed --
    and stage 2 of the baseline arm took three passes, so this is the normal case.
    """
    report = arm.run_arm([["raw/a1.md", "raw/b1.md"]],
                         hooks([], [ok(1), ok(1)]), log=lambda _m: None)

    assert report["stages"][0]["compiled"] == 2
    assert report["residual"] == []


def test_one_retry_only_and_the_shortfall_is_recorded_not_raised():
    events: list[str] = []
    report = arm.run_arm([["raw/a1.md", "raw/b1.md"]],
                         hooks(events, [ok(0), ok(1)]), log=lambda _m: None)

    assert events.count("compile1.1") == 1 and events.count("compile1.2") == 1
    assert report["residual"] == [{"stage": 1, "staged": 2, "compiled": 1}]
    assert report["stages"][0]["attempts"] == 2


def test_spend_accumulates_over_every_attempt_of_every_stage():
    report = arm.run_arm([["raw/a1.md", "raw/b1.md"], ["raw/a2.md"]],
                         hooks([], [ok(1, cost=2.5, calls=30),
                                    ok(1, cost=0.5, calls=6),
                                    ok(1, cost=1.0, calls=12)]),
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


def test_a_protocol_failure_leaves_the_error_on_the_stage_record():
    report = arm.run_arm([["raw/a1.md"]],
                         hooks([], [{"ok": False, "error": {"code": "NO_KEY"}},
                                    {"ok": False, "error": {"code": "NO_KEY"}}]),
                         log=lambda _m: None)

    assert report["stages"][0]["failures"] == ["NO_KEY", "NO_KEY"]
    assert report["residual"] == [{"stage": 1, "staged": 1, "compiled": 0}]


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
    runner = arm._compile_runner(tmp_path, tmp_path / "kb", tmp_path, workers=4)

    assert runner(1, 1) == {"ok": True, "data": {"compiled": 3}}
    assert (tmp_path / "stage1-attempt1.stderr.log").read_text() == "phase log\n"


def test_a_compile_that_printed_nothing_is_a_failure_not_a_crash(tmp_path,
                                                                monkeypatch):
    monkeypatch.setattr(arm.subprocess, "run",
                        lambda _cmd, **_kw: subprocess.CompletedProcess(
                            _cmd, 1, stdout="", stderr="killed\n"))
    runner = arm._compile_runner(tmp_path, tmp_path / "kb", tmp_path, workers=4)

    assert runner(2, 1)["error"]["code"] == "NO_RESPONSE"


def test_unparseable_stdout_is_a_failure_the_stage_can_retry(tmp_path,
                                                            monkeypatch):
    monkeypatch.setattr(arm.subprocess, "run",
                        lambda _cmd, **_kw: subprocess.CompletedProcess(
                            _cmd, 0, stdout="Traceback…\n", stderr=""))
    runner = arm._compile_runner(tmp_path, tmp_path / "kb", tmp_path, workers=4)

    assert runner(1, 2)["error"]["code"] == "UNPARSEABLE_RESPONSE"


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
                     "--cases", str(cases_path)])

    out = capsys.readouterr()
    assert code == 0
    assert "stage 1: +1 document" in out.out and "stage 2: +1 document" in out.out
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
    monkeypatch.setattr(arm, "run_arm", lambda *_a, **_kw: {
        "stages": [], "cost_usd": 3.5, "calls": 40, "residual": [],
        "blocked_at_stage": 2})

    code = arm.main(["--fixture", str(tmp_path), "--out", str(tmp_path / "arm"),
                     "--cases", str(cases_path), "--execute"])

    logs = tmp_path / "arm" / "logs"
    assert code == 1  # a blocked arm is not a successful one
    assert json.loads((logs / "cases.json").read_text())[0]["chain"] == ["raw/a1.md"]
    assert json.loads((logs / "arm-report.json").read_text())["cost_usd"] == 3.5


def test_the_out_directory_may_not_be_under_tmp(tmp_path):
    """The one lesson the lost arm cost 18 USD to learn."""
    write(tmp_path / "raw" / "a1.md")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([case(["raw/a1.md"])]), encoding="utf-8")

    with pytest.raises(SystemExit):
        arm.main(["--fixture", str(tmp_path), "--out", "/tmp/kaas-a1",
                  "--cases", str(cases_path)])
