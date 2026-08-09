from __future__ import annotations

import re
import sys
from datetime import datetime

import yaml

from kb_ai._frontmatter import split_frontmatter
from kb_ai.storage import extraction
from kb_ai.storage.store import KEYS_MARKER, ArticleMeta, KBStore

DOCUMENT_INDEX_NAME = "document-index.md"

# Joins the routing signals a raw document's frontmatter carries for free onto
# its summary. Deliberately not separate columns: the line is only ever read by
# an LLM, and keeping the format byte-identical to the article catalog is what
# lets one parser (KBStore._parse_index) and one topic filter serve both.
_DOC_FIELD_SEP = " · "

# Frontmatter keys worth spending catalog budget on. `source` is the highest-value
# one in a cross-KB selection: it says which person or channel a document came
# from, which no amount of summary prose conveys.
_DOC_CONTEXT_KEYS = ("date", "source")

# Backstop bounding one catalog line, NOT the length the write phase aims for:
# core.merge asks it for "one sentence under 150 characters" and it empirically
# produces 143-200 (median 159, n=20 articles across two compiles of this
# repository). Capping at the instructed 150 clipped 13 of 15, and what it cut
# was the last enumerated specific ("...orchestrated classify->dedup->write
# pipeline") -- the routing terms the summary exists to carry. 200 is where that
# clipping stops; 250 changes nothing. It costs 5.6% more catalog, and selection
# recall is flat from 50 to 600 chars, so nothing else pays for it.
SUMMARY_MAX_CHARS = 200

# Budget for the keys column of one article. 500 chars holds ~30 keys, which
# covers every reference article in a 48-article compile of this repository
# (largest: 437 chars) while keeping a pathological table from dominating the
# retrieval prompt, where every article's line is paid for on every query.
KEYS_MAX_CHARS = 500

_KEYS_ELLIPSIS = ", …"

_HEADING_RE = re.compile(r"^#{1,6}\s")

# First cell of a table row when it is one backticked token -- how a reference
# table names the thing each row documents. Prose cells and the header/separator
# rows don't match, so a narrative article yields nothing.
_KEY_CELL_RE = re.compile(r"^\|\s*`([^\s`|]+)`\s*\|")


def _flatten(text: str, max_chars: int) -> str:
    """Collapse whitespace to a single line and cap it for the catalog entry.

    Trims at a word boundary where there is one: the catalog is a git-tracked
    file people read, and a first-paragraph fallback usually needs clipping.
    """
    flat = " ".join(text.split())
    if len(flat) <= max_chars:
        return flat
    clipped = flat[:max_chars]
    head, sep, _ = clipped.rpartition(" ")
    return f"{head}…" if sep else clipped


def _derive_summary(fm: dict, body: str, max_chars: int) -> str:
    """Pick the catalog summary for an article.

    Prefers a purpose-written ``summary`` from the frontmatter, else the first
    prose paragraph of the body. Skipping headings matters: compiled articles
    always open with one (``# Title`` / ``## Overview``), so taking the first
    paragraph verbatim fills the whole catalog with heading echoes and leaves
    LLM page selection navigating by title alone.
    """
    declared = fm.get("summary")
    if isinstance(declared, str) and declared.strip():
        return _flatten(declared, max_chars)

    for block in body.split("\n\n"):
        prose = [ln for ln in block.splitlines()
                 if ln.strip() and not _HEADING_RE.match(ln.strip())]
        if prose:
            return _flatten(" ".join(prose), max_chars)

    # Heading-only body: the heading text beats an empty summary column.
    for line in body.splitlines():
        if line.strip():
            return _flatten(line.lstrip("#"), max_chars)
    return ""


def _derive_keys(body: str) -> str:
    """List the identifiers a reference article documents, for its catalog line.

    A 150-char prose summary cannot advertise the dozens of discrete values a
    config or API table defines, so a narrow factual question ("how many entries
    may a zip hold?") has no signal pointing at the article holding the answer,
    and page selection falls back to whichever title sounds topical. The first
    cell of each table row is where such an article names its keys.

    Returns them comma-joined and capped at KEYS_MAX_CHARS, keeping whole keys
    only and marking a cut with a trailing "…" -- a half-written key would read
    as a different identifier. Prose articles yield "".
    """
    keys: list[str] = []
    seen: set[str] = set()
    for line in body.splitlines():
        m = _KEY_CELL_RE.match(line.strip())
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            keys.append(m.group(1))

    out = ""
    for i, key in enumerate(keys):
        # Reserve room for the cut marker while more keys are still pending, so
        # appending it later cannot push the column past the budget.
        limit = KEYS_MAX_CHARS - (len(_KEYS_ELLIPSIS) if i < len(keys) - 1 else 0)
        candidate = f"{out}, {key}" if out else key
        if len(candidate) > limit:
            return f"{out}{_KEYS_ELLIPSIS}" if out else ""
        out = candidate
    return out


def _document_frontmatter(content: str) -> tuple[dict, str]:
    """Split a raw document into (frontmatter, body), tolerating both absences.

    Unlike a wiki article, a raw document is not required to carry frontmatter --
    and a malformed one must not make the document unselectable, only unlabelled.
    So where update_markdown_index skips, this degrades to ({}, whole content).
    """
    split = split_frontmatter(content)
    if split is None:
        return {}, content
    try:
        fm = yaml.safe_load(split[0])
    except yaml.YAMLError:
        return {}, split[1]
    return (fm if isinstance(fm, dict) else {}), split[1]


def _document_summary(store: KBStore, rel_path: str, fm: dict, body: str,
                      max_chars: int) -> tuple[str, bool]:
    """The catalog summary for one raw document, cheapest source first.

    1. a ``summary`` declared in the document's own frontmatter
    2. the ``summary`` in the document's extraction frontmatter -- the
       document-level summary the compile pipeline already paid for
    3. the first prose paragraph, via the same _derive_summary the article
       catalog uses

    Returns (summary, used_body_fallback). Layer 3 is only reached by a document
    with no extraction yet -- fetched but never compiled -- and the caller reports
    how often that happened rather than leaving a materially worse catalog line
    silent.

    A lookup keyed by the raw path, not an iteration of extraction/: the title and
    the date/source context prefix come from the raw document's own frontmatter,
    which the extraction file does not carry, and an orphan extraction left by a
    deleted or renamed document would otherwise appear in the catalog as a
    document that no longer exists.

    Note the extraction summary is written for extraction, not for a catalog line:
    its median length is 361 chars against this budget's 200, so most entries are
    clipped by _flatten. Whether that clipping costs selection recall is open --
    it is measured before any second summarisation pass is worth paying for.
    """
    declared = fm.get("summary")
    if isinstance(declared, str) and declared.strip():
        return _flatten(declared, max_chars), False

    header, _reason = extraction.load_header(store, rel_path)
    if header:
        summary = header.get("summary")
        if isinstance(summary, str) and summary.strip():
            return _flatten(summary, max_chars), False

    # Empty frontmatter, so _derive_summary goes straight to the body.
    return _derive_summary({}, body.strip(), max_chars), True


def build_document_catalog(store: KBStore, *,
                           summary_max_chars: int | None = None) -> list[ArticleMeta]:
    """The raw-document catalog, computed without writing anything.

    The article catalog can only offer what compiling produced: a document that
    yielded no article is unreachable through it, and a KB that was never
    compiled has no catalog at all. Selecting over documents instead makes the
    unit of selection the unit that actually gets copied, which is what a
    cross-KB topic merge needs -- it can then read this and each KB's raw/, and
    never touch anyone's compiled wiki/.

    Returns ArticleMeta, not a document-specific type, so render_catalog_line,
    _filter.pack_batches and _filter.select_by_topic consume a document catalog
    and an article catalog through the same code path.

    Separate from update_document_index because derive opens its source KB
    read-only and, across KBs, that KB may belong to someone else and be
    genuinely unwritable -- a selection must not require write access.

    Content is read one document at a time and dropped, so peak memory stays at
    the size of the largest single document.
    """
    if summary_max_chars is None:
        summary_max_chars = SUMMARY_MAX_CHARS

    catalog: list[ArticleMeta] = []
    without_extraction = 0
    for path in store._iter_raw_paths():
        content = path.read_text()
        fm, body = _document_frontmatter(content)
        rel_path = str(path.relative_to(store.base_dir))

        context = _DOC_FIELD_SEP.join(
            str(fm[k]) for k in _DOC_CONTEXT_KEYS if fm.get(k))
        # The context prefix is paid for out of the same budget, not added on
        # top of it, so one line cannot exceed what the caller allowed.
        spent = len(context) + len(_DOC_FIELD_SEP) if context else 0
        summary, from_body = _document_summary(store, rel_path, fm, body,
                                               max(summary_max_chars - spent, 0))
        without_extraction += from_body

        catalog.append(ArticleMeta(
            title=str(fm.get("title") or path.stem),
            path=rel_path,
            summary=_DOC_FIELD_SEP.join(p for p in (context, summary) if p),
        ))

    # Reported rather than silent: a document with no extraction gets a
    # first-paragraph summary, which is materially worse for selection than the
    # one the compile pipeline would have paid for. One line, not one per
    # document -- a never-compiled KB is the legitimate case and hits every one.
    if without_extraction:
        print(f"[document-index] {without_extraction} of {len(catalog)} documents "
              "have no extraction yet; using their first paragraph as the summary",
              file=sys.stderr, flush=True)
    return catalog


def update_document_index(store: KBStore, *,
                          summary_max_chars: int | None = None) -> None:
    """Write build_document_catalog() to index/document-index.md.

    Rebuilt wholesale like update_markdown_index, so it cannot drift from raw/.
    Persisting it is what makes a later selection free; derive falls back to
    computing the catalog in memory when this file is absent.
    """
    catalog = build_document_catalog(store, summary_max_chars=summary_max_chars)
    store.index_dir.mkdir(exist_ok=True)
    out = "# Document Index\n\n" + "".join(
        f"- [{d.title}]({d.path}) — {d.summary}\n" for d in catalog)
    (store.index_dir / DOCUMENT_INDEX_NAME).write_text(out)


def update_markdown_index(store: KBStore, *, min_articles: int = 3,
                          summary_max_chars: int | None = None) -> None:
    """Rebuild master-index, topic indexes and the long-tail index.

    ``summary_max_chars`` trades summary length against article count: the whole
    catalog goes into every page-selection prompt, so a knowledge base large
    enough to strain that budget can shrink summaries instead of losing articles.
    Measured on a 48-article compile of this repository, selection recall was
    flat from 50 to 600 chars once the keys column existed, so the default is set
    by what the write phase actually emits rather than by recall -- see
    SUMMARY_MAX_CHARS. Defaults late (None) so the constant stays the single
    source of truth for the default.
    """
    if summary_max_chars is None:
        summary_max_chars = SUMMARY_MAX_CHARS
    store.index_dir.mkdir(exist_ok=True)

    articles = []
    tags_map: dict[str, list[dict]] = {}

    for md_file in store.wiki_dir.rglob("*.md"):
        content = md_file.read_text()
        split = split_frontmatter(content)
        if split is None:
            continue
        try:
            fm = yaml.safe_load(split[0])
        except yaml.YAMLError:
            continue
        # Empty frontmatter loads as None and scalar frontmatter as str. Skip
        # like the other malformed cases above -- one bad article must not abort
        # the whole index rebuild.
        if not isinstance(fm, dict):
            continue

        rel_path = str(md_file.relative_to(store.base_dir))
        title = fm.get("title", md_file.stem)
        article_type = fm.get("type", "unknown")
        tags = fm.get("tags", [])
        status = fm.get("status", "")
        body = split[1].strip()
        summary = _derive_summary(fm, body, summary_max_chars)

        articles.append({
            "title": title, "path": rel_path, "type": article_type,
            "tags": tags, "status": status, "summary": summary,
            "keys": _derive_keys(body),
        })
        for tag in tags:
            tags_map.setdefault(str(tag), []).append({"title": title, "path": rel_path})

    master = "# Knowledge Base Index\n\n"
    for a in sorted(articles, key=lambda x: x["title"]):
        status_marker = f" [{a['status']}]" if a.get("status") else ""
        keys_column = f"{KEYS_MARKER}{a['keys']}" if a["keys"] else ""
        master += (f"- [{a['title']}]({a['path']}){status_marker} — "
                   f"{a['summary']}{keys_column}\n")
    (store.index_dir / "master-index.md").write_text(master)

    # Split topic index by frequency.
    primary_tags = [(tag, arts) for tag, arts in tags_map.items() if len(arts) >= min_articles]
    longtail_tags = [(tag, arts) for tag, arts in tags_map.items() if len(arts) < min_articles]

    # Primary: sort by article count desc, tie-break by tag name asc.
    primary_tags.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    # Longtail: alphabetical.
    longtail_tags.sort(key=lambda kv: kv[0])

    primary_md = f"# Topic Index\n\nTags with at least {min_articles} articles, sorted by frequency.\n\n"
    for tag, arts in primary_tags:
        primary_md += f"## {tag} ({len(arts)})\n\n"
        for a in sorted(arts, key=lambda x: x["title"]):
            primary_md += f"- [{a['title']}]({a['path']})\n"
        primary_md += "\n"
    (store.index_dir / "topic-index.md").write_text(primary_md)

    longtail_md = f"# Topic Index — Long Tail\n\nTags with fewer than {min_articles} articles.\n\n"
    for tag, arts in longtail_tags:
        longtail_md += f"## {tag} ({len(arts)})\n\n"
        for a in sorted(arts, key=lambda x: x["title"]):
            longtail_md += f"- [{a['title']}]({a['path']})\n"
        longtail_md += "\n"
    (store.index_dir / "topic-index-longtail.md").write_text(longtail_md)


def update_timeline(store: KBStore, compiled_sources: list[str]) -> None:
    store.index_dir.mkdir(exist_ok=True)
    timeline_path = store.index_dir / "timeline.md"

    if not timeline_path.exists():
        timeline_path.write_text("# Knowledge Timeline\n\n")

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entries = f"\n## {now}\n\n"
    for src in compiled_sources:
        entries += f"- Compiled: `{src}`\n"

    with open(timeline_path, "a") as f:
        f.write(entries)
