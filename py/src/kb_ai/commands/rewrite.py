"""Server-side query rewrite: resolve coreferences using conversation history.

Uses LiteLLM (via completion()) to rewrite an ambiguous follow-up question into
a self-contained search query, given the last few rounds of conversation history.
"""

import json
import sys

from kb_ai._protocol import RequestResponseCommand, respond_ok, respond_error
from kb_ai.llm import completion, CostTracker, get_request_tracker, set_request_tracker
from kb_ai.prompts import default_registry


def _format_history(history: list[dict]) -> str:
    """Format conversation history into a readable string."""
    lines = []
    for msg in history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def rewrite_query(query: str, history: list[dict] | None = None,
                  model: str = "claude-sonnet-4-6") -> dict:
    """Rewrite a query using conversation history for coreference resolution.

    Args:
        query: The current user question.
        history: List of previous conversation messages (role/content dicts).
        model: LLM model to use for rewriting.

    Returns:
        Dict with rewritten_query, tokens_prompt, tokens_completion, cost_usd.
    """
    # No history: return original query without LLM call
    if not history:
        return {
            "rewritten_query": query,
            "tokens_prompt": 0,
            "tokens_completion": 0,
            "cost_usd": 0.0,
        }

    formatted_history = _format_history(history)
    user_content = (
        f"Conversation history:\n{formatted_history}\n\n"
        f"Latest question: {query}\n\n"
        f"Rewritten query:"
    )

    system_prompt = default_registry().get("rewrite").render()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    # Per-request tracker isolates this call's tokens from concurrent requests.
    req_tracker = CostTracker()
    prev_tracker = get_request_tracker()
    set_request_tracker(req_tracker)
    try:
        rewritten = completion(model=model, messages=messages, temperature=0, max_tokens=256)
    finally:
        set_request_tracker(prev_tracker)

    # The tracker already priced each call (cache discount included), so read its
    # total rather than re-deriving one from the token counts.
    summary = req_tracker.summary()

    return {
        "rewritten_query": rewritten,
        "tokens_prompt": summary["total_prompt_tokens"],
        "tokens_completion": summary["total_completion_tokens"],
        "cost_usd": round(summary["total_cost_usd"], 8),
    }


def run_server_rewrite():
    """Bridge entry point: read JSON from stdin, write JSON to stdout."""
    from kb_ai._protocol import read_input

    input_data = read_input()
    query = input_data.get("query", "")
    history = input_data.get("history")
    model = input_data.get("model", "claude-sonnet-4-6")

    if not query:
        respond_error("EMPTY_QUERY", "query must not be empty")
        return

    result = rewrite_query(query, history, model=model)
    respond_ok(data=result)
