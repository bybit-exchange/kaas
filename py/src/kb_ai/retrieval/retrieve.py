"""LLM-iterative retrieval over the compiled markdown wiki.

First-version retrieval with NO embeddings / vector DB. The LLM navigates the
``master-index`` catalog (title + summary per article) and picks the most
relevant article paths, which are then read in full to ground a chat answer.
Single pass:

  1. Parse ``index/master-index.md`` -> catalog of (title, path, summary).
  2. LLM-select: given the catalog + question, the model picks the most
     relevant article paths (most relevant first).
  3. Read each selected page in full (frontmatter stripped, truncated).

Returns ``[{"title", "path", "content"}]`` consumable as the ``/chat``
``articles`` field, which the existing chat context assembler already handles.

Scope note: the catalog line is the only navigation surface. It carries the
prose summary plus, for articles built around a reference table, the key names
that table defines (see storage.index._derive_keys) -- so a question naming one
setting can reach the article defining it. An article relevant only via prose
terms deep in its body is still out of reach; body-depth recall is deferred to a
future version (vector search).
"""
from __future__ import annotations

import sys

from kb_ai.llm import completion_json
from kb_ai.storage.store import KEYS_MARKER, ArticleMeta, KBStore

# Cap per article so the combined context stays within the LLM prompt budget.
# Coordinated with the default max_articles (6) and llm.MAX_PROMPT_CHARS (80K):
# 6 * 12K = 72K leaves headroom for the system prompt + history.
MAX_ARTICLE_CHARS = 12_000

# Replaces the dropped tail so the model reads the excerpt as partial. Without
# it, a cut article is indistinguishable from a complete one and the answer
# reports a detail as missing when it was only cut off.
TRUNCATION_NOTE = ("\n\n[This article exceeds the retrieval budget and is cut off here. "
                   "A detail missing from this excerpt does not mean the article lacks it.]")


def _select_relevant(catalog: list[ArticleMeta], query: str, model: str,
                     *, max_select: int) -> list[str]:
    """Ask the LLM which catalog articles are most relevant to the query.

    Returns a ranked list of paths, filtered to those actually present in the
    catalog (the model occasionally invents paths). Empty catalog -> [].
    Degrades to [] on any LLM error so chat still answers (without context).
    """
    if not catalog:
        return []
    valid = {a.path for a in catalog}
    listing = "\n".join(
        f"- {a.path} — {a.title}: {a.summary}" + (f"{KEYS_MARKER}{a.keys}" if a.keys else "")
        for a in catalog)
    prompt = (
        "You are selecting which knowledge-base articles can help answer a "
        "question. Below is the article catalog (path — title: summary). An "
        "article that documents a table of settings, fields or endpoints also "
        "lists their names after `| keys:`, so a question about one specific "
        "named value belongs to the article whose keys contain it.\n\n"
        f"{listing}\n\n"
        f"Question: {query}\n\n"
        f"Return JSON {{\"paths\": [...]}} listing up to {max_select} article "
        "paths (verbatim from the catalog) most relevant to the question, most "
        "relevant first. Return an empty list if none are relevant."
    )
    try:
        result = completion_json(model=model, messages=[{"role": "user", "content": prompt}])
    except Exception as e:  # noqa: BLE001 — retrieval must degrade gracefully
        print(f"[retrieve] select_relevant failed: {e}", file=sys.stderr)
        return []
    paths = result.get("paths") if isinstance(result, dict) else None
    if not isinstance(paths, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for p in paths:
        if isinstance(p, str) and p in valid and p not in seen:
            seen.add(p)
            out.append(p)
        if len(out) >= max_select:
            break
    return out


def _strip_frontmatter(content: str) -> str:
    """Drop a leading YAML frontmatter block (``---\\n...\\n---``)."""
    if not content.startswith("---"):
        return content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return content
    return parts[2].lstrip("\n")


def _fit_to_budget(path: str, body: str) -> str:
    """Cap one article at the per-article budget, saying so when it has to cut.

    The note costs part of the budget rather than being added on top of it, so the
    coordination with MAX_PROMPT_CHARS documented above still holds.
    """
    if len(body) <= MAX_ARTICLE_CHARS:
        return body
    kept = MAX_ARTICLE_CHARS - len(TRUNCATION_NOTE)
    print(f"[retrieve] {path} truncated: kept {kept:,} of {len(body):,} chars "
          f"({len(body) - kept:,} dropped)", file=sys.stderr, flush=True)
    return body[:kept] + TRUNCATION_NOTE


def _read_selected(store: KBStore, meta_by_path: dict, paths: list[str]) -> list[dict]:
    """Read the given article paths in full (frontmatter stripped, truncated).

    Returns ``[{title, path, content}]``; skips non-string, unreadable, and
    out-of-KB paths. paths comes from the client-supplied MCP `ask` argument, so
    one bad entry must not discard the articles that did resolve -- and the
    caller learns nothing about what lies outside the KB.
    """
    articles: list[dict] = []
    for path in paths:
        if not isinstance(path, str):
            continue
        try:
            raw = store.read_article(path)
        except OSError:
            continue
        except ValueError as e:
            print(f"[retrieve] skipping path: {e}", file=sys.stderr, flush=True)
            continue
        meta = meta_by_path.get(path)
        title = meta.title if meta else path.rsplit("/", 1)[-1].removesuffix(".md")
        articles.append({"title": title, "path": path,
                         "content": _fit_to_budget(path, _strip_frontmatter(raw))})
    return articles


def read_articles(paths: list[str], kb_dir: str) -> list[dict]:
    """Read explicit wiki article paths in full — the explicit-``paths`` chat path.

    No embeddings / vector chunking: the selected pages are read verbatim and
    grounded as full-article context. Returns ``[{title, path, content}]``.
    """
    store = KBStore(kb_dir, read_only=True)
    meta_by_path = {a.path: a for a in store.existing_articles()}
    return _read_selected(store, meta_by_path, paths)


def iterative_retrieve(query: str, kb_dir: str, *, model: str,
                       max_articles: int = 6) -> list[dict]:
    """Retrieve relevant wiki articles for a query via LLM index navigation.

    See module docstring for the pipeline. Returns ``[{title, path, content}]``,
    empty when there is no master-index or nothing relevant is found.
    """
    store = KBStore(kb_dir, read_only=True)
    catalog = store.existing_articles()
    if not catalog:
        return []
    meta_by_path = {a.path: a for a in catalog}

    selected = _select_relevant(catalog, query, model, max_select=max_articles)
    return _read_selected(store, meta_by_path, selected)
