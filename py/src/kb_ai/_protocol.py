"""Bridge protocol abstraction for Go<->Python subprocess communication.

Provides utility functions for the stdin/stdout JSON protocol used by the
Go bridge, plus base classes for streaming and request/response commands
with complete error boundary guarantees.
"""

import json
import sys
import traceback
from typing import Callable

from kb_ai._errors import KBError


def read_input() -> dict:
    """Read JSON input from stdin (bridge protocol)."""
    return json.loads(sys.stdin.read())


def respond_ok(data=None) -> None:
    """Write success response to stdout."""
    resp = {"ok": True}
    if data is not None:
        resp["data"] = data
    print(json.dumps(resp, ensure_ascii=False))


def respond_error(code: str, message: str) -> None:
    """Write error response to stdout."""
    print(
        json.dumps(
            {"ok": False, "error": {"code": code, "message": message}},
            ensure_ascii=False,
        )
    )


def stream_emit(event: dict) -> None:
    """Emit a streaming JSON-line event to stdout."""
    print(json.dumps(event, ensure_ascii=False), flush=True)


class RequestResponseCommand:
    """Base for request/response commands (extract, search, index).

    Error boundary: this class guarantees that exceptions never escape run().
    Exactly one JSON object is written to stdout.
    """

    def run(self) -> None:
        """Execute the command. Guaranteed not to raise."""
        try:
            input_data = read_input()
            result = self.execute(input_data)
            respond_ok(result)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            if isinstance(e, KBError):
                respond_error(e.code, str(e))
            else:
                respond_error("INTERNAL_ERROR", str(e))

    def execute(self, input_data: dict) -> dict:
        """Override in subclass to implement request/response logic.

        Args:
            input_data: Parsed JSON input from stdin.

        Returns:
            Result dict to be wrapped in respond_ok().
        """
        raise NotImplementedError


class StreamingCommand:
    """Base for streaming commands (chat, iterative, query).

    Error boundary: this class guarantees that exceptions never escape run().
    """

    def run(self) -> None:
        """Execute the command. Guaranteed not to raise."""
        try:
            input_data = read_input()
            self.execute(input_data, stream_emit)
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            try:
                error_event = {"type": "error", "message": str(e)}
                if isinstance(e, KBError):
                    error_event["code"] = e.code
                else:
                    error_event["code"] = "INTERNAL_ERROR"
                stream_emit(error_event)
            except Exception:
                pass

    def execute(self, input_data: dict, emit: Callable) -> None:
        """Override in subclass to implement streaming logic.

        Args:
            input_data: Parsed JSON input from stdin.
            emit: Callable to emit streaming events (calls stream_emit).
        """
        raise NotImplementedError
