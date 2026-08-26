"""kb-ai check -- run the read-only checks over a knowledge base (F3, F5, #42).

The checks themselves live as pure functions elsewhere -- F3 and F5 in
derive/_status.py, which is what F5 asks for, and the grounding check in
core/grounding.py. This is the surface that makes them runnable: without it they
are reachable only from the test suite and from a python -c, and a check nobody
can run is a check that rots.

One command covers both kinds of knowledge base rather than two. F3 applies to
any KB, parent or derived, and F5 already degrades to "unknown" with a reason
when there is no derive manifest to read -- so a parent KB gets an honest
"not derived from anything" instead of a special case in the CLI.

It also reports the wiki lag (G5), which compile can only report on a run that
had other work to do. That is exactly the wrong time for the write-phase gate:
editing merge-rewrite.md changes no document and no extraction, so the next
compile finds nothing to do and returns before any report. Here it costs nothing
and is available whenever an operator asks.

The grounding check is here for the same reason and one more: the fabrication it
looks for (#42) is already on disk in knowledge bases compiled before the
grounding constraint existed, and a check that only ran during a write could not
revisit any of it.

One caveat worth knowing before reading its output. It needs each article's
extraction, and extraction files written before #41 record schema_version 1, which
parse() refuses -- so on a knowledge base that has not been re-extracted since,
every article lands in `skipped` and the check has seen nothing. The extraction
report above says "N match" for those same files, because F3 reads the
frontmatter only and never reaches the version gate. The two lines are consistent;
the summary here says "no articles could be checked" rather than counting zero
findings, so the pair cannot be read as a clean bill.

Spends nothing and rewrites nothing, so it is safe to point at a read-only KB or
at someone else's.

One more thing the output has to survive: scale. Pointed at a 1024-document
knowledge base this printed 482KB of JSON, of which 1024 rows were
`{"document": ..., "reason": "missing"}` -- the same reason every time, for a
condition check_extractions itself documents as not a fault. A diagnostic that
takes a screenful to say "nothing is wrong" does not get read, and the one thing
it did have to say (0 mismatched, and grounding able to check none of the 698
articles it found) was buried in it.

So every finding list is capped and reports the total it was cut from. The cap
is a display limit, never a measurement: `count` is the real number whatever
--limit does, and `truncated` says outright that rows were dropped. Truncating
into a bare list would be worse than not truncating -- twenty rows that look like
the whole set is a wrong answer, where twenty rows labelled "of 1024" is a short
one.

The cap is uniform across every list, which means the actionable ones
(`mismatched`, `unsourced`) are cut at the same twenty as the benign `missing`
that motivated it. That is the right default -- a KB with thousands of genuine
faults has a bigger problem than its report length -- but it is why --limit 0
exists.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kb_ai._protocol import respond_error, respond_ok
from kb_ai.core.grounding import check_grounding
from kb_ai.core.merge import write_prompt_version
from kb_ai.derive import check_extractions, check_parent
from kb_ai.derive._layout import MANIFEST_NAME
from kb_ai.prompts import PromptError
from kb_ai.storage import extraction as extraction_layer
from kb_ai.storage.lag import wiki_lag
from kb_ai.storage.store import KBStore


def _prompt_version(compute) -> str:
    """A prompt-set version, or "" when the prompt files cannot be read.

    A read-only report degrades rather than failing: F3 and F5 do not depend on
    any prompt, and refusing to run them over an unreadable prompt directory
    would withhold the answers that are still available. The empty string reaches
    wiki_lag as "cannot tell", which it reports as such instead of counting every
    document as behind.
    """
    try:
        return compute()
    except PromptError as e:
        print(f"[check] {e}", file=sys.stderr)
        return ""


DEFAULT_LIMIT = 20


def _capped(items: list, limit: int) -> dict:
    """Render one finding list as its total, a shown slice, and whether it was cut.

    limit 0 means no limit. A negative limit never reaches here -- the parser
    rejects it, because reading -1 as "unlimited" would hand back the whole
    payload to someone who was asking for less of it.

    The slice is copied rather than aliased: the caller's list is a check result,
    and handing a live reference to it into the response payload is a
    same-object coupling nobody would expect from a function named for cutting.
    """
    shown = items[:] if limit == 0 else items[:limit]
    return {"count": len(items), "items": shown,
            "truncated": len(shown) < len(items)}


def nonnegative_int(value: str) -> int:
    """argparse renders type.__name__ in its error text, so this name is
    operator-facing: `invalid _limit value: 'abc'` leaked a private helper."""
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError(
            f"--limit must not be negative (got {n}); use 0 for no limit")
    return n


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kb-ai check")
    parser.add_argument("--kb", default="./.kaas",
                        help="knowledge-base directory to check (default: ./.kaas)")
    parser.add_argument("--limit", type=nonnegative_int, default=DEFAULT_LIMIT,
                        help="how many items to show per finding list; the "
                             "reported count is always the full total "
                             f"(default: {DEFAULT_LIMIT}, 0 for no limit)")
    return parser


def run_check(argv: list[str]) -> None:
    args = build_parser().parse_args(argv)

    store = KBStore(args.kb, read_only=True)
    # Checked first: without it a mistyped --kb reports 0 match / 0 missing /
    # 0 mismatched and ok, which in the one command built for diagnosis is
    # indistinguishable from a healthy empty knowledge base.
    #
    # Either marker is enough. raw/ is what F3 reads, and a derive manifest alone
    # still identifies a knowledge base worth asking F5 about -- requiring raw/
    # would refuse a derived KB whose documents have not been copied yet.
    if not (store.raw_dir.is_dir() or (Path(args.kb).expanduser()
                                       / MANIFEST_NAME).is_file()):
        respond_error("NOT_A_KB",
                      f"{args.kb} has neither a raw/ directory nor a "
                      f"{MANIFEST_NAME}; check the --kb path")
        return

    extractions = check_extractions(args.kb)
    parent = check_parent(args.kb)
    grounding = check_grounding(args.kb)

    lag = wiki_lag(
        store.load_compile_state(),
        present={meta.rel_path for meta in store.iter_raw_file_meta()},
        extract_prompt_version=_prompt_version(
            extraction_layer.current_prompt_version),
        write_prompt_version=_prompt_version(write_prompt_version),
    )

    print(f"[check] extractions: {extractions.summary()}", file=sys.stderr)
    print(f"[check] parent: {parent.summary()}", file=sys.stderr)
    print(f"[check] wiki: {lag.summary()}", file=sys.stderr)
    print(f"[check] grounding: {grounding.summary()}", file=sys.stderr)

    # Every list below goes through capped(): the summaries above and the count
    # inside each wrapper carry the totals, so shrinking the payload cannot shrink
    # the answer.
    def cap(items: list) -> dict:
        return _capped(items, args.limit)

    respond_ok(data={
        "kb": args.kb,
        "limit": args.limit,
        "extractions": {
            "matches": cap(extractions.matches),
            # Reasons are carried per document rather than summarised: "missing"
            # and "invalid: counts disagree with body" call for different actions.
            "missing": cap([{"document": rel, "reason": why}
                            for rel, why in extractions.missing]),
            "mismatched": cap([{"document": rel, "reason": why}
                               for rel, why in extractions.mismatched]),
            "summary": extractions.summary(),
        },
        "parent": {
            "source_kb": parent.source_kb,
            "verdict": parent.verdict,
            "in_sync": cap(parent.in_sync),
            "changed_in_parent": cap(parent.changed_in_parent),
            "gone_from_parent": cap(parent.gone_from_parent),
            "reason": parent.reason,
            "summary": parent.summary(),
        },
        # Named rather than counted: the count is what compile already reports,
        # and what an operator needs here is which articles to re-read.
        "wiki": {
            "behind_extract_prompt": cap(lag.behind_extract),
            "behind_write_prompt": cap(lag.behind_write),
            "extract_first_run": lag.extract_first_run,
            "write_first_run": lag.write_first_run,
            "summary": lag.summary(),
        },
        # Each finding carries the line it sits on, not just the name: the
        # operator's next move is deciding whether the article really claims the
        # thing, and a bare name sends them opening files to find out.
        "grounding": {
            "checked": cap(grounding.checked),
            "unsourced": cap([{"article": f.article, "name": f.name,
                               "line": f.line} for f in grounding.unsourced]),
            # An article that could not be checked is neither clean nor flagged.
            # Its reason usually points at the extraction layer, which is the
            # check above.
            "skipped": cap([{"article": rel, "reason": why}
                            for rel, why in grounding.skipped]),
            "summary": grounding.summary(),
        },
    })
