"""Page-cache eviction helpers for Linux deployments.

On Linux, advises the kernel to drop cached pages after reading a file
(POSIX_FADVISE with FADV_DONTNEED). This prevents unbounded page-cache
growth in long-running Kubernetes pods that continuously ingest files.

No-op on platforms lacking os.posix_fadvise (macOS, Windows).

``max_bytes`` in :func:`read_head_and_evict` is a *byte budget*; the
returned string is decoded with ``errors='replace'`` because the callers
only need ASCII structural markers (e.g. YAML frontmatter delimiters).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO

_HAS_FADVISE = hasattr(os, "posix_fadvise")

# POSIX_FADV_DONTNEED == 4 on Linux; only referenced when _HAS_FADVISE is True.
_FADV_DONTNEED = 4

_CHUNK_SIZE = 65536  # 64 KB


def read_text_and_evict(path: str | Path) -> str:
    """Read entire file as UTF-8 text, then advise kernel to evict pages.

    Uses low-level os.open/os.read/os.close for fd-level control so that
    posix_fadvise can be issued before the fd is closed.

    Returns the full file content as a string.
    """
    fd = os.open(str(path), os.O_RDONLY)
    try:
        chunks: list[bytes] = []
        while chunk := os.read(fd, _CHUNK_SIZE):
            chunks.append(chunk)
        if _HAS_FADVISE:
            os.posix_fadvise(fd, 0, 0, _FADV_DONTNEED)
    finally:
        os.close(fd)
    # Normalize newlines (\r\n and \r to \n) to match Python text-mode read.
    text = b"".join(chunks).decode("utf-8")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_head_and_evict(path: str | Path, max_bytes: int) -> str:
    """Read up to *max_bytes* raw bytes from *path*, then evict pages.

    *max_bytes* is a byte budget — the actual read may be shorter if the
    file is smaller. The raw bytes are decoded with ``errors='replace'``
    because structural markers (YAML frontmatter delimiters) are ASCII.

    Returns the decoded string (possibly truncated mid-character, replaced
    with U+FFFD).
    """
    fd = os.open(str(path), os.O_RDONLY)
    try:
        data = os.read(fd, max_bytes)
        if _HAS_FADVISE:
            os.posix_fadvise(fd, 0, 0, _FADV_DONTNEED)
    finally:
        os.close(fd)
    return data.decode("utf-8", errors="replace")


def evict_after_open_read(f: IO[bytes] | IO[str]) -> None:
    """Advise kernel to evict cached pages for an already-open file object.

    Call this after finishing reads on *f* but before closing it. The fd
    must still be valid (not yet closed).

    No-op on platforms without os.posix_fadvise. Silently ignores errors
    (e.g. if the fd is a pipe or socket).
    """
    if not _HAS_FADVISE:
        return
    try:
        os.posix_fadvise(f.fileno(), 0, 0, _FADV_DONTNEED)
    except (OSError, AttributeError):
        pass
