"""kb-ai derive -- build a topic-scoped knowledge base (spec F1-F6).

Holds every CLI concern the core deliberately does not know about: argparse, the
volume gate's TTY prompt, and the bridge-protocol response. The gate is passed
into derive_kb as the `approve` callback.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Callable

from kb_ai._errors import KBError
from kb_ai.derive import DeriveReport, derive_kb

_DEFAULT_MODEL = "claude-sonnet-4-6"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb-ai derive")
    parser.add_argument("topic", help="topic to scope the derived knowledge base to")
    parser.add_argument("--kb", default="./.kaas",
                        help="source knowledge-base directory (default: ./.kaas)")
    parser.add_argument("--slug", default=None,
                        help="directory name under derived/ (default: from the topic)")
    parser.add_argument("--force", action="store_true",
                        help="replace an existing derived/<slug>/ from a previous run")
    parser.add_argument("--model", default=None,
                        help="model for the topic filter and the derived compile")
    parser.add_argument("--yes", action="store_true",
                        help="skip the volume gate and compile without confirming")
    return parser


def _make_approve(args: argparse.Namespace) -> Callable[[DeriveReport], bool] | None:
    """The volume gate (F5), or None to auto-approve when --yes was given.

    Reports articles matched, documents resolved and total bytes -- deliberately
    no cost figure: there is no pre-compile estimator in this repository, and a
    guessed one would be worse than none.
    """
    if args.yes:
        return None

    def approve(report: DeriveReport) -> bool:
        total_bytes = sum(d.size_bytes for d in report.documents)
        print(f"[derive] topic: {report.topic}", file=sys.stderr)
        print(f"[derive] {len(report.selected_articles)} articles matched, "
              f"{len(report.documents)} documents resolved, "
              f"{total_bytes:,} bytes to compile", file=sys.stderr)
        if not sys.stdin.isatty():
            print("[derive] no TTY to confirm on and --yes not given; stopping "
                  "before the compile. Re-run with --yes --force to proceed.",
                  file=sys.stderr)
            return False
        answer = input("Compile the derived knowledge base? [y/N] ").strip().lower()
        return answer in ("y", "yes")

    return approve


def run_derive(argv: list[str]) -> None:
    from kb_ai.__main__ import respond

    args = build_parser().parse_args(argv)
    model = args.model or os.environ.get("LLM_MODEL") or _DEFAULT_MODEL

    try:
        report = derive_kb(
            args.kb, args.topic,
            slug=args.slug, force=args.force, model=model,
            approve=_make_approve(args),
        )
    except KBError as e:
        respond(False, error={"code": e.code, "message": str(e)})
        return

    if report.compiled:
        next_step = f"Register MCP: KAAS_KB_DIR={report.derived_kb} kb-ai mcp"
    else:
        next_step = (f"Declined before compiling. Re-run with --force --yes to "
                     f"compile {report.derived_kb} without re-resolving documents.")

    respond(True, data={
        "derived_kb": report.derived_kb,
        "slug": report.slug,
        "topic": report.topic,
        "selected": len(report.selected_articles),
        "skipped": [{"ref": s.ref, "reason": s.reason}
                    for s in report.skipped_articles + report.skipped_documents],
        "documents": len(report.documents),
        "bytes": sum(d.size_bytes for d in report.documents),
        "offtopic": len(report.offtopic_articles),
        "filter_batches": report.filter_batches,
        "dropped_invented_paths": report.dropped_invented_paths,
        "compiled": report.compiled,
        "compile": report.compile,
        "cost": report.cost,
        "warnings": report.warnings,
        "next": next_step,
    })
