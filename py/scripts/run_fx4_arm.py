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
- **One retry per stage, taken in place.** Staging the next version first would
  compile a leftover document against an article the next version had already
  moved, which scores the wrong thing silently.
- **Record the residual and carry on.** Stage 2 finished 16 of its 18 documents
  and the arm is still the measurement; a driver that aborted there would have
  spent 8 USD for nothing.

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
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import stage_fixture  # noqa: E402
from select_cases import select_cases  # noqa: E402

from kb_ai.storage.store import KBStore  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_FIXTURE = _REPO / "data" / "kb-supersession-fixture"
# The directory that ate the baseline arm. Named literally rather than via
# tempfile.gettempdir(), which on macOS points at the per-user folder pytest's
# own tmp_path lives under.
_VOLATILE = ("/tmp", "/private/tmp")
_WAIT_DEADLINE_S = 900.0
_WAIT_INTERVAL_S = 15.0
_ATTEMPTS_PER_STAGE = 2


def rebuild_cases(fixture_kb: Path) -> list[dict]:
    """The 18 curated chains, derived from the fixture instead of stored."""
    return select_cases(KBStore(str(fixture_kb)))


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
    on_disk = {p.relative_to(fixture_kb).as_posix()
               for p in (fixture_kb / "raw").rglob("*.md")
               if p.is_file() and not p.name.startswith(".")}

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


def stage_needs_retry(response: dict, *, compiled_so_far: int,
                      staged: int) -> bool:
    """Whether this stage has unfinished work after the attempt just made.

    Progress is cumulative across the stage's attempts: a retry only compiles what
    is left, so its own ``compiled`` is small by construction and reading it alone
    would retry a stage that had just finished.
    """
    if not response.get("ok"):
        return True
    data = response.get("data") or {}
    if data.get("errors"):
        return True
    return compiled_so_far < staged


@dataclass
class Hooks:
    """The four side effects, injected so the policy above can be tested."""
    materialize: Callable[[int, list[str]], None]
    wait: Callable[[], bool]
    compile: Callable[[int, int], dict]
    snapshot: Callable[[int], None]


def run_arm(staged: list[list[str]], hooks: Hooks,
            log: Callable[[str], None] = print) -> dict:
    """Every stage in order, retried in place, with the spend counted."""
    report: dict = {"stages": [], "cost_usd": 0.0, "calls": 0, "residual": [],
                    "blocked_at_stage": None}

    for stage, members in enumerate(staged, 1):
        hooks.materialize(stage, members)
        record = {"stage": stage, "staged": len(members), "compiled": 0,
                  "attempts": 0, "failures": []}
        report["stages"].append(record)
        log(f"stage {stage}: {len(members)} document(s) staged")

        for attempt in range(1, _ATTEMPTS_PER_STAGE + 1):
            if not hooks.wait():
                report["blocked_at_stage"] = stage
                log(f"stage {stage}: endpoint never came back, arm stopped "
                    f"after {report['cost_usd']:.4f} USD")
                return report

            response = hooks.compile(stage, attempt)
            record["attempts"] = attempt
            data = response.get("data") or {}
            cost = data.get("cost") or {}
            report["cost_usd"] += float(cost.get("total_cost_usd") or 0.0)
            report["calls"] += int(cost.get("calls") or 0)
            record["compiled"] += int(data.get("compiled") or 0)
            if not response.get("ok"):
                code = (response.get("error") or {}).get("code") or "UNKNOWN"
                record["failures"].append(code)
            log(f"stage {stage} attempt {attempt}: "
                f"{record['compiled']}/{len(members)} compiled, "
                f"{report['cost_usd']:.4f} USD so far")

            if not stage_needs_retry(response, compiled_so_far=record["compiled"],
                                     staged=len(members)):
                break

        hooks.snapshot(stage)
        if record["compiled"] < record["staged"] or record["failures"]:
            report["residual"].append({"stage": stage, "staged": record["staged"],
                                       "compiled": record["compiled"]})
    return report


# ── the real side effects ──────────────────────────────────────────────

def _endpoint_probe(base_url: str, api_key: str) -> Callable[[], bool]:
    """A gateway that answers anything at all is up.

    An HTTP error is an answer -- 401 from a key the arm will not use still proves
    the endpoint is serving -- so only a transport failure counts as down.
    """
    request = urllib.request.Request(base_url.rstrip("/") + "/models",
                                     headers={"Authorization": f"Bearer {api_key}"})

    def probe() -> bool:
        try:
            with urllib.request.urlopen(request, timeout=20):
                return True
        except urllib.error.HTTPError:
            return True
    return probe


def _compile_runner(repo: Path, kb: Path, logs: Path,
                    workers: int) -> Callable[[int, int], dict]:
    """Run the compile out of process, against whichever checkout ``repo`` is.

    Out of process because the baseline arm is the pre-A1 code in a worktree, and
    the point of an arm is which code wrote the articles.
    """
    body = json.dumps({"data_dir": str(kb), "workers": workers})

    def compile_stage(stage: int, attempt: int) -> dict:
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


def _plan_lines(staged: list[list[str]], kb: Path, repo: Path) -> list[str]:
    return [f"stage {i}: +{len(members)} document(s) → "
            f"(cd {repo / 'py'} && echo '{{\"data_dir\": \"{kb}\"}}' | "
            f"uv run python -m kb_ai compile)"
            for i, members in enumerate(staged, 1)]


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
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--execute", action="store_true",
                        help="run the compiles; this is what spends ~18 USD")
    args = parser.parse_args(argv)

    out = Path(args.out).expanduser()
    if any(str(out) == v or str(out).startswith(v + "/") for v in _VOLATILE):
        parser.error(f"--out may not be under {' or '.join(_VOLATILE)}: clearing "
                     "it is what destroyed the baseline arm")

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
    for line in _plan_lines(staged, kb, Path(args.repo)):
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

    kb.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "cases.json").write_text(json.dumps(cases, ensure_ascii=False,
                                                indent=1), encoding="utf-8")
    probe = _endpoint_probe(base_url, api_key)
    hooks = Hooks(
        materialize=lambda stage, members: stage_fixture.materialize(
            fixture, kb, members),
        wait=lambda: wait_for_endpoint(probe, deadline_s=_WAIT_DEADLINE_S,
                                       interval_s=_WAIT_INTERVAL_S,
                                       sleep=time.sleep, clock=time.monotonic),
        compile=_compile_runner(Path(args.repo), kb, logs, args.workers),
        snapshot=_snapshotter(kb, logs),
    )

    report = run_arm(staged, hooks, log=lambda message: print(message,
                                                             file=sys.stderr))
    (logs / "arm-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\narm done: {report['cost_usd']:.4f} USD over {report['calls']} calls, "
          f"residual {report['residual']}", file=sys.stderr)
    print(f"next: uv run python scripts/audit_articles.py --kb {kb} "
          f"--out {logs / 'audit.json'}", file=sys.stderr)
    return 1 if report["blocked_at_stage"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
