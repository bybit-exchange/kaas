from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

from kb_ai.commands.compile import compile_kb
from kb_ai.core.extract import (
    EXTRACT_STRATEGIES,
    STRATEGY_CHUNKED,
    validate_strategy,
)
from kb_ai.storage.store import KBStore

TEXT_SUFFIXES = {
    ".md", ".markdown", ".txt", ".rst", ".org",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".c", ".h", ".cpp", ".hpp", ".rb", ".php", ".sh",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".json",
    ".html", ".css", ".sql",
}

IGNORE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
    ".idea", ".vscode", ".kaas", ".next", "target",
}


@dataclass
class IngestReport:
    ingested: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _iter_files(path: Path):
    if path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file() and not any(part in IGNORE_DIRS for part in p.relative_to(path).parts):
                yield p
    elif path.is_file():
        yield path


def _raw_rel(root: Path, file: Path) -> str:
    # Flatten the file's path (relative to root, or just its name for a
    # single file) into a collision-resistant raw/*.md filename.
    try:
        rel = file.relative_to(root)
    except ValueError:
        rel = Path(file.name)
    flat = "__".join(rel.parts)
    # The suffix is appended rather than replaced: KBStore only scans raw/*.md,
    # so a .go or .yaml source needs it, and keeping the original extension in
    # the name is how the source's type stays visible. A source that is already
    # ".md" keeps its single suffix.
    #
    # Deliberately case-sensitive, though ingest_paths() accepts an uppercase
    # ".MD": the raw scan globs "*.md", which pathlib matches case-sensitively on
    # POSIX, so leaving "NOTE.MD" alone would ingest a file that never compiles.
    # Appending gives "NOTE.MD.md", which is ugly and correct.
    suffix = "" if flat.endswith(".md") else ".md"
    return f"raw/{root.name}__{flat}{suffix}"


def ingest_paths(paths: list[str], kb_dir: str) -> IngestReport:
    store = KBStore(kb_dir)
    report = IngestReport()
    for raw_path in paths:
        root = Path(raw_path).expanduser().resolve()
        for file in _iter_files(root):
            if file.suffix.lower() not in TEXT_SUFFIXES:
                report.skipped.append(str(file))
                continue
            try:
                content = file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                report.skipped.append(str(file))
                continue
            rel = _raw_rel(root if root.is_dir() else root.parent, file)
            store.write_raw(rel, f"<!-- source: {file} -->\n\n{content}")
            report.ingested.append(rel)
    return report


def run_distill(argv: list[str]) -> None:
    from kb_ai.__main__ import respond

    parser = argparse.ArgumentParser(prog="kb-ai distill")
    parser.add_argument("paths", nargs="+", help="files or directories to distill")
    parser.add_argument("--kb", default="./.kaas", help="knowledge-base directory (default: ./.kaas)")
    parser.add_argument(
        "--categories",
        help="comma-separated article categories, frozen into the KB on first use "
             "(default: the KB's frozen set, or the built-in defaults for a new KB)",
    )
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="run the extraction phase and stop, leaving wiki/ untouched — for "
             "reading the new extraction/ files after editing an extract prompt "
             "before paying for the write phase",
    )
    parser.add_argument(
        # type= as well as choices=: argparse does not validate a default against
        # choices, so LLM_EXTRACT_STRATEGY=Chunked would otherwise slip past the
        # flag's own check and surface as an INTERNAL_ERROR from __main__ instead
        # of the message the other two entry points give.
        "--extract-strategy", choices=list(EXTRACT_STRATEGIES),
        type=validate_strategy,
        default=os.environ.get("LLM_EXTRACT_STRATEGY") or STRATEGY_CHUNKED,
        dest="extract_strategy",
        help="how extraction reads a document: 'chunked' (default) extracts from "
             "the text itself, 'summarize' extracts from per-chunk summaries, "
             "'auto' summarizes once a document splits into three or more chunks. "
             "Must match the deployment's llm.extract_strategy: the freshness gate "
             "compares it, so a mismatch re-extracts every document once",
    )
    args = parser.parse_args(argv)

    # Omitting the flag must stay None rather than becoming the defaults, so an
    # existing KB keeps the set it was created with.
    categories = None
    if args.categories is not None:
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]
        if not categories:
            respond(False, error={
                "code": "EMPTY_CATEGORIES",
                "message": "--categories was given but lists no category names",
            })
            return

    # A path that does not exist yields no files rather than an error, so without
    # this check a run whose paths were mostly mistyped -- or relative to the
    # wrong directory, which `uv --directory py` makes easy -- reports ok=true
    # for whatever did resolve and quietly distills the wrong corpus.
    missing = [p for p in args.paths if not Path(p).expanduser().exists()]
    if missing:
        respond(False, error={
            "code": "PATH_NOT_FOUND",
            "message": f"{len(missing)} of {len(args.paths)} paths do not exist",
            "paths": missing,
        })
        return

    report = ingest_paths(args.paths, args.kb)
    if not report.ingested:
        respond(False, error={
            "code": "NO_READABLE_FILES",
            "message": "no readable text files found to distill",
            "skipped": report.skipped,
        })
        return

    model = os.environ.get("LLM_MODEL") or "gpt-4o-mini"
    result = compile_kb(args.kb, extract_model=model, compile_model=model,
                        write_model=model, categories=categories,
                        extract_only=args.extract_only,
                        extract_strategy=args.extract_strategy,
                        summarize_model=(os.environ.get("LLM_SUMMARIZE_MODEL")
                                         or model))
    respond(True, data={
        "kb": args.kb,
        "ingested": len(report.ingested),
        "skipped": report.skipped,
        "compile": result,
        "next": f"Register MCP: KAAS_KB_DIR={args.kb} kb-ai mcp",
    })
