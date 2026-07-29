from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

from kb_ai.commands.compile import compile_kb
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
    return f"raw/{root.name}__{flat}.md"


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
    args = parser.parse_args(argv)

    report = ingest_paths(args.paths, args.kb)
    if not report.ingested:
        respond(False, error={
            "code": "NO_READABLE_FILES",
            "message": "no readable text files found to distill",
            "skipped": report.skipped,
        })
        return

    model = os.environ.get("LLM_MODEL") or "gpt-4o-mini"
    result = compile_kb(args.kb, extract_model=model, compile_model=model, write_model=model)
    respond(True, data={
        "kb": args.kb,
        "ingested": len(report.ingested),
        "skipped": report.skipped,
        "compile": result,
        "next": f"Register MCP: KAAS_KB_DIR={args.kb} kb-ai mcp",
    })
