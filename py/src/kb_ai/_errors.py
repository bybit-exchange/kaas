"""Typed exception hierarchy for kb-ai domain errors."""


class KBError(Exception):
    """Base for all kb-ai domain errors. Carries a machine-readable code."""

    code: str = "INTERNAL_ERROR"

    def __init__(self, message: str):
        super().__init__(message)


class LLMTimeoutError(KBError):
    """LLM API call timed out after all retries."""

    code = "LLM_TIMEOUT"


class LLMGatewayError(KBError):
    """LLM gateway returned 502/503/504 after all retries."""

    code = "LLM_GATEWAY"


class PromptTooLargeError(KBError):
    """Prompt exceeds the configured character limit."""

    code = "PROMPT_TOO_LARGE"


class PipelineCancelledError(KBError):
    """Pipeline was cancelled (client disconnected)."""

    code = "CANCELLED"


class DeadlineExceededError(KBError):
    """Pipeline deadline is too close to continue or retry."""

    code = "DEADLINE_EXCEEDED"


class OutputTruncatedError(KBError):
    """LLM output was truncated and cannot be retried (at ceiling)."""

    code = "OUTPUT_TRUNCATED"


class DeriveError(KBError):
    """A topic-scoped derive run failed.

    Derive fails loudly where retrieval degrades: an empty selection or a
    swallowed LLM error would silently produce an empty knowledge base.
    """

    code = "DERIVE_FAILED"


class NoCatalogError(DeriveError):
    """The source knowledge base has no index/master-index.md to filter."""

    code = "NO_CATALOG"


class InvalidSlugError(DeriveError):
    """The derived-KB slug is empty or is not a single safe path segment."""

    code = "INVALID_SLUG"


class SlugExistsError(DeriveError):
    """derived/<slug>/ already exists and --force was not given."""

    code = "SLUG_EXISTS"


class NestedDeriveError(DeriveError):
    """The source knowledge base is itself a derived one; nesting stops at one level."""

    code = "NESTED_DERIVE"


class NoDocumentsError(DeriveError):
    """No selected article resolved to a readable source document."""

    code = "NO_DOCUMENTS"


class UnknownDerivedKBError(DeriveError):
    """The requested derived-KB slug does not exist.

    Never a fallback to the root KB: answering from the wrong corpus silently is
    worse than an error (spec G3).
    """

    code = "UNKNOWN_DERIVED_KB"
