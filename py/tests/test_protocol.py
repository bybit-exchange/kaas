"""Tests for kb_ai._protocol module."""

from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from kb_ai._errors import KBError, LLMTimeoutError, PromptTooLargeError
from kb_ai._protocol import (
    RequestResponseCommand,
    StreamingCommand,
    read_input,
    respond_error,
    respond_ok,
    stream_emit,
)


class TestReadInput:
    def test_reads_json_from_stdin(self):
        with patch("sys.stdin", StringIO('{"key": "value"}')):
            result = read_input()
        assert result == {"key": "value"}

    def test_raises_on_invalid_json(self):
        with patch("sys.stdin", StringIO("not json")):
            with pytest.raises(json.JSONDecodeError):
                read_input()


class TestRespondOk:
    def test_with_data(self, capsys):
        respond_ok({"result": 42})
        output = json.loads(capsys.readouterr().out.strip())
        assert output == {"ok": True, "data": {"result": 42}}

    def test_without_data(self, capsys):
        respond_ok()
        output = json.loads(capsys.readouterr().out.strip())
        assert output == {"ok": True}

    def test_with_none_data(self, capsys):
        respond_ok(None)
        output = json.loads(capsys.readouterr().out.strip())
        assert output == {"ok": True}


class TestRespondError:
    def test_formats_error_response(self, capsys):
        respond_error("TEST_CODE", "something failed")
        output = json.loads(capsys.readouterr().out.strip())
        assert output == {
            "ok": False,
            "error": {"code": "TEST_CODE", "message": "something failed"},
        }


class TestStreamEmit:
    def test_emits_json_line(self, capsys):
        stream_emit({"type": "chunk", "data": "hello"})
        output = json.loads(capsys.readouterr().out.strip())
        assert output == {"type": "chunk", "data": "hello"}


class TestRequestResponseCommand:
    """AC2: when a RequestResponseCommand subclass raises KBError,
    run() outputs {ok: false, error: {code, message}} without raising."""

    def test_success_path(self, capsys):
        class MyCommand(RequestResponseCommand):
            def execute(self, input_data: dict) -> dict:
                return {"answer": input_data["question"]}

        with patch("sys.stdin", StringIO('{"question": "hello"}')):
            MyCommand().run()

        output = json.loads(capsys.readouterr().out.strip())
        assert output == {"ok": True, "data": {"answer": "hello"}}

    def test_kb_error_mapped_to_respond_error(self, capsys):
        """KBError subclass -> respond_error with proper code."""

        class FailingCommand(RequestResponseCommand):
            def execute(self, input_data: dict) -> dict:
                raise LLMTimeoutError("timed out after 180s")

        with patch("sys.stdin", StringIO("{}")):
            # Must not raise
            FailingCommand().run()

        output = json.loads(capsys.readouterr().out.strip())
        assert output["ok"] is False
        assert output["error"]["code"] == "LLM_TIMEOUT"
        assert "timed out" in output["error"]["message"]

    def test_prompt_too_large_error(self, capsys):
        class FailingCommand(RequestResponseCommand):
            def execute(self, input_data: dict) -> dict:
                raise PromptTooLargeError("prompt exceeds 80K chars")

        with patch("sys.stdin", StringIO("{}")):
            FailingCommand().run()

        output = json.loads(capsys.readouterr().out.strip())
        assert output["ok"] is False
        assert output["error"]["code"] == "PROMPT_TOO_LARGE"
        assert "80K" in output["error"]["message"]

    def test_generic_exception_mapped_to_internal_error(self, capsys):
        class FailingCommand(RequestResponseCommand):
            def execute(self, input_data: dict) -> dict:
                raise RuntimeError("unexpected crash")

        with patch("sys.stdin", StringIO("{}")):
            FailingCommand().run()

        output = json.loads(capsys.readouterr().out.strip())
        assert output["ok"] is False
        assert output["error"]["code"] == "INTERNAL_ERROR"
        assert "unexpected crash" in output["error"]["message"]

    def test_run_does_not_raise(self):
        """run() never propagates exceptions to the caller."""

        class FailingCommand(RequestResponseCommand):
            def execute(self, input_data: dict) -> dict:
                raise ValueError("boom")

        with patch("sys.stdin", StringIO("{}")):
            # This must not raise
            FailingCommand().run()


class TestStreamingCommand:
    """AC3: when a StreamingCommand subclass raises, run() emits error event without raising."""

    def test_success_path(self, capsys):
        class MyStream(StreamingCommand):
            def execute(self, input_data: dict, emit) -> None:
                emit({"type": "chunk", "text": "hello"})
                emit({"type": "done"})

        with patch("sys.stdin", StringIO('{"prompt": "hi"}')):
            MyStream().run()

        lines = capsys.readouterr().out.strip().split("\n")
        events = [json.loads(line) for line in lines]
        assert events[0] == {"type": "chunk", "text": "hello"}
        assert events[1] == {"type": "done"}

    def test_kb_error_emits_error_event(self, capsys):
        """KBError in streaming -> error event with code."""

        class FailingStream(StreamingCommand):
            def execute(self, input_data: dict, emit) -> None:
                raise LLMTimeoutError("API timeout")

        with patch("sys.stdin", StringIO("{}")):
            # Must not raise
            FailingStream().run()

        output = json.loads(capsys.readouterr().out.strip())
        assert output["type"] == "error"
        assert output["code"] == "LLM_TIMEOUT"
        assert "timeout" in output["message"].lower()

    def test_generic_exception_emits_error_event(self, capsys):
        class FailingStream(StreamingCommand):
            def execute(self, input_data: dict, emit) -> None:
                raise RuntimeError("oops")

        with patch("sys.stdin", StringIO("{}")):
            FailingStream().run()

        output = json.loads(capsys.readouterr().out.strip())
        assert output["type"] == "error"
        assert output["code"] == "INTERNAL_ERROR"
        assert "oops" in output["message"]

    def test_run_does_not_raise(self):
        """run() never propagates exceptions to the caller."""

        class FailingStream(StreamingCommand):
            def execute(self, input_data: dict, emit) -> None:
                raise ValueError("boom")

        with patch("sys.stdin", StringIO("{}")):
            # This must not raise
            FailingStream().run()

    def test_partial_emit_then_error(self, capsys):
        """If some events were emitted before the error, error event follows them."""

        class PartialStream(StreamingCommand):
            def execute(self, input_data: dict, emit) -> None:
                emit({"type": "chunk", "text": "partial"})
                raise KBError("mid-stream failure")

        with patch("sys.stdin", StringIO("{}")):
            PartialStream().run()

        lines = capsys.readouterr().out.strip().split("\n")
        events = [json.loads(line) for line in lines]
        assert events[0] == {"type": "chunk", "text": "partial"}
        assert events[1]["type"] == "error"
        assert events[1]["code"] == "INTERNAL_ERROR"
        assert "mid-stream" in events[1]["message"]
