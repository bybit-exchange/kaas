"""Streaming chat command for the KaaS server bridge.

Grounds the answer via LLM-iterative retrieval over the compiled markdown wiki
(master-index -> LLM page selection -> full-article context), builds a strict RAG
context, and streams the LLM response as JSON-line delta/done events.

Implements Anthropic prompt caching:
- System message (fixed instructions) gets cache_control: ephemeral
- Last history message gets cache_control: ephemeral
- Current user message (with RAG context) is NOT cached
- Adaptive toggle: disables caching after 10 consecutive cache misses

Uses its own AdaptiveCacheState instance (separate from llm/_completion.py).
"""

import json
import re
import sys
from typing import Callable

from openai import APIError, APIStatusError, APITimeoutError

from kb_ai._protocol import StreamingCommand
from kb_ai.llm import PRICING, _emit_alert, get_client
from kb_ai.llm._cache import AdaptiveCacheState
from kb_ai.prompts import default_registry
from kb_ai.retrieval.query import _assemble_article_context

# ---------------------------------------------------------------------------
# Adaptive prompt cache toggle — own instance, separate from llm/_completion.py
# ---------------------------------------------------------------------------
_cache_state = AdaptiveCacheState(miss_threshold=10, label="server-chat")


def _reset_cache_state() -> None:
    """Reset adaptive cache state — mainly for testing."""
    _cache_state.reset()


def _update_cache_state(cached_tokens: int, cache_created_tokens: int) -> None:
    """Update the adaptive cache toggle after a streaming call."""
    _cache_state.record_result(cached_tokens, cache_created_tokens)


def _build_system_message(use_cache: bool, prompt: str) -> dict:
    """Build the system message for the OpenAI-compatible API.

    When caching is enabled, uses content blocks with cache_control.
    When disabled, uses a plain string content.
    """
    if use_cache:
        return {
            "role": "system",
            "content": [{
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }],
        }
    return {"role": "system", "content": prompt}


def _add_cache_to_last_history(messages: list[dict]) -> list[dict]:
    """Add cache_control to the last message in history.

    Converts the last message's string content to a content block list
    with cache_control: ephemeral, which tells Anthropic to cache up to
    and including that message for future turns.
    """
    if not messages:
        return messages
    result = list(messages)  # shallow copy
    last = result[-1]
    if isinstance(last.get("content"), str):
        result[-1] = {
            "role": last["role"],
            "content": [
                {
                    "type": "text",
                    "text": last["content"],
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }
    return result


def _build_user_message(query: str, context: str) -> str:
    """Build the current user message content with RAG context.

    The reference_material is prepended to the user's question so the
    system prompt stays fixed (and cacheable) across turns.
    """
    if context:
        return f"<reference_material>\n{context}\n</reference_material>\n\n{query}"
    return query


def _estimate_cost(model: str, prompt_tokens: int, completion_tokens: int,
                   cached_tokens: int = 0) -> float:
    """Estimate USD cost from model name and token counts."""
    pricing = PRICING.get(model)
    if not pricing:
        # Try prefix match (e.g. "claude-sonnet-4-6-20250514" -> "claude-sonnet-4-6")
        for key, val in PRICING.items():
            if model.startswith(key.rsplit("-", 1)[0]):
                pricing = val
                break
    if not pricing:
        return 0.0
    non_cached = prompt_tokens - cached_tokens
    return (non_cached * pricing["input"]
            + cached_tokens * pricing["input"] * 0.1
            + completion_tokens * pricing["output"]) / 1_000_000


def _normalize_citation_path(path: str) -> str:
    """Reduce a cited link target to the wiki-relative form used by the catalog.

    Models spell the same article several ways -- `/wiki/a.md`, `./wiki/a.md`,
    `wiki/a`, with a `#section` anchor -- while retrieved paths are always bare
    `wiki/...md`. Without this, every citation missed the membership test below
    and cited_sources came back empty on every answer.
    """
    p = path.strip().split("#", 1)[0].removeprefix("./").lstrip("/")
    if not p.endswith(".md"):
        p += ".md"
    return p


def _extract_citations(answer_text: str, search_paths: set[str]) -> list[dict]:
    """Extract [Title](path) markdown links from LLM answer and intersect with search results.

    Only citations resolving to a path in the search_paths set are included, and
    the retrieved path is reported rather than the model's spelling of it.
    Duplicate paths are deduplicated (first occurrence wins).
    """
    pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    by_normalized = {_normalize_citation_path(p): p for p in search_paths}
    cited: list[dict] = []
    seen_paths: set[str] = set()
    for match in pattern.finditer(answer_text):
        title = match.group(1)
        resolved = by_normalized.get(_normalize_citation_path(match.group(2)))
        if resolved and resolved not in seen_paths:
            seen_paths.add(resolved)
            cited.append({"title": title, "path": resolved})
    return cited


def _run_chat_core(input_data: dict, emit_fn) -> None:
    """Core chat logic shared by stdin bridge and HTTP server.

    Args:
        input_data: Parsed JSON input dict.
        emit_fn: Callable that accepts a dict event to emit.
    """
    query = input_data.get("query", "")
    kb_dir = input_data.get("kb_dir", "")
    paths = input_data.get("paths") or []
    articles = input_data.get("articles") or []
    messages = input_data.get("messages") or []
    model = input_data.get("model", "claude-sonnet-4-6")
    temperature = input_data.get("temperature", 0)
    include_sources = input_data.get("include_sources", True)
    employee_id = input_data.get("employee_id") or None

    print(f"[server-chat] request: query={query!r}, kb_dir={kb_dir!r}, "
          f"model={model!r}, temperature={temperature}, "
          f"paths={len(paths)}, articles={len(articles)}, messages={len(messages)}",
          file=sys.stderr)

    # LLM-iterative retrieval (no embeddings): when the caller supplies a kb_dir
    # but no explicit articles, ground the answer from the compiled wiki.
    if kb_dir and query and not articles:
        from kb_ai.retrieval.retrieve import iterative_retrieve, read_articles
        articles = read_articles(paths, kb_dir) if paths \
            else iterative_retrieve(query, kb_dir, model=model)
        if articles:
            emit_fn({"type": "status", "stage": "retrieved",
                     "sources": [{"title": a["title"], "path": a["path"]} for a in articles]})

    # -- Build context from retrieved articles --
    retrieved_sources: list[dict] = []
    if articles:
        context = _assemble_article_context(articles)
        for a in articles:
            retrieved_sources.append({
                "title": a.get("title", ""),
                "path": a.get("path", ""),
            })
        print(f"[server-chat] {len(articles)} full articles, "
              f"{len(context):,} chars", file=sys.stderr)
    else:
        context = ""
        print("[server-chat] no context available", file=sys.stderr)

    # -- Determine cache eligibility --
    use_cache = _cache_state.is_enabled

    # -- Resolve system prompt from registry (routes by name+employee_id) --
    prompt_name = "chat-with-sources" if include_sources else "chat-no-sources"
    prompt = default_registry().get(prompt_name, employee_id=employee_id)
    system_text = prompt.render(employee_id=employee_id or "")

    # -- Build system message (fixed instructions, cacheable) --
    system_msg = _build_system_message(use_cache, system_text)

    # -- Build messages array --
    history_messages: list[dict] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant") and content:
            history_messages.append({"role": role, "content": content})

    # Go sends full messages (including current query) AND the query field
    # separately. Remove the trailing user message to avoid duplication.
    if history_messages and history_messages[-1]["role"] == "user":
        history_messages.pop()

    # Add cache_control to last history message for multi-turn caching.
    if use_cache and history_messages:
        history_messages = _add_cache_to_last_history(history_messages)

    # Build the current user message with RAG context embedded.
    chat_messages: list[dict] = [system_msg] + list(history_messages)
    if query:
        user_content = _build_user_message(query, context)
        chat_messages.append({"role": "user", "content": user_content})

    # Ensure we have at least one user message (beyond system).
    if len(chat_messages) <= 1:
        emit_fn({"type": "done", "tokens_prompt": 0, "tokens_completion": 0,
                 "cost_usd": 0.0, "cited_sources": [], "retrieved_sources": retrieved_sources,
                 "prompt_id": prompt.id})
        return

    # -- Stream LLM response --
    print(f"[server-chat] streaming: model={model!r}, "
          f"history_msgs={len(history_messages)}, use_cache={use_cache}",
          file=sys.stderr)

    client = get_client()

    answer_parts: list[str] = []
    try:
        stream = client.chat.completions.create(
            model=model,
            messages=chat_messages,
            max_tokens=8192,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
    except (APITimeoutError, APIStatusError, APIError) as e:
        kind = "timeout" if isinstance(e, APITimeoutError) else f"http_{getattr(e, 'status_code', 0)}"
        _emit_alert(str(e), model, 1, kind)
        raise

    tokens_prompt = 0
    tokens_completion = 0
    cached_tokens = 0
    cache_created_tokens = 0

    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            text = chunk.choices[0].delta.content
            answer_parts.append(text)
            emit_fn({"type": "delta", "content": text})
        if chunk.usage:
            tokens_prompt = chunk.usage.prompt_tokens or 0
            tokens_completion = chunk.usage.completion_tokens or 0
            raw = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else {}
            det = getattr(chunk.usage, "prompt_tokens_details", None)
            if det:
                cached_tokens = getattr(det, "cached_tokens", 0) or 0
                cache_created_tokens = getattr(det, "cache_creation_tokens", 0) or 0
            if not cached_tokens:
                cached_tokens = raw.get("cache_read_input_tokens", 0) or 0
            if not cache_created_tokens:
                cache_created_tokens = raw.get("cache_creation_input_tokens", 0) or 0

    full_answer = "".join(answer_parts)

    # -- Extract citations from the completed answer --
    search_paths = {s["path"] for s in retrieved_sources}
    cited_sources = _extract_citations(full_answer, search_paths)

    # Update adaptive cache state.
    if use_cache:
        _update_cache_state(cached_tokens, cache_created_tokens)

    cost = _estimate_cost(model, tokens_prompt, tokens_completion, cached_tokens)

    print(f"[server-chat] done: prompt={tokens_prompt}, completion={tokens_completion}, "
          f"cached={cached_tokens}, cost=${cost:.6f}, "
          f"cited={len(cited_sources)}, retrieved={len(retrieved_sources)}",
          file=sys.stderr)

    emit_fn({
        "type": "done",
        "tokens_prompt": tokens_prompt,
        "tokens_completion": tokens_completion,
        "cached_tokens": cached_tokens,
        "cost_usd": round(cost, 6),
        "cited_sources": cited_sources,
        "retrieved_sources": retrieved_sources,
        "prompt_id": prompt.id,
    })


def run_server_chat_http(input_data: dict, emit_fn) -> None:
    """HTTP server entry point for chat. Takes parsed input and an emit callback.

    Args:
        input_data: Parsed JSON input dict (same structure as stdin bridge).
        emit_fn: Callable that accepts a dict event to emit as SSE.
    """
    _run_chat_core(input_data, emit_fn)


class ChatCommand(StreamingCommand):
    """Streaming chat command using the StreamingCommand base class."""

    def execute(self, input_data: dict, emit: Callable) -> None:
        _run_chat_core(input_data, emit)


def run_server_chat() -> None:
    """Entry point for the server-chat bridge command.

    Reads JSON from stdin, retrieves chunks, builds context, and streams
    the Anthropic LLM response as JSON-line events to stdout.
    """
    ChatCommand().run()
