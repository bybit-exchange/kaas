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
