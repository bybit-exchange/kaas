"""Split a leading YAML frontmatter block from a markdown body.

The delimiter is a line that is exactly ``---``. Every reader in this package
used to do ``content.split("---", 2)`` instead, which splits on the first three
dashes *anywhere*: a frontmatter value containing ``---`` -- a raw filename like
``meeting---part-2.md``, or a horizontal rule in a summary -- was cut in half,
silently losing the rest of that value, every key after it, and leaking the
remains into the body.
"""
from __future__ import annotations

_DELIM = "---"


def split_frontmatter(content: str) -> tuple[str, str] | None:
    """Return (frontmatter_text, body), or None when there is no complete block.

    None covers both shapes the callers treat as "no frontmatter": content that
    does not open with a delimiter line, and a block that is never closed.
    """
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIM:
        return None
    for i in range(1, len(lines)):
        if lines[i].strip() == _DELIM:
            return "".join(lines[1:i]), "".join(lines[i + 1:])
    return None
