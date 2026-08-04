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


@dataclass(frozen=True)
class Skipped:
    """One thing the run could not use, and why.

    reason is drawn from a fixed vocabulary so the manifest stays
    machine-readable: no_sources_key, empty_sources, unparseable_frontmatter,
    article_unreadable, escapes_kb, document_missing, document_unreadable,
    line_over_budget.
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
    """Everything one derive run decided and did. Serialised into manifest.json."""

    derived_kb: str
    slug: str
    topic: str
    selected_articles: list[str] = field(default_factory=list)
    skipped_articles: list[Skipped] = field(default_factory=list)
    skipped_documents: list[Skipped] = field(default_factory=list)
    documents: list[DocumentRef] = field(default_factory=list)
    dropped_invented_paths: int = 0
    filter_batches: int = 0
    offtopic_articles: list[str] = field(default_factory=list)
    compiled: bool = False
    compile: dict | None = None
    # Whole-run LLM spend, read from the process-wide tracker after the second
    # pass -- compile's own summary predates that pass, so it is not the total.
    cost: dict | None = None
    warnings: list[str] = field(default_factory=list)


# (catalog, topic, mode) -> SelectionResult. The model is bound by the caller, so
# tests inject a three-argument stub and no test needs a real LLM (spec I1).
Selector = Callable[[list[ArticleMeta], str, str], SelectionResult]
