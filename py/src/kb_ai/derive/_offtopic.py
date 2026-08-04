"""Second filter pass over the freshly compiled derived catalog (spec D2-D7).

A selected document can be broader than the topic, so its compiled articles can
be off-topic even though the document was on-topic. This pass re-filters the
derived catalog in PRECISION mode and moves what it does not select into
_offtopic/, outside wiki/ -- which is what takes it out of indexing and
retrieval, by the same mechanism that makes a nested derived KB invisible to its
parent.

Moved, never deleted (D2). The documents behind moved articles stay in the
derived raw/ (D7): they are what the articles were compiled from, and removing
them would make the derived KB's own re-compile lossy.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from kb_ai.derive._layout import OFFTOPIC_DIRNAME
from kb_ai.derive._types import MODE_PRECISION, Selector
from kb_ai.storage.index import update_markdown_index
from kb_ai.storage.store import KBStore

_WIKI_PREFIX = "wiki/"


def prune(derived_dir: Path, topic: str,
          select: Selector) -> tuple[list[str], list[str]]:
    """Move off-topic articles to _offtopic/ and reindex. Returns (moved, warnings).

    Two backstops keep a mis-tuned PRECISION prompt from emptying the wiki:
    an empty catalog and an empty selection both leave every article in place and
    return a warning instead (D6).
    """
    derived_dir = Path(derived_dir)
    store = KBStore(str(derived_dir))
    catalog = store.existing_articles()
    if not catalog:
        return [], ["second_pass_empty_catalog"]

    result = select(catalog, topic, MODE_PRECISION)
    keep = set(result.paths)
    if not keep:
        # An empty derived wiki is worse than an unfiltered one.
        return [], ["second_pass_selected_nothing"]

    moved: list[str] = []
    for article in catalog:
        if article.path in keep:
            continue
        # Catalog paths are written by update_markdown_index as base-relative
        # wiki/... paths; anything else is not ours to move.
        if not article.path.startswith(_WIKI_PREFIX):
            continue
        src = derived_dir / article.path
        if not src.is_file():
            continue
        dest = derived_dir / OFFTOPIC_DIRNAME / article.path[len(_WIKI_PREFIX):]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        moved.append(article.path)

    if moved:
        update_markdown_index(store)
    return moved, []
