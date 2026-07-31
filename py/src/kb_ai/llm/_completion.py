"""Non-streaming completion: completion, completion_json, and _completion_inner.

This module reads context via get_context() from kb_ai._context (contextvars-based).
All threading.local() reads have been migrated to the unified ThreadContext.
"""

from __future__ import annotations

import json
import sys
import time

from openai import APIStatusError, APITimeoutError

from kb_ai._errors import (
    DeadlineExceededError,
    LLMTimeoutError,
    OutputTruncatedError,
    PipelineCancelledError,
    PromptTooLargeError,
)

from ._cache import AdaptiveCacheState, enable_prompt_caching
from ._cost_record import record_cost
from ._infra import (
    MAX_PROMPT_CHARS,
    _ALERT_CALLER,
    _MAX_TOKENS_CEILING,
    _TIMEOUT_BACKOFF_BASE,
    _TIMEOUT_RETRIES,
    count_prompt_chars,
    emit_alert,
    parse_usage,
)

# Adaptive cache state — module-level singleton
_CACHE_MISS_THRESHOLD = 10
_cache_state = AdaptiveCacheState(miss_threshold=_CACHE_MISS_THRESHOLD)
_cache_lock = _cache_state._lock  # tests access this directly


def _completion_inner(model: str, messages: list[dict], temperature: float = 0,
                      max_tokens: int = 4096, cache: bool = False,
                      response_format: dict | None = None) -> tuple[str, str | None]:
    """Low-level completion call. Returns (text, finish_reason).

    Retries up to _TIMEOUT_RETRIES times on timeout with exponential backoff.

    All context reads use get_context() from kb_ai._context (contextvars).
    """
    from kb_ai._context import get_context
    from . import get_client, tracker

    ctx = get_context()

    use_cache = _cache_state.should_use_cache(cache)

    client = get_client()
    override = ctx.call_timeout
    if override is not None:
        client = client.with_options(timeout=override)
    msgs = enable_prompt_caching(messages) if use_cache else messages

    kwargs: dict = {
        "model": model,
        "messages": msgs,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format

    base_url = str(client.base_url).rstrip("/")
    op = ctx.phase
    content_hash = ctx.content_hash
    prompt_chars = count_prompt_chars(messages)
    if prompt_chars > MAX_PROMPT_CHARS:
        emit_alert(
            f"op={op} model={model} prompt_chars={prompt_chars} limit={MAX_PROMPT_CHARS}",
            model, 0, "prompt_too_large",
            content_hash=content_hash, caller=_ALERT_CALLER,
        )
        raise PromptTooLargeError(
            f"prompt_too_large: {prompt_chars} chars (limit {MAX_PROMPT_CHARS}), "
            f"op={op} model={model}"
        )

    t0 = time.monotonic()
    for attempt in range(_TIMEOUT_RETRIES + 1):
        cancel_ev = ctx.cancel_event
        if cancel_ev is not None and cancel_ev.is_set():
            raise PipelineCancelledError("pipeline cancelled: client disconnected")
        try:
            response = client.chat.completions.create(**kwargs)
            break
        except (APITimeoutError, APIStatusError) as e:
            elapsed = round(time.monotonic() - t0, 1)
            # Must not shadow ctx -- the retry path below still reads
            # ctx.deadline_abs / ctx.cancel_event, and record_cost closes over it.
            detail = (f"op={op} model={model} attempt={attempt + 1}/{_TIMEOUT_RETRIES + 1} "
                      f"prompt_chars={prompt_chars} elapsed={elapsed}s")

            is_timeout = isinstance(e, APITimeoutError)
            is_retryable_gateway = (
                isinstance(e, APIStatusError) and e.status_code in (502, 503, 504)
            )
            can_retry = attempt < _TIMEOUT_RETRIES and (is_timeout or is_retryable_gateway)

            kind = "api_timeout_error" if is_timeout else (
                f"gateway_{e.status_code}" if is_retryable_gateway else f"http_{e.status_code}"
            )
            emit_alert(f"{detail} | {e}", model, attempt + 1, kind,
                       content_hash=content_hash, caller=_ALERT_CALLER)

            if not can_retry:
                if is_timeout:
                    raise LLMTimeoutError(
                        f"api_timeout_error: op={op} model={model} attempts={attempt + 1} "
                        f"prompt_chars={prompt_chars} elapsed={elapsed}s base_url={base_url}"
                    )
                raise

            wait = _TIMEOUT_BACKOFF_BASE * (2 ** attempt)
            if (dl := ctx.deadline_abs) and time.monotonic() + wait + 60 > dl:
                label = "timeout" if is_timeout else f"gateway_{e.status_code}"
                print(f"  [{label}] {detail}, deadline_too_close, raising", file=sys.stderr)
                raise DeadlineExceededError(
                    f"deadline_too_close: op={op} model={model} attempts={attempt + 1} "
                    f"prompt_chars={prompt_chars} elapsed={elapsed}s base_url={base_url}"
                )
            label = "timeout" if is_timeout else f"gateway_{e.status_code}"
            print(f"  [{label}] {detail}, retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)

    # Parse usage and record cost
    usage_info = parse_usage(response)
    if response.usage:
        record_cost(
            model=model,
            usage=usage_info,
            duration_s=round(time.monotonic() - t0, 3),
            attempts=attempt + 1,
            global_tracker=tracker,
            get_phase_context=lambda: ctx.phase,
            get_content_hash_context=lambda: ctx.content_hash,
            get_call_emit=lambda: ctx.call_emit,
            get_request_tracker=lambda: ctx.request_tracker,
        )

    # Adaptive cache: record result
    if use_cache:
        _cache_state.record_result(usage_info.cached_tokens, usage_info.cache_created_tokens)

    finish_reason = response.choices[0].finish_reason
    text = response.choices[0].message.content or ""
    return text.strip(), finish_reason


def completion(model: str, messages: list[dict], temperature: float = 0, max_tokens: int = 4096,
               cache: bool = False, response_format: dict | None = None) -> str:
    """Simple completion helper. Returns the response text. Tracks cost.

    Auto-retries with doubled max_tokens on truncation (up to 65536).

    Args:
        cache: Enable Anthropic prompt caching on system messages.
               Use True for sequential calls sharing the same system prefix.
               Use False for parallel calls (cache writes cost 25% extra with no reads).
               Auto-disables after consecutive cache misses.
        response_format: Optional OpenAI response_format spec, e.g.
                         {"type": "json_object"} to enforce JSON output.
    """
    from kb_ai._context import get_context

    current_max = max_tokens

    while True:
        text, finish_reason = _completion_inner(
            model=model, messages=messages, temperature=temperature,
            max_tokens=current_max, cache=cache,
            response_format=response_format,
        )

        if finish_reason != "length":
            return text

        next_max = min(current_max * 2, _MAX_TOKENS_CEILING)
        if next_max == current_max:
            raise OutputTruncatedError(
                f"LLM output truncated at ceiling (max_tokens={current_max}). "
                f"Reduce input size."
            )
        if (dl := get_context().deadline_abs) and time.monotonic() + 60 > dl:
            raise DeadlineExceededError(
                f"LLM output truncated (max_tokens={current_max}) but deadline_too_close to retry."
            )
        print(f"  [truncated] max_tokens={current_max} hit, retrying with {next_max}",
              file=sys.stderr)
        current_max = next_max




def completion_json(model: str, messages: list[dict], **kwargs) -> dict:
    """Call completion and parse the result as JSON, with json_repair fallback.

    Strips markdown code fences, then attempts json.loads. On parse failure, uses
    json_repair for heuristic fix (handles unescaped quotes, missing commas, trailing
    commas, stray control chars). No retry -- LLM JSON errors are deterministic for a
    given prompt, so retrying wastes money without improving results.

    Note: we intentionally do NOT enable response_format={"type": "json_object"} here.
    Our extract/classify prompts ask the model to reason in text first, then emit JSON;
    Claude's JSON mode (via LiteLLM prefill of "{") short-circuits that reasoning and
    returns "{}". Repair-on-failure gives us robustness without breaking the prompt.
    """
    text = completion(model=model, messages=messages, **kwargs).strip()

    # Strip markdown fencing if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        # Heuristic repair -- handles common LLM mistakes that deterministically
        # fail json.loads (missing commas, unescaped quotes, trailing commas).
        try:
            from json_repair import repair_json
            repaired = repair_json(text, return_objects=True)
        except Exception:
            raise e

        if isinstance(repaired, dict):
            print(f"  [json-repair] fixed: {e}", file=sys.stderr)
            return repaired
        raise e
