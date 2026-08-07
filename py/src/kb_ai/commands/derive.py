"""kb-ai derive -- build a topic-scoped knowledge base (spec F1-F6).

Holds every CLI concern the core deliberately does not know about: argparse, the
volume gate's TTY prompt, and the bridge-protocol response. The gate is passed
into derive_kb as the `approve` callback.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable

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
    parser.add_argument("--prune", action="store_true",
                        help="run the second topic filter over the derived catalog and "
                             "move articles it rejects into _offtopic/ (off by default: "
                             "see issue #24)")
    parser.add_argument("--select-from", choices=["articles", "documents"],
                        default="articles", dest="select_from",
                        help="which catalog to filter: 'articles' uses the compiled "
                             "catalog and follows each article's sources: (default); "
                             "'documents' filters raw/ directly, which also works on a "
                             "knowledge base that was never compiled")
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
        # Report whichever unit the filter actually selected: under
        # --select-from documents selected_articles is empty by design, and
        # "0 articles matched" would read as "nothing matched".
        if args.select_from == "documents":
            matched = f"{len(report.selected_documents)} documents matched"
        else:
            matched = f"{len(report.selected_articles)} articles matched"
        print(f"[derive] topic: {report.topic}", file=sys.stderr)
        print(f"[derive] {matched}, "
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
            slug=args.slug, force=args.force, prune=args.prune,
            select_from=args.select_from, model=model,
            approve=_make_approve(args),
        )
    except KBError as e:
        respond(False, error={"code": e.code, "message": str(e)})
        return

    if report.compiled:
        next_step = f"Register MCP: KAAS_KB_DIR={report.derived_kb} kb-ai mcp"
    else:
        # No resume path exists: --force calls create(), which deletes the
        # directory and starts over -- the topic filter runs again at full cost and
        # the documents are resolved and copied again. The source KB's extraction
        # layer is the one thing genuinely reused, and it was never lost.
        next_step = (f"Declined before compiling. Re-run with --force --yes to "
                     f"replace {report.derived_kb}: the topic filter runs again "
                     f"and the documents are re-copied, but the source knowledge "
                     f"base's extraction layer is reused.")

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
