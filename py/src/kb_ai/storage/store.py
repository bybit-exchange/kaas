from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


# Separates the catalog line's prose summary from the identifiers a reference
# article documents. Written by storage.index, read back by existing_articles().
KEYS_MARKER = " | keys: "


@dataclass
class ArticleMeta:
    title: str
    path: str
    summary: str = ""
    type: str = ""
    tags: list[str] = field(default_factory=list)
    status: str = ""
    keys: str = ""


def render_catalog_line(a: ArticleMeta) -> str:
    """Render one catalog line the way the master index writes it.

    Shared by retrieval's page selection and derive's topic filter: two copies of
    this f-string would drift, and a change to the keys column would silently
    stop reaching one of them.
    """
    return (f"- {a.path} — {a.title}: {a.summary}"
            + (f"{KEYS_MARKER}{a.keys}" if a.keys else ""))


@dataclass
class RawFile:
    rel_path: str
    content: str
    checksum: str


@dataclass
class RawFileMeta:
    rel_path: str
    checksum: str
    size_bytes: int  # UTF-8 encoded bytes after universal-newline translation


def _compute_checksum(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class KBStore:
    def __init__(self, base_dir: str, *, read_only: bool = False, cache_enabled: bool = True):
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.read_only = read_only
        self.cache_enabled = cache_enabled

    @property
    def wiki_dir(self) -> Path:
        return self.base_dir / "wiki"

    @property
    def raw_dir(self) -> Path:
        return self.base_dir / "raw"

    @property
    def index_dir(self) -> Path:
        return self.base_dir / "index"

    def _iter_raw_paths(self) -> Iterator[Path]:
        """Yield raw/*.md paths in sorted order, applying skip rules.

        Single source of truth for the file-scan contract shared by
        list_raw_files() and iter_raw_file_meta(). When extending skip
        rules (e.g. adding "_archive"), change here only.
        """
        for p in sorted(self.raw_dir.rglob("*.md")):
            if p.name.startswith("."):
                continue
            # raw/_skipped/ holds files moved out by cost-review approval and
            # must not re-enter compile/estimate. Mirrors the Go scanner guard
            # in kaas/internal/worker/scanner.go.
            if "_skipped" in p.relative_to(self.raw_dir).parts:
                continue
            yield p

    def list_raw_files(self) -> list[RawFile]:
        files = []
        for p in self._iter_raw_paths():
            content = p.read_text()
            rel = str(p.relative_to(self.base_dir))
            files.append(RawFile(rel_path=rel, content=content, checksum=_compute_checksum(content)))
        return files

    def iter_raw_file_meta(self) -> Iterator[RawFileMeta]:
        """Stream-scan raw/*.md, yielding (rel_path, checksum, size_bytes)
        without holding any file's content in memory.

        Checksum and size_bytes are byte-equivalent to:
            content = path.read_text()                       # text mode, universal newlines
            size_bytes = len(content.encode('utf-8'))
            checksum  = hashlib.sha256(content.encode()).hexdigest()[:16]

        Achieved by reading in text mode (so \\r\\n -> \\n matches read_text)
        and re-encoding each chunk as UTF-8 to feed both the hasher and the
        byte counter -- concatenation of UTF-8-encoded valid-Unicode chunks
        equals UTF-8 of the full string, byte-for-byte.

        Chunk size: 64K chars. UTF-8 worst case for BMP is ~3 bytes/char,
        so per-file peak transient memory is ~192KB -- well below the
        "max(single to_compile file)" memory target.
        """
        for p in self._iter_raw_paths():
            hasher = hashlib.sha256()
            size_bytes = 0
            with open(p, "r", encoding="utf-8", newline=None) as f:
                while True:
                    chunk = f.read(64 * 1024)  # 64K chars
                    if not chunk:
                        break
                    encoded = chunk.encode("utf-8")
                    hasher.update(encoded)
                    size_bytes += len(encoded)
            yield RawFileMeta(
                rel_path=str(p.relative_to(self.base_dir)),
                checksum=hasher.hexdigest()[:16],
                size_bytes=size_bytes,
            )

    def _resolve(self, rel_path: str) -> Path:
        """Resolve rel_path inside base_dir, rejecting anything that escapes it.

        rel_path reaches these methods from LLM output and from client-supplied
        MCP arguments (the `paths` argument of the ask tool), so "../" segments
        and absolute paths are attacker-influenced. pathlib replaces the whole
        path on an absolute operand, which makes the naive `base_dir / rel_path`
        an arbitrary-file read.

        By design this resolves symlinks, so a symlinked subtree pointing outside
        base_dir is rejected. That deliberately differs from the lexical
        containment check in the Go layer (internal/api/wiki.go safeJoin): a
        symlink planted under wiki/ is exactly the case worth rejecting here.
        base_dir itself is also rejected -- every caller addresses a file.
        """
        full = (self.base_dir / rel_path).resolve()
        if full == self.base_dir or not full.is_relative_to(self.base_dir):
            raise ValueError(f"path escapes kb_dir: {rel_path}")
        return full

    def read_raw(self, rel_path: str) -> str:
        """Read a raw/*.md file by rel_path (relative to base_dir).

        Used by the estimate path to lazily load file content after the
        streaming meta scan filters out cached/oversized files. Existence
        of this method (vs. inlining (base_dir / rel_path).read_text())
        is to give tests a stable monkeypatch point for read counting.
        """
        return self._resolve(rel_path).read_text()

    def read_article(self, rel_path: str) -> str:
        return self._resolve(rel_path).read_text()

    def write_article(self, rel_path: str, content: str) -> None:
        if self.read_only:
            raise PermissionError("KBStore is read-only")
        full = self._resolve(rel_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)

    def write_raw(self, rel_path: str, content: str) -> None:
        if self.read_only:
            raise PermissionError("KBStore is read-only")
        full = self._resolve(rel_path)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)

    def existing_articles(self) -> list[ArticleMeta]:
        index_path = self.index_dir / "master-index.md"
        if not index_path.exists():
            return []
        articles = []
        for line in index_path.read_text().splitlines():
            line = line.strip()
            if not line.startswith("- ["):
                continue
            try:
                # Find the "](" that separates title from path — handles titles with parentheses
                link_sep = line.index("](")
                title = line[3:link_sep]
                rest = line[link_sep + 2:]
                path_end = rest.index(")")
                path = rest[:path_end]
                # Split only what follows the link, and only on the first dash:
                # em dashes occur inside both titles and prose summaries.
                tail = rest[path_end + 1:]
                summary = tail.split("—", 1)[1].strip() if "—" in tail else ""
                # Split from the right: a summary taken from a table row carries
                # its own pipes, and the keys column is always last.
                head, marked, marked_keys = summary.rpartition(KEYS_MARKER)
                keys = ""
                if marked:
                    summary, keys = head.strip(), marked_keys.strip()
                articles.append(ArticleMeta(title=title, path=path,
                                            summary=summary, keys=keys))
            except (IndexError, ValueError):
                continue
        return articles

    def load_extract_cache(self, checksum: str) -> dict | None:
        if not self.cache_enabled:
            return None
        cache_path = self.base_dir / ".extract-cache" / f"{checksum}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())
        return None

    def save_extract_cache(self, checksum: str, data: dict) -> None:
        if not self.cache_enabled:
            return
        cache_dir = self.base_dir / ".extract-cache"
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / f"{checksum}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2)
        )

    def load_classify_cache(self, cache_key: str) -> dict | None:
        if not self.cache_enabled:
            return None
        cache_path = self.base_dir / ".classify-cache" / f"{cache_key}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text())
        return None

    def save_classify_cache(self, cache_key: str, data) -> None:
        if not self.cache_enabled:
            return
        # Support both raw dicts and typed objects with .to_dict()
        serializable = data.to_dict() if hasattr(data, "to_dict") else data
        cache_dir = self.base_dir / ".classify-cache"
        cache_dir.mkdir(exist_ok=True)
        (cache_dir / f"{cache_key}.json").write_text(
            json.dumps(serializable, ensure_ascii=False, indent=2)
        )

    def load_compile_state(self) -> dict:
        state_path = self.base_dir / ".compile-state.json"
        if state_path.exists():
            return json.loads(state_path.read_text())
        return {}

    def save_compile_state(self, state: dict) -> None:
        state_path = self.base_dir / ".compile-state.json"
        tmp_path = state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
        os.replace(str(tmp_path), str(state_path))
