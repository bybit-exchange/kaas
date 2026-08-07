"""Derive a topic-scoped knowledge base from a compiled KaaS knowledge base.

Orchestration only -- every phase lives in a private submodule:

    catalog  -> _filter.select_by_topic   (RECALL)
    articles -> _sources.resolve_documents
    disk     -> _layout.create / copy_documents / write_manifest
    compile  -> commands.compile.compile_kb  (UNCHANGED)
    catalog' -> _offtopic.prune            (PRECISION, opt-in via prune=True)

select, compile_fn and approve are injected and default late (None), so every
test drives this function with stubs and no test needs a real LLM (spec I1).
approve is how the CLI's volume gate (F5) reaches into the middle of the run
without this module knowing about TTYs or --yes.

See docs/features/derive-topic-kb-from-catalog/spec.md.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from kb_ai._errors import (  # noqa: F401 -- re-exported for callers
    DeriveError,
    InvalidSlugError,
    NestedDeriveError,
    NoCatalogError,
    NoDocumentsError,
    SlugExistsError,
    UnknownDerivedKBError,
)
from kb_ai.derive._filter import select_by_topic
from kb_ai.derive._layout import (  # noqa: F401 -- re-exported for callers
    assert_not_nested,
    check_slug_available,
    copy_documents,
    create,
    list_derived,
    normalise_slug,
    read_manifest,
    resolve_kb_dir,
    validate_slug,
    write_manifest,
)
from kb_ai.derive._offtopic import prune as prune_offtopic
from kb_ai.derive._status import (  # noqa: F401 -- re-exported for callers
    check_extractions,
    check_parent,
)
from kb_ai.derive._sources import (
    documents_from_paths,
    parse_sources,
    resolve_documents,
)
from kb_ai.derive._types import (  # noqa: F401 -- re-exported for callers
    MODE_PRECISION,
    MODE_RECALL,
    SELECT_FROM_ARTICLES,
    SELECT_FROM_DOCUMENTS,
    DeriveReport,
    DocumentRef,
    SelectionResult,
    Selector,
    Skipped,
)
from kb_ai.llm import get_request_tracker, tracker
from kb_ai.storage.index import build_document_catalog
from kb_ai.storage.store import KBStore

# Bumped when the manifest's shape changes incompatibly, so a future re-derive
# feature can refuse a manifest it does not understand.
MANIFEST_SCHEMA_VERSION = 1


def _manifest_payload(report: DeriveReport, *, source_kb: Path, model: str,
                      created_at: str, sources_by_article: dict[str, list[str]],
                      titles_by_path: dict[str, str],
                      select_from: str) -> dict:
    """Serialise a report into the manifest shape (spec E2, E3)."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_kb": str(source_kb),
        "topic": report.topic,
        "slug": report.slug,
        "created_at": created_at,
        "filter_model": model,
        # Which catalog the run filtered over. Additive, so schema_version stays
        # at 1: a reader that predates it sees the same keys it already knew, and
        # selected_articles is still empty exactly when no article was selected.
        "select_from": select_from,
        "selected_articles": [
            {"path": p, "title": titles_by_path.get(p, ""),
             "sources": sources_by_article.get(p, [])}
            for p in report.selected_articles
        ],
        "selected_documents": list(report.selected_documents),
        "skipped_articles": [{"path": s.ref, "reason": s.reason}
                             for s in report.skipped_articles],
        "skipped_documents": [{"ref": s.ref, "reason": s.reason}
                              for s in report.skipped_documents],
        "documents": [{"rel_path": d.rel_path, "checksum": d.checksum,
                       "size_bytes": d.size_bytes} for d in report.documents],
        "dropped_invented_paths": report.dropped_invented_paths,
        "filter_batches": report.filter_batches,
        "offtopic_articles": report.offtopic_articles,
        "compiled": report.compiled,
        "compile": report.compile,
        "cost": report.cost,
        "warnings": report.warnings,
    }


def derive_kb(
    source_kb: str,
    topic: str,
    *,
    slug: str | None = None,
    force: bool = False,
    prune: bool = False,
    select_from: str = SELECT_FROM_ARTICLES,
    model: str,
    select: Selector | None = None,
    compile_fn: Callable[..., dict] | None = None,
    approve: Callable[[DeriveReport], bool] | None = None,
) -> DeriveReport:
    """Build <source_kb>/derived/<slug>/ from the articles matching topic.

    Order matters and is not the same as the tech design's diagram: the slug is
    validated and checked for availability BEFORE the first LLM call, so a name
    clash costs nothing, while the derived directory is created only after at
    least one document resolves (B5).

    prune runs the PRECISION pass, which moves articles the topic filter rejects
    a second time into _offtopic/. It defaults to off: the two runs that have
    measured it put the move ratio at 0.83 and 0.00 -- too strict, then selecting
    nothing at all -- so it does not yet earn a place in the default output. See
    issue #24.

    select_from picks which catalog the RECALL pass filters over; see
    SELECT_FROM_ARTICLES / SELECT_FROM_DOCUMENTS. It stays on articles by default
    because those summaries are single-topic write-phase prose over a catalog
    roughly half the size, so the selection is both better and cheaper whenever
    the source KB is compiled and its articles carry sources:.

    Raises DeriveError or a subclass on every failure named in the spec.
    """
    if not topic.strip():
        raise DeriveError("topic must not be empty")
    if select_from not in (SELECT_FROM_ARTICLES, SELECT_FROM_DOCUMENTS):
        raise DeriveError(
            f"unknown select_from {select_from!r}; expected "
            f"{SELECT_FROM_ARTICLES!r} or {SELECT_FROM_DOCUMENTS!r}"
        )

    source = Path(source_kb).expanduser().resolve()
    assert_not_nested(source)

    slug = slug or normalise_slug(topic)
    validate_slug(slug)
    check_slug_available(source, slug, force)

    if select is None:
        def select(catalog, topic_, mode):  # noqa: F811 -- late default
            return select_by_topic(catalog, topic_, mode, model=model)
    if compile_fn is None:
        from kb_ai.commands.compile import compile_kb as compile_fn  # noqa: F811

    source_store = KBStore(str(source), read_only=True)

    if select_from == SELECT_FROM_DOCUMENTS:
        # Prefer the written index (free), fall back to computing the catalog in
        # memory. Never materialise it here: source_store is read-only and, in a
        # cross-KB merge, the KB may not be ours to write to.
        catalog = source_store.existing_documents() or build_document_catalog(
            source_store)
        if not catalog:
            raise NoDocumentsError(
                f"{source} has no documents under raw/; nothing to select from")
        selection = select(catalog, topic, MODE_RECALL)
        documents, skipped_documents = documents_from_paths(
            source_store, selection.paths)
        # selection.skipped holds line_over_budget refs, which here are document
        # paths -- so they belong under skipped_documents. No article is involved
        # in this mode, so skipped_articles stays empty rather than holding
        # document paths under an article-shaped key.
        skipped_documents = list(selection.skipped) + skipped_documents
        skipped_articles = []
    else:
        catalog = source_store.existing_articles()
        if not catalog:
            raise NoCatalogError(
                f"{source} has no index/master-index.md; derive needs a compiled "
                "knowledge base"
            )
        selection = select(catalog, topic, MODE_RECALL)
        documents, skipped_articles, skipped_documents = resolve_documents(
            source_store, selection.paths)
        skipped_articles = list(selection.skipped) + skipped_articles

    titles_by_path = {a.path: a.title for a in catalog}

    if not documents:
        raise NoDocumentsError(
            f"none of the {len(selection.paths)} matching "
            f"{'documents' if select_from == SELECT_FROM_DOCUMENTS else 'articles'} "
            "resolved to a readable source document; nothing to derive"
        )

    derived_dir = create(source, slug, force)

    documents_mode = select_from == SELECT_FROM_DOCUMENTS
    report = DeriveReport(
        derived_kb=str(derived_dir),
        slug=slug,
        topic=topic,
        selected_articles=[] if documents_mode else list(selection.paths),
        selected_documents=list(selection.paths) if documents_mode else [],
        skipped_articles=skipped_articles,
        skipped_documents=skipped_documents,
        dropped_invented_paths=selection.dropped_invented,
        filter_batches=selection.batches,
    )

    # sources: per selected article, for the manifest's provenance record. Under
    # SELECT_FROM_DOCUMENTS the selected paths ARE the documents, so there is no
    # indirection to record -- report.documents already carries them.
    sources_by_article: dict[str, list[str]] = {}
    if not documents_mode:
        for path in selection.paths:
            entries, _reason = parse_sources(source_store, path)
            sources_by_article[path] = entries or []

    created_at = datetime.now().isoformat(timespec="seconds")

    def flush() -> None:
        write_manifest(derived_dir, _manifest_payload(
            report, source_kb=source, model=model, created_at=created_at,
            sources_by_article=sources_by_article, titles_by_path=titles_by_path,
            select_from=select_from))

    def snapshot_cost() -> None:
        """Record whole-run spend into report.cost.

        Prefers the per-request tracker when the daemon has set one
        (server_daemon.py creates a fresh CostTracker per request to avoid
        cross-request accumulation); falls back to the process-wide tracker for
        the one-shot CLI path where no per-request tracker is set.
        """
        req = get_request_tracker()
        report.cost = (req if req is not None else tracker).summary()

    # Written the moment the directory exists, before anything that can fail:
    # a half-built derive then identifies itself as ours, so the --force retry
    # the CLI advises is accepted instead of hitting check_slug_available's
    # "a directory this command did not create". documents is still empty here
    # -- nothing has been copied yet, so nothing is claimed.
    flush()

    _copied, copy_warnings = copy_documents(source_store, derived_dir, documents)
    report.warnings.extend(copy_warnings)
    report.documents = documents
    flush()  # E1: full record written before compiling, so a run that dies
             # mid-compile still records what it intended.

    if approve is not None and not approve(report):
        # The RECALL pass has already been paid for; a declined run must still
        # report and record what it spent (F6, E3).
        snapshot_cost()
        flush()
        return report

    # A derived KB inherits its source's frozen category set. Falling back to
    # DEFAULT_CATEGORIES would file the derived articles under categories the
    # source deliberately excluded -- the silent re-partition that freezing the
    # set per KB exists to prevent. None on a source predating that feature.
    compile_result = compile_fn(str(derived_dir), extract_model=model,
                                compile_model=model, write_model=model,
                                categories=source_store.load_config().get("categories"))
    # compile_kb returns the PROCESS-WIDE tracker summary, which here would be the
    # RECALL pass plus, in the long-lived daemon, every earlier request's spend.
    # report.cost is the authoritative per-request figure, so the misleading key
    # is dropped rather than published over HTTP and into the manifest.
    report.compile = {k: v for k, v in compile_result.items() if k != "cost"}
    report.compiled = True
    flush()  # E3: record compiled=true before the PRECISION pass; if prune raises,
             # the on-disk manifest still shows a fully compiled KB rather than the
             # pre-compile state, so recovery does not need to re-pay for compile.

    if prune:
        moved, warnings = prune_offtopic(derived_dir, topic, select)
        report.offtopic_articles = moved
        report.warnings.extend(warnings)

    # After the PRECISION pass, so that pass's spend is included -- compile's own
    # cost snapshot cannot contain it.
    snapshot_cost()
    flush()
    return report
