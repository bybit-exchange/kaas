"""Value objects shared by the derive phases (spec A–E).

Kept out of the package __init__ so _filter, _sources, _layout and _offtopic can
import them without a cycle through the orchestrator -- the same reason
kb_ai/_types.py exists.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from kb_ai.storage.store import ArticleMeta

# Filter modes. The two passes have opposite failure costs, so they share one
# prompt template with different inclusion instructions (spec O4).
#   RECALL    -- first pass over the source catalog. A missed article loses its
#                documents permanently, so include anything that could help.
#   PRECISION -- second pass over the derived catalog. Every article here came
#                from documents already judged topical, so a permissive prompt
#                would select everything and the pass would do nothing.
MODE_RECALL = "recall"
MODE_PRECISION = "precision"

# What a run filters over.
#   ARTICLES  -- the compiled catalog, then each selected article's sources:.
#                Summaries are the write phase's own prose, so they are single-
#                topic and already de-noised, and the catalog is smaller.
#   DOCUMENTS -- the raw-document catalog. The unit of selection becomes the unit
#                that gets copied, which removes the sources: hop, reaches
#                documents that produced no article, and works on a KB that was
#                never compiled -- what a cross-KB topic merge needs.
SELECT_FROM_ARTICLES = "articles"
SELECT_FROM_DOCUMENTS = "documents"


@dataclass(frozen=True)
class Skipped:
    """One thing the run could not use, and why.

    reason is drawn from a fixed vocabulary so the manifest stays
    machine-readable: no_sources_key, empty_sources, unparseable_frontmatter,
    article_unreadable, escapes_kb, not_a_raw_document, document_missing,
    document_unreadable, line_over_budget.
    """

    ref: str
    reason: str


@dataclass(frozen=True)
class SelectionResult:
    """What one topic-filter pass decided. Identical shape for 1 or N batches (A7)."""

    paths: list[str]
    batches: int
    dropped_invented: int
    skipped: list[Skipped]


@dataclass(frozen=True)
class DocumentRef:
    """A source document to copy into the derived KB.

    size_bytes feeds the CLI volume gate (F5); checksum is the 16-hex-char
    SHA-256 prefix storage.store._compute_checksum produces, so it also keys the
    extract-cache entry copied alongside the document (C7, E4).
    """

    rel_path: str
    checksum: str
    size_bytes: int


@dataclass
class DeriveReport:
    """Everything one derive run decided and did. Serialised into manifest.json.

    cost is the authoritative per-request spend for the whole run. compile holds
    compile_kb's result summary with its own "cost" key removed: that key is a
    process-wide tracker snapshot, so in the long-lived daemon it would report the
    daemon's lifetime spend rather than this run's.
    """

    derived_kb: str
    slug: str
    topic: str
    selected_articles: list[str] = field(default_factory=list)
    # Populated instead of selected_articles under SELECT_FROM_DOCUMENTS. Kept
    # separate rather than overloading one field: the two hold different kinds of
    # path, and a manifest reader must not have to guess which.
    selected_documents: list[str] = field(default_factory=list)
    skipped_articles: list[Skipped] = field(default_factory=list)
    skipped_documents: list[Skipped] = field(default_factory=list)
    documents: list[DocumentRef] = field(default_factory=list)
    dropped_invented_paths: int = 0
    filter_batches: int = 0
    offtopic_articles: list[str] = field(default_factory=list)
    compiled: bool = False
    compile: dict | None = None
    # Whole-run LLM spend, read from the per-request tracker (or the process-wide
    # one on the CLI path) after the second pass -- compile's own summary predates
    # that pass, so it is not the total. Set even when the volume gate declines:
    # the RECALL pass has already been paid for by then (F6, E3).
    cost: dict | None = None
    warnings: list[str] = field(default_factory=list)


# (catalog, topic, mode) -> SelectionResult. The model is bound by the caller, so
# tests inject a three-argument stub and no test needs a real LLM (spec I1).
Selector = Callable[[list[ArticleMeta], str, str], SelectionResult]
