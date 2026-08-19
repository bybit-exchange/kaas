"""Drive one FX4 arm end to end: stage, compile, snapshot, audit (spec FX4, FX5).

This is the artifact whose absence stopped the branch. The baseline arm ran from
four shell scripts under ``/tmp`` that were never committed, and when ``/tmp`` was
cleared on 2026-08-19 it took them, the 27 scored articles and the logs with it --
so the arm cannot be re-read, only re-quoted from
[scoring.md](../../docs/features/supersession/scoring.md). Everything that made
that loss possible is fixed here rather than described: the driver is versioned,
its output directory may not be under ``/tmp``, and it snapshots ``wiki/`` per
stage so Size has a basis instead of a single absolute byte count.

The policy is the baseline run's, recorded in the ledger's 2026-08-18 entries and
paid for twice by outages:

- **Wait for the endpoint before every compile.** Both of that night's outages were
  transient and one lasted ten minutes. The first driver gave up into them; the
  finish driver rode them out, which is why the arm completed at all.
- **Retry a stage in place.** Staging the next version first would compile a
  leftover document against an article the next version had already moved, which
  scores the wrong thing silently. The written policy is one retry; the default
  here is three attempts, because the baseline got three passes at stage 2 by hand
  and an arm with fewer attempts than the arm it is compared against confounds FX7.
  ``--attempts`` sets it and the report records it.
- **Record the residual and carry on.** Stage 2 finished 16 of its 18 documents
  and the arm is still the measurement; a driver that aborted there would have
  spent 8 USD for nothing.
- **Decide a stage by name, never by count.** ``compiled`` in a compile's response
  is KB-wide -- gate 2 re-queues every document with no ``compiled_at``, so a later
  stage's run also recomposes an earlier stage's residual. Stages 3 and 4 stage one
  document each and the baseline left two residual in stage 2, so a count would
  declare stage 3 finished on stage 2's work.

``cases.json`` is rebuilt rather than shipped. It is derived, deterministic and
free: ``select_cases`` run against the *fixture* emits the curated 18 chains over
all 38 documents (the 131 candidates the ledger recorded is its count against
``data/kb-knowledge``, a different KB). ``--cases`` is still accepted for an arm
that must reuse a specific file.

Plan by default, spend only when asked -- ``stage_fixture.py``'s stance, and an arm
measured at 17.99 USD earns it::

    uv run python scripts/run_fx4_arm.py --out ~/kaas-arms/a1
    uv run python scripts/run_fx4_arm.py --out ~/kaas-arms/a1 --execute

The baseline arm needs the code as it stood before A1, so point ``--repo`` at a
worktree of ``bd8252e``; the default is this checkout, which is the A1 arm.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import select_cases as select_cases_module  # noqa: E402
import stage_fixture  # noqa: E402

from kb_ai.storage.store import KBStore  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "data" / "kb-supersession-fixture"
# The directory that ate the baseline arm, plus the per-user one macOS clears on
# its own schedule. Compared against a resolved path, so a relative or symlinked
# spelling of the same directory is caught too.
_VOLATILE = ("/tmp", "/private/tmp", tempfile.gettempdir())
_WAIT_DEADLINE_S = 900.0
_WAIT_INTERVAL_S = 15.0
# The written policy is one retry. The baseline got more than that -- stage 2
# reached 16 of 18 over three passes, driven by hand from three recovery scripts --
# so giving the A1 arm strictly fewer attempts than the arm it is compared against
# would confound FX7. Three by default, and recorded in the report either way.
_ATTEMPTS_PER_STAGE = 3


def rebuild_cases(fixture_kb: Path) -> list[dict]:
    """The 18 curated chains, derived from the fixture instead of stored."""
    return select_cases_module.select_cases(KBStore(str(fixture_kb)))


def stage_plan(cases: list[dict]) -> list[list[str]]:
    return stage_fixture.stages(cases)


def verify_coverage(cases: list[dict], fixture_kb: Path) -> dict:
    """Prove a cases file describes exactly the KB it will be staged from.

    Two failures, both silent otherwise. A member the KB does not hold raises out
    of ``materialize`` halfway through a stage, after earlier documents have been
    copied. A document no chain names is never staged at all, so the arm scores a
    corpus smaller than the one test-set.md labels -- and nothing downstream
    notices, because every article it does write looks fine.
    """
    members = [rel for case in cases for rel in case["chain"]]
    counts = Counter(members)
    # The selector's own enumeration, not a second copy of it: a coverage check
    # that counted documents by a different rule than the one that built the
    # chains would report orphans that are not orphans.
    on_disk = set(select_cases_module._raw_documents(KBStore(str(fixture_kb))))

    missing = sorted(set(counts) - on_disk)
    orphans = sorted(on_disk - set(counts))
    return {
        "ok": not missing and not orphans,
        "chains": len(cases),
        "documents": len(on_disk),
        "missing": missing,
        "orphans": orphans,
        # Reported, not fatal: a document can be the later version of one chain
        # and the earlier of another, and stage_fixture stages it at its
        # shallowest depth on purpose.
        "shared": sorted(rel for rel, n in counts.items() if n > 1),
    }


def wait_for_endpoint(probe: Callable[[], bool], *, deadline_s: float,
                      interval_s: float, sleep: Callable[[float], None],
                      clock: Callable[[], float]) -> bool:
    """Poll until the gateway answers, or until waiting would pass the deadline.

    A probe that raises counts as down. Mid-outage that is an ``OSError`` from the
    socket layer -- curl's HTTP 000 -- and letting it propagate would end an arm
    that is already several dollars in.
    """
    start = clock()
    while True:
        try:
            if probe():
                return True
        except OSError:
            pass
        if clock() - start + interval_s > deadline_s:
            return False
        sleep(interval_s)


def stage_shortfall(members: list[str], state: dict) -> list[str]:
    """This stage's documents the KB does not record as compiled, by name.

    By name because ``compiled`` in a compile's response is KB-wide, not this
    stage's: gate 2 (``compile.py:312-317``) re-queues every document whose state
    carries no ``compiled_at``, so a later stage's run also recomposes an earlier
    stage's residual. Stages 3 and 4 stage one document each and the baseline left
    two residual in stage 2, so a count-based test would declare stage 3 finished
    on stage 2's work -- no retry, nothing in the report, and the chain collapsed
    onto the single-run write path FX2 exists to avoid.
    """
    return [rel for rel in members
            if not (state.get(rel) or {}).get("compiled_at")]


def stage_needs_retry(response: dict, *, missing: list[str]) -> bool:
    """Whether this stage has unfinished work after the attempt just made.

    A per-document error is not a trigger. The compile recomposes earlier stages'
    residual too, so its ``errors`` can be entirely about documents this stage
    never staged -- while an error on a member of *this* stage leaves that member
    missing, which is the trigger. So the errors are recorded rather than acted on,
    and the shortfall decides.
    """
    if not response.get("ok"):
        return True
    return bool(missing)


@dataclass
class Hooks:
    """The five side effects, injected so the policy above can be tested."""
    materialize: Callable[[int, list[str]], None]
    wait: Callable[[], bool]
    compile: Callable[[int, int], dict]
    snapshot: Callable[[int], None]
    compile_state: Callable[[], dict]


def run_arm(staged: list[list[str]], hooks: Hooks, *,
            attempts: int = _ATTEMPTS_PER_STAGE,
            log: Callable[[str], None] = print,
            on_stage: Callable[[dict], None] | None = None) -> dict:
    """Every stage in order, retried in place, with the spend counted.

    ``on_stage`` is called with the report after each stage so the caller can
    checkpoint it. A driver whose whole reason for existing is not losing the
    arm's record must not hold that record only in memory until the end.
    """
    report: dict = {"stages": [], "cost_usd": 0.0, "calls": 0, "residual": [],
                    "blocked_at_stage": None}

    def close_stage(record: dict) -> None:
        # A residual is a shortfall, so a stage that failed an attempt and then
        # recovered does not have one. Its failures stay on the stage record --
        # dropping them would lose the retry history, and recording them here
        # would claim a shortfall that did not happen.
        if record["missing"]:
            report["residual"].append({"stage": record["stage"],
                                       "staged": record["staged"],
                                       "compiled": record["compiled"],
                                       "missing": record["missing"],
                                       "failures": list(record["failures"])})
        if on_stage:
            on_stage(report)

    for stage, members in enumerate(staged, 1):
        hooks.materialize(stage, members)
        record = {"stage": stage, "staged": len(members), "compiled": 0,
                  "attempts": 0, "failures": [], "missing": list(members),
                  "errors": []}
        report["stages"].append(record)
        log(f"stage {stage}: {len(members)} document(s) staged")

        for attempt in range(1, attempts + 1):
            if not hooks.wait():
                report["blocked_at_stage"] = stage
                log(f"stage {stage}: endpoint never came back, arm stopped "
                    f"after {report['cost_usd']:.4f} USD")
                close_stage(record)
                return report

            response = hooks.compile(stage, attempt)
            record["attempts"] = attempt
            data = response.get("data") or {}
            cost = data.get("cost") or {}
            report["cost_usd"] += float(cost.get("total_cost_usd") or 0.0)
            report["calls"] += int(cost.get("calls") or 0)
            record["errors"].extend(data.get("errors") or [])
            if not response.get("ok"):
                code = (response.get("error") or {}).get("code") or "UNKNOWN"
                record["failures"].append(code)

            record["missing"] = stage_shortfall(members, hooks.compile_state())
            record["compiled"] = len(members) - len(record["missing"])
            log(f"stage {stage} attempt {attempt}: "
                f"{record['compiled']}/{len(members)} compiled, "
                f"{report['cost_usd']:.4f} USD so far")

            if not stage_needs_retry(response, missing=record["missing"]):
                break

        hooks.snapshot(stage)
        close_stage(record)
    return report


# ── the real side effects ──────────────────────────────────────────────

def _endpoint_probe(base_url: str, api_key: str) -> Callable[[], bool]:
    """A gateway that answers anything at all is up.

    An HTTP error is an answer -- 401 from a key the arm will not use still proves
    the endpoint is serving -- so only a transport failure counts as down, and that
    one propagates for ``wait_for_endpoint`` to catch as the OSError it is.
    """
    url = base_url.rstrip("/") + "/models"

    def probe() -> bool:
        try:
            request = urllib.request.Request(
                url, headers={"Authorization": f"Bearer {api_key}"})
            with urllib.request.urlopen(request, timeout=20):
                return True
        except urllib.error.HTTPError:
            return True
        except ValueError as exc:
            # A base URL with no scheme is a configuration error, not an outage:
            # waiting out the deadline for it would burn 15 minutes and then abort.
            raise SystemExit(f"LLM_BASE_URL is not a usable URL ({url}): {exc}")
    return probe


def _compile_runner(repo: Path, kb: Path, logs: Path,
                    workers: int) -> Callable[[int, int], dict]:
    """Run the compile out of process, against whichever checkout ``repo`` is.

    Out of process because the baseline arm is the pre-A1 code in a worktree, and
    the point of an arm is which code wrote the articles.
    """
    body = json.dumps({"data_dir": str(kb), "workers": workers})

    def compile_stage(stage: int, attempt: int) -> dict:
        # Deliberately no timeout: a stage's writes climb a 300 s per-call ladder
        # and one baseline group took 931 s before landing, so a wall here would
        # kill work that was about to succeed. The operator watching is the timeout.
        proc = subprocess.run(["uv", "run", "python", "-m", "kb_ai", "compile"],
                              cwd=repo / "py", input=body, capture_output=True,
                              text=True)
        prefix = logs / f"stage{stage}-attempt{attempt}"
        prefix.with_suffix(".stdout.json").write_text(proc.stdout,
                                                      encoding="utf-8")
        prefix.with_suffix(".stderr.log").write_text(proc.stderr, encoding="utf-8")
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        if not lines:
            return {"ok": False, "error": {"code": "NO_RESPONSE"}}
        try:
            return json.loads(lines[-1])
        except json.JSONDecodeError:
            return {"ok": False, "error": {"code": "UNPARSEABLE_RESPONSE"}}
    return compile_stage


def _compile_state_reader(kb: Path) -> Callable[[], dict]:
    """Re-read ``.compile-state.json`` after every attempt.

    A fresh ``KBStore`` per call on purpose: the file is rewritten by the compile
    subprocess, so anything cached in this process is a stale answer to the only
    question that decides whether a stage is done.
    """
    def compile_state() -> dict:
        try:
            state = KBStore(str(kb)).load_compile_state()
        except (OSError, ValueError):
            # A missing or half-written state file reads as "nothing compiled",
            # which retries rather than declaring a stage finished on no evidence.
            return {}
        return state if isinstance(state, dict) else {}
    return compile_state


def _snapshotter(kb: Path, logs: Path) -> Callable[[int], None]:
    """``cp -a`` per stage, ~750 KB each, which is what Size is defined against.

    Neither FX4 driver did this, so after stage 1 there was no pre-run article to
    compare and the column was unmeasurable on both arms.
    """
    def snapshot(stage: int) -> None:
        wiki = kb / "wiki"
        if wiki.is_dir():
            shutil.copytree(wiki, logs / f"stage{stage}-wiki", dirs_exist_ok=True)
    return snapshot


def _plan_lines(staged: list[list[str]], kb: Path, repo: Path,
                workers: int) -> list[str]:
    """The compile each stage runs, with every parameter the arm will really use.

    ``workers`` is in the line because it is a comparability variable, not a
    performance knob: concurrent load is what makes the 300 s write timeouts more
    likely, the baseline's count is unrecoverable, and a plan line that omitted it
    would have an operator paste a 16-worker compile (compile.py's own default)
    where ``--execute`` runs a different number.
    """
    return [f"stage {i}: +{len(members)} document(s) → "
            f"(cd {repo / 'py'} && echo "
            f"'{{\"data_dir\": \"{kb}\", \"workers\": {workers}}}' | "
            f"uv run python -m kb_ai compile)"
            for i, members in enumerate(staged, 1)]


def _volatile(out: Path) -> str | None:
    """The volatile directory ``out`` resolves into, if any.

    Resolved rather than string-prefixed: ``/tmp/../tmp/x``, a relative walk up to
    ``/tmp`` and a symlink pointing there all name the directory that destroyed the
    baseline arm, and none of them starts with ``/tmp``.
    """
    resolved = out.expanduser().resolve()
    for candidate in _VOLATILE:
        base = Path(candidate).resolve()
        if resolved == base or base in resolved.parents:
            return str(base)
    return None


def _arm_config(args: argparse.Namespace, fixture: Path, kb: Path) -> dict:
    """What the arm was, in the arm's own record.

    FX7 compares this arm against a baseline whose worker count, models and
    extract strategy are unrecoverable, and the baseline's write history had to be
    reconstructed by hand from driver log lines. Everything that decides what the
    articles look like is written down here instead.
    """
    head = subprocess.run(["git", "-C", args.repo, "rev-parse", "HEAD"],
                          capture_output=True, text=True)
    return {
        "repo": args.repo,
        "repo_head": head.stdout.strip() or "unknown",
        "fixture": str(fixture),
        "kb": str(kb),
        "workers": args.workers,
        "attempts": args.attempts,
        "resumed": bool(args.resume),
        # Read from the environment the compile subprocess inherits, not from a
        # copy of compile.py's defaults, which would go stale.
        "env": {name: os.environ.get(name) or ""
                for name in ("LLM_MODEL", "LLM_EXTRACT_STRATEGY",
                             "LLM_SUMMARIZE_MODEL", "LLM_BASE_URL")},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True,
                        help="persistent directory for the arm's KB and logs")
    parser.add_argument("--fixture", default=str(_FIXTURE),
                        help="the KB holding every version")
    parser.add_argument("--cases", help="reuse this cases file instead of "
                                        "rebuilding it from the fixture")
    parser.add_argument("--repo", default=str(_REPO),
                        help="checkout whose code writes the articles "
                             "(a bd8252e worktree for the baseline arm)")
    parser.add_argument("--workers", type=int, default=8,
                        help="compile workers; recorded in the report because "
                             "concurrency changes how often writes time out")
    parser.add_argument("--attempts", type=int, default=_ATTEMPTS_PER_STAGE,
                        help="attempts per stage before the residual is recorded")
    parser.add_argument("--resume", action="store_true",
                        help="continue into an --out that already holds a KB")
    parser.add_argument("--execute", action="store_true",
                        help="run the compiles; this is what spends ~18 USD")
    args = parser.parse_args(argv)

    out = Path(args.out).expanduser()
    volatile = _volatile(out)
    if volatile:
        parser.error(f"--out resolves into {volatile}, which is cleared without "
                     "warning: that is what destroyed the baseline arm")

    fixture = Path(args.fixture)
    cases = (json.loads(Path(args.cases).read_text(encoding="utf-8"))
             if args.cases else rebuild_cases(fixture))
    coverage = verify_coverage(cases, fixture)
    print(f"{coverage['chains']} chains over {coverage['documents']} documents"
          + (f", {len(coverage['shared'])} shared between two chains"
             if coverage["shared"] else ""))
    if not coverage["ok"]:
        print(f"coverage is not exact — missing: {coverage['missing']}, "
              f"orphans: {coverage['orphans']}", file=sys.stderr)
        return 1

    staged = stage_plan(cases)
    kb, logs = out / "kb", out / "logs"
    for line in _plan_lines(staged, kb, Path(args.repo), args.workers):
        print(line)

    if not args.execute:
        print(f"\n{len(staged)} stages planned, nothing written and nothing spent. "
              "Re-run with --execute to run the arm (~18 USD).", file=sys.stderr)
        return 0

    base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not base_url or not api_key:
        print("set LLM_BASE_URL and LLM_API_KEY: the arm reaches the gateway "
              "through them and an unset key fails every write", file=sys.stderr)
        return 1

    # Staging is additive and the logs are written by name, so a second run into a
    # used directory resumes on top of old compile state, overwrites the previous
    # report and merges into its snapshots -- after the first run's spend is gone.
    if any(kb.glob("raw/**/*.md")) and not args.resume:
        print(f"{kb} already holds a staged KB. Point --out somewhere fresh, or "
              "pass --resume to continue this one (which reuses its compile "
              "state and overwrites its report).", file=sys.stderr)
        return 1

    kb.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "cases.json").write_text(json.dumps(cases, ensure_ascii=False,
                                                indent=1), encoding="utf-8")
    config = _arm_config(args, fixture, kb)
    report_path = logs / "arm-report.json"

    def checkpoint(report: dict) -> None:
        report_path.write_text(
            json.dumps({**report, "config": config}, ensure_ascii=False,
                       indent=2) + "\n", encoding="utf-8")

    probe = _endpoint_probe(base_url, api_key)
    hooks = Hooks(
        materialize=lambda stage, members: stage_fixture.materialize(
            fixture, kb, members),
        wait=lambda: wait_for_endpoint(probe, deadline_s=_WAIT_DEADLINE_S,
                                       interval_s=_WAIT_INTERVAL_S,
                                       sleep=time.sleep, clock=time.monotonic),
        compile=_compile_runner(Path(args.repo), kb, logs, args.workers),
        snapshot=_snapshotter(kb, logs),
        compile_state=_compile_state_reader(kb),
    )

    report = run_arm(staged, hooks, attempts=args.attempts, on_stage=checkpoint,
                     log=lambda message: print(message, file=sys.stderr))
    checkpoint(report)
    print(f"\narm done: {report['cost_usd']:.4f} USD over {report['calls']} calls, "
          f"residual {report['residual']}", file=sys.stderr)
    print(f"next: uv run python scripts/audit_articles.py --kb {kb} "
          f"--out {logs / 'audit.json'}", file=sys.stderr)
    return 1 if report["blocked_at_stage"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
