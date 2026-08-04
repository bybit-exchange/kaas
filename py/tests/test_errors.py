"""Tests for kb_ai._errors module."""
from __future__ import annotations

import pytest

from kb_ai._errors import (
    KBError,
    LLMTimeoutError,
    LLMGatewayError,
    PromptTooLargeError,
    PipelineCancelledError,
    DeadlineExceededError,
    OutputTruncatedError,
)


# ── Error code attributes ─────────────────────────────────────────────

class TestErrorCodes:
    def test_kberror_has_internal_error_code(self):
        e = KBError("something broke")
        assert e.code == "INTERNAL_ERROR"
        assert str(e) == "something broke"

    def test_llm_timeout_error_code(self):
        e = LLMTimeoutError("timed out after 3 attempts")
        assert e.code == "LLM_TIMEOUT"
        assert "timed out" in str(e)

    def test_llm_gateway_error_code(self):
        e = LLMGatewayError("502 bad gateway")
        assert e.code == "LLM_GATEWAY"

    def test_prompt_too_large_error_code(self):
        e = PromptTooLargeError("120000 chars")
        assert e.code == "PROMPT_TOO_LARGE"

    def test_pipeline_cancelled_error_code(self):
        e = PipelineCancelledError("client disconnected")
        assert e.code == "CANCELLED"

    def test_deadline_exceeded_error_code(self):
        e = DeadlineExceededError("too close to retry")
        assert e.code == "DEADLINE_EXCEEDED"

    def test_output_truncated_error_code(self):
        e = OutputTruncatedError("at ceiling 64000")
        assert e.code == "OUTPUT_TRUNCATED"


# ── Inheritance ────────────────────────────────────────────────────────

class TestInheritance:
    @pytest.mark.parametrize("cls", [
        LLMTimeoutError,
        LLMGatewayError,
        PromptTooLargeError,
        PipelineCancelledError,
        DeadlineExceededError,
        OutputTruncatedError,
    ])
    def test_all_subclass_kberror(self, cls):
        assert issubclass(cls, KBError)

    @pytest.mark.parametrize("cls", [
        LLMTimeoutError,
        LLMGatewayError,
        PromptTooLargeError,
        PipelineCancelledError,
        DeadlineExceededError,
        OutputTruncatedError,
    ])
    def test_all_subclass_exception(self, cls):
        assert issubclass(cls, Exception)

    def test_catch_kberror_catches_subtypes(self):
        with pytest.raises(KBError):
            raise LLMTimeoutError("oops")

    def test_catch_specific_type(self):
        with pytest.raises(PipelineCancelledError):
            raise PipelineCancelledError("cancelled")


# ── Code uniqueness ────────────────────────────────────────────────────

def test_all_error_codes_are_unique():
    codes = [
        KBError.code,
        LLMTimeoutError.code,
        LLMGatewayError.code,
        PromptTooLargeError.code,
        PipelineCancelledError.code,
        DeadlineExceededError.code,
        OutputTruncatedError.code,
    ]
    assert len(codes) == len(set(codes)), f"Duplicate codes found: {codes}"


# ── Derive error family ────────────────────────────────────────────────

def test_derive_error_codes():
    from kb_ai._errors import (
        DeriveError, InvalidSlugError, KBError, NestedDeriveError, NoCatalogError,
        NoDocumentsError, SlugExistsError, UnknownDerivedKBError,
    )

    expected = {
        DeriveError: "DERIVE_FAILED",
        NoCatalogError: "NO_CATALOG",
        InvalidSlugError: "INVALID_SLUG",
        SlugExistsError: "SLUG_EXISTS",
        NestedDeriveError: "NESTED_DERIVE",
        NoDocumentsError: "NO_DOCUMENTS",
        UnknownDerivedKBError: "UNKNOWN_DERIVED_KB",
    }
    for cls, code in expected.items():
        assert cls.code == code
        assert issubclass(cls, KBError)
    for cls in expected:
        if cls is not DeriveError:
            assert issubclass(cls, DeriveError)


def test_derive_report_defaults():
    from kb_ai.derive._types import DeriveReport

    r = DeriveReport(derived_kb="/kb/derived/x", slug="x", topic="pricing")
    assert r.compiled is False
    assert r.compile is None
    assert r.selected_articles == []
    assert r.warnings == []
