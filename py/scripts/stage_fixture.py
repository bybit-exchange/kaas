"""Build the supersession fixture one stage per version (spec FX1, FX2).

Compiling all 38 fixture documents in one run routes every version chain into a
single ``merge→create`` call, which composes an article from scratch and is the one
write path better ordering information was always going to fix. The merge paths --
the ones that run against existing article text through prompts whose only actions
are ``append_to_section`` and ``new_section`` -- were never exercised, so a score
taken that way measures the easy path and reports it as a general result.

Staging fixes that. Stage 1 holds every chain's earliest version, stage 2 adds the
next one *into the KB stage 1 wrote*, and so on, so from stage 2 onward every write
is a merge into an article an earlier version already composed. P4's four-version
chain merges three times.

This script materialises the stages and prints the compiles to run. It deliberately
does not run them: a full pass over the fixture costs about 10 USD (2.09 extract +
3.22 classify + 4.73 write, measured on this corpus), and every arm -- the pre-A1
baseline, the post-A1 run, FX6's second arm -- pays it again. Spending is the
operator's call, so the plan is printed and the commands are theirs to run.

The pre-A1 baseline (FX4) needs the code as it stood before A1, which is no longer
what is checked out. Run that arm from a worktree::

    git worktree add /tmp/kaas-pre-a1 bd8252e
    uv run python scripts/stage_fixture.py --kb ../data/kb-supersession-fixture \\
        --cases cases.json --out /tmp/kaas-baseline

Usage::

    uv run python scripts/stage_fixture.py --kb ../data/kb-supersession-fixture \\
        --cases cases.json --out ../data/kb-supersession-staged --stage 1
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_CONFIG_NAME = "kaas.json"


def stages(cases: list[dict]) -> list[list[str]]:
    """Stage N is every chain's Nth version, in path order, each document once.

    A document can be the later version of one chain and the earlier version of
    another -- shape A and shape B overlap in this corpus -- so the same path can
    appear at two depths. It is staged at the shallowest, because ingesting it twice
    in one KB is not a thing the pipeline does and the second copy would compile
    against an article the first already wrote.
    """
    depth: dict[str, int] = {}
    for case in cases:
        for index, rel in enumerate(case["chain"]):
            if rel not in depth or index < depth[rel]:
                depth[rel] = index
    if not depth:
        return []
    out: list[list[str]] = [[] for _ in range(max(depth.values()) + 1)]
    for rel, index in depth.items():
        out[index].append(rel)
    return [sorted(members) for members in out]


def materialize(source_kb: Path, work_kb: Path, members: list[str]) -> list[str]:
    """Copy one stage's documents and their extractions into the working KB.

    Additive on purpose: what earlier stages wrote under ``wiki/`` is what this
    stage's merges run against, and the compile state they left is what keeps those
    documents from being recompiled.

    A document with no stored extraction is copied anyway and costs an extract call.
    14 corpus documents are in that position, and dropping them would change which
    documents a chain's article was composed from -- which is the thing being
    measured.
    """
    copied = []
    for rel in members:
        src = source_kb / rel
        if not src.exists():
            raise FileNotFoundError(f"{rel} is not in {source_kb}")
        dst = work_kb / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        copied.append(rel)

        extraction = source_kb / "extraction" / Path(rel).relative_to("raw")
        if extraction.exists():
            target = work_kb / "extraction" / Path(rel).relative_to("raw")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(extraction, target)

    config = source_kb / _CONFIG_NAME
    if config.exists() and not (work_kb / _CONFIG_NAME).exists():
        shutil.copyfile(config, work_kb / _CONFIG_NAME)
    return copied


def plan(staged: list[list[str]], work_kb: Path) -> list[str]:
    """One line per stage: what it adds and the compile that consumes it."""
    return [f"stage {i + 1}: +{len(members)} document(s) → "
            f"kb-ai compile --kb {work_kb}"
            for i, members in enumerate(staged)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--kb", required=True, help="the KB holding every version")
    parser.add_argument("--cases", required=True,
                        help="JSON from select_cases.py")
    parser.add_argument("--out", required=True, help="the staged KB to build")
    parser.add_argument("--stage", type=int,
                        help="materialise this stage (1-based); omit to only plan")
    args = parser.parse_args(argv)

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    staged = stages(cases)
    work = Path(args.out)

    for line in plan(staged, work):
        print(line)

    if args.stage is None:
        print(f"\n{len(staged)} stages planned, nothing written. "
              "Re-run with --stage 1 to materialise the first.", file=sys.stderr)
        return 0
    if not 1 <= args.stage <= len(staged):
        print(f"stage {args.stage} is outside 1..{len(staged)}", file=sys.stderr)
        return 1

    members = staged[args.stage - 1]
    work.mkdir(parents=True, exist_ok=True)
    copied = materialize(Path(args.kb), work, members)
    print(f"\nstage {args.stage}: {len(copied)} document(s) into {work}",
          file=sys.stderr)
    print(f"next: kb-ai compile --kb {work}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
