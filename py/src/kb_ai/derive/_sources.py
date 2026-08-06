"""Follow selected articles' sources: frontmatter to source documents (B1-B5).

sources: is written by the compile pipeline (core/merge.py) from LLM output, so
every value here is attacker-influenced: reads go through KBStore.read_raw ->
_resolve, which resolves symlinks and rejects escapes. A rejected or missing
entry is recorded and the run continues -- one bad path must not discard the
documents that did resolve.
"""
from __future__ import annotations

import posixpath

import yaml

from kb_ai._frontmatter import split_frontmatter
from kb_ai.derive._types import DocumentRef, Skipped
from kb_ai.storage.store import KBStore, _compute_checksum

_RAW_PREFIX = "raw/"


def _is_raw_document(rel: str) -> bool:
    """True when rel names a file inside the KB's raw/ subtree (spec C1).

    KBStore._resolve only enforces containment in the KB, so without this an
    LLM-written 'sources: wiki/pricing.md' would copy a compiled article into the
    derived wiki, and 'sources: .compile-state.json' would make the derived
    compile believe every document was already compiled. Normalised first, so
    'raw/../wiki/x.md' does not pass on its lexical prefix.
    """
    return posixpath.normpath(rel).startswith(_RAW_PREFIX)


def parse_sources(store: KBStore, article_path: str) -> tuple[list[str] | None, str]:
    """Read an article's sources: entries.

    Returns (entries, "") on success, or (None, reason) with reason one of
    article_unreadable, unparseable_frontmatter, no_sources_key, empty_sources.
    """
    try:
        content = store.read_article(article_path)
    except (OSError, ValueError):
        return None, "article_unreadable"

    split = split_frontmatter(content)
    if split is None:
        return None, "unparseable_frontmatter"
    try:
        fm = yaml.safe_load(split[0])
    except yaml.YAMLError:
        return None, "unparseable_frontmatter"
    if not isinstance(fm, dict):
        return None, "unparseable_frontmatter"
    if "sources" not in fm:
        return None, "no_sources_key"

    raw = fm["sources"]
    if isinstance(raw, str):
        entries = [raw]
    elif isinstance(raw, list):
        entries = [e for e in raw if isinstance(e, str)]
    else:
        return None, "unparseable_frontmatter"

    # A batch merge records several documents in ONE entry: commands/compile.py
    # passes ", ".join(merge_rels) as source_path and core.merge appends it as a
    # single "  - raw/a.md, raw/b.md" line. Treating that as one path would lose
    # every document behind a batch-merged article.
    out: list[str] = []
    for entry in entries:
        out.extend(piece.strip() for piece in entry.split(",") if piece.strip())
    if not out:
        return None, "empty_sources"
    return out, ""


def _read_document(store: KBStore, rel: str) -> tuple[DocumentRef | None, str]:
    """Resolve one raw-document path to a DocumentRef, or (None, reason).

    The security checks and their ordering match resolve_documents: containment
    is enforced by KBStore._resolve (which also resolves symlinks), and the
    raw/ check runs after the read so an escaping entry keeps the more specific
    escapes_kb reason.
    """
    try:
        content = store.read_raw(rel)
    except ValueError:
        return None, "escapes_kb"
    except FileNotFoundError:
        return None, "document_missing"
    except OSError:
        return None, "document_unreadable"
    if not _is_raw_document(rel):
        return None, "not_a_raw_document"
    return DocumentRef(rel_path=rel, checksum=_compute_checksum(content),
                       size_bytes=len(content.encode())), ""


def documents_from_paths(
    store: KBStore, paths: list[str],
) -> tuple[list[DocumentRef], list[Skipped]]:
    """Resolve selected raw-document paths straight to DocumentRefs.

    The document-catalog counterpart of resolve_documents: when the topic filter
    selects over documents, the selected path IS the document, so there is no
    sources: frontmatter to follow -- and none of its failure modes
    (no_sources_key, unparseable_frontmatter, a batch-merged comma-joined entry).

    Same guarantees as resolve_documents otherwise: de-duplicated, sorted by
    rel_path, every rejection recorded rather than raised, and content read only
    to compute the checksum and size before being dropped.
    """
    found: dict[str, DocumentRef] = {}
    skipped: list[Skipped] = []
    seen_bad: set[str] = set()

    for rel in paths:
        if not isinstance(rel, str) or rel in found or rel in seen_bad:
            continue
        doc, reason = _read_document(store, rel)
        if doc is None:
            seen_bad.add(rel)
            skipped.append(Skipped(ref=rel, reason=reason))
            continue
        found[rel] = doc

    return [found[k] for k in sorted(found)], skipped


def resolve_documents(
    store: KBStore, article_paths: list[str],
) -> tuple[list[DocumentRef], list[Skipped], list[Skipped]]:
    """De-duplicated union of the documents behind article_paths (B1-B4).

    Returns (documents, skipped_articles, skipped_documents). Documents come back
    in stable sorted order by rel_path; each is reported at most once even when
    several articles name it. Content is read to compute the checksum and size
    and then dropped -- the copy step re-reads it, which keeps peak memory off
    the size of the whole selection.
    """
    skipped_articles: list[Skipped] = []
    skipped_documents: list[Skipped] = []
    found: dict[str, DocumentRef] = {}
    seen_bad: set[str] = set()

    for article_path in article_paths:
        entries, reason = parse_sources(store, article_path)
        if entries is None:
            skipped_articles.append(Skipped(ref=article_path, reason=reason))
            continue
        for rel in entries:
            if rel in found or rel in seen_bad:
                continue
            try:
                content = store.read_raw(rel)
            except ValueError:
                # _resolve rejected it: absolute path, "../" climb, or a symlink
                # leading out of the KB.
                seen_bad.add(rel)
                skipped_documents.append(Skipped(ref=rel, reason="escapes_kb"))
                continue
            except FileNotFoundError:
                seen_bad.add(rel)
                skipped_documents.append(Skipped(ref=rel, reason="document_missing"))
                continue
            except OSError:
                seen_bad.add(rel)
                skipped_documents.append(Skipped(ref=rel, reason="document_unreadable"))
                continue
            # Checked after the read so an escaping entry keeps its escapes_kb
            # reason (B3); only entries that resolve inside the KB but outside
            # raw/ reach this branch.
            if not _is_raw_document(rel):
                seen_bad.add(rel)
                skipped_documents.append(Skipped(ref=rel, reason="not_a_raw_document"))
                continue
            found[rel] = DocumentRef(
                rel_path=rel,
                checksum=_compute_checksum(content),
                size_bytes=len(content.encode()),
            )

    documents = [found[k] for k in sorted(found)]
    return documents, skipped_articles, skipped_documents
