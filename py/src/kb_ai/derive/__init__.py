"""Derive a topic-scoped knowledge base from a compiled KaaS knowledge base.

Orchestration only -- every phase lives in a private submodule:

    catalog  -> _filter.select_by_topic   (RECALL)
    articles -> _sources.resolve_documents
    disk     -> _layout.create / copy_documents / write_manifest
    compile  -> commands.compile.compile_kb  (UNCHANGED)
    catalog' -> _offtopic.prune            (PRECISION)

select, compile_fn and approve are injected and default late (None), so every
test drives this function with stubs and no test needs a real LLM (spec I1).
approve is how the CLI's volume gate (F5) reaches into the middle of the run
without this module knowing about TTYs or --yes.

See docs/features/derive-topic-kb-from-catalog/spec.md.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

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
from kb_ai.derive._offtopic import prune
from kb_ai.derive._sources import resolve_documents
from kb_ai.derive._types import (  # noqa: F401 -- re-exported for callers
    MODE_PRECISION,
    MODE_RECALL,
    DeriveReport,
    DocumentRef,
    SelectionResult,
    Selector,
    Skipped,
)
from kb_ai.llm import tracker
from kb_ai.storage.store import KBStore

# Bumped when the manifest's shape changes incompatibly, so a future re-derive
# feature can refuse a manifest it does not understand.
MANIFEST_SCHEMA_VERSION = 1


def _manifest_payload(report: DeriveReport, *, source_kb: Path, model: str,
                      created_at: str, sources_by_article: dict[str, list[str]],
                      titles_by_path: dict[str, str]) -> dict:
    """Serialise a report into the manifest shape (spec E2, E3)."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "source_kb": str(source_kb),
        "topic": report.topic,
        "slug": report.slug,
        "created_at": created_at,
        "filter_model": model,
        "selected_articles": [
            {"path": p, "title": titles_by_path.get(p, ""),
             "sources": sources_by_article.get(p, [])}
            for p in report.selected_articles
        ],
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

    Raises DeriveError or a subclass on every failure named in the spec.
    """
    if not topic.strip():
        raise DeriveError("topic must not be empty")

    source = Path(source_kb).expanduser().resolve()
    from kb_ai.derive._layout import assert_not_nested
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
    catalog = source_store.existing_articles()
    if not catalog:
        raise NoCatalogError(
            f"{source} has no index/master-index.md; derive needs a compiled "
            "knowledge base"
        )
    titles_by_path = {a.path: a.title for a in catalog}

    selection = select(catalog, topic, MODE_RECALL)
    documents, skipped_articles, skipped_documents = resolve_documents(
        source_store, selection.paths)
    skipped_articles = list(selection.skipped) + skipped_articles

    if not documents:
        raise NoDocumentsError(
            f"none of the {len(selection.paths)} matching articles resolved to a "
            "readable source document; nothing to derive"
        )

    derived_dir = create(source, slug, force)
    copy_documents(source_store, derived_dir, documents)

    report = DeriveReport(
        derived_kb=str(derived_dir),
        slug=slug,
        topic=topic,
        selected_articles=list(selection.paths),
        skipped_articles=skipped_articles,
        skipped_documents=skipped_documents,
        documents=documents,
        dropped_invented_paths=selection.dropped_invented,
        filter_batches=selection.batches,
    )

    # sources: per selected article, for the manifest's provenance record.
    from kb_ai.derive._sources import parse_sources
    sources_by_article = {}
    for path in selection.paths:
        entries, _reason = parse_sources(source_store, path)
        sources_by_article[path] = entries or []

    created_at = datetime.now().isoformat(timespec="seconds")

    def flush() -> None:
        write_manifest(derived_dir, _manifest_payload(
            report, source_kb=source, model=model, created_at=created_at,
            sources_by_article=sources_by_article, titles_by_path=titles_by_path))

    flush()  # E1: written before compiling, so a run that dies still records intent

    if approve is not None and not approve(report):
        return report

    report.compile = compile_fn(str(derived_dir), extract_model=model,
                                compile_model=model, write_model=model)
    report.compiled = True

    moved, warnings = prune(derived_dir, topic, select)
    report.offtopic_articles = moved
    report.warnings.extend(warnings)

    # The process-wide tracker is the only place holding the WHOLE run: the
    # compile result's own cost snapshot predates the PRECISION pass.
    report.cost = tracker.summary()
    flush()
    return report
