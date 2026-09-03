"""Non-streaming completion: completion, completion_json, and _completion_inner.

This module reads context via get_context() from kb_ai._context (contextvars-based).
All threading.local() reads have been migrated to the unified ThreadContext.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time

from openai import APIStatusError, APITimeoutError

from kb_ai._errors import (
    DeadlineExceededError,
    EmptyCompletionError,
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

# --- Truncation matching / sizing constants --------------------------------
_TOKENS_PER_CHAR = 0.75  # calibrated for the replay corpus's mixed zh/en
                         # markdown; errs high (~3x) for pure English prose,
                         # which is acceptable: billing is per generated
                         # token, and under-sizing costs a restart.
_REASONING_HEADROOM_TOKENS = 16384  # budget for reasoning-style models whose
                                    # thinking tokens count against max_tokens
                                    # but never appear in the text. Round C
                                    # measured the burn at 8-15K per call;
                                    # 8192 sat at the bottom of that range, so
                                    # ~half the sized calls still truncated --
                                    # and under-granting pays twice (a restart
                                    # discards, a continuation re-reasons)
                                    # while over-granting is free (billing is
                                    # per generated token, not per cap).

# Gateways spell the length-cut finish_reason differently (OpenAI "length",
# LiteLLM/vLLM routes "max_tokens", Anthropic-style "max_output_tokens", each
# in either case). Set-based case-insensitive matching closes the leak where a
# variant string bypassed the truncation ladder and returned mangled text.
_TRUNCATION_FINISH_REASONS = {"length", "max_tokens", "max_output_tokens"}

# Sent verbatim as the user message of every continuation round (used by the
# continuation branch; part of the raw-text seam contract, not free-form text).
_CONTINUATION_USER = (
    "Continue exactly where the previous message stopped. "
    "Do not repeat text already written, do not apologize, do not "
    "add commentary — output only the continuation."
)

# At most this many continuation rounds before OutputTruncatedError.
_CONTINUATION_MAX = 3

# --- Reasoning-effort passthrough -------------------------------------------
# Operator knob, process-wide by design: when KB_AI_REASONING_EFFORT is set
# (e.g. "low"), every request carries reasoning_effort so reasoning-style
# models spend fewer thinking tokens. A gateway that does not support the
# param answers 400; the first such refusal alerts, retries the attempt once
# without the param, and flips the module-level flag below so it is never
# sent again this process. Default unset = zero behavior change.
_REASONING_EFFORT_ENV = "KB_AI_REASONING_EFFORT"
_reasoning_effort_disabled = False


def _is_truncated(finish_reason: str | None) -> bool:
    """True when finish_reason indicates the output was cut by the token cap."""
    return isinstance(finish_reason, str) and finish_reason.lower() in _TRUNCATION_FINISH_REASONS


def estimate_max_tokens(expected_output_chars: int, *, minimum: int = 4096,
                        ceiling: int = _MAX_TOKENS_CEILING,
                        headroom: int = _REASONING_HEADROOM_TOKENS) -> int:
    """Size the first max_tokens rung from an expected output length in chars.

    ceil(chars * _TOKENS_PER_CHAR) + headroom, clamped to [minimum, ceiling].
    Over-provisioning is free (billing is per generated token, not per cap);
    under-sizing costs a restart or a continuation round-trip.
    """
    estimated = math.ceil(expected_output_chars * _TOKENS_PER_CHAR) + headroom
    return max(minimum, min(estimated, ceiling))


def _dedup_overlap(acc: str, chunk: str, max_chars: int = 256) -> str:
    """Concatenate RAW strings, dropping the longest suffix of `acc` that equals
    a prefix of `chunk` (bounded scan) — removes seam repetition only. It never
    inserts or restores separator whitespace (that is the raw-text contract's job).
    """
    limit = min(len(acc), len(chunk), max_chars)
    for overlap in range(limit, 0, -1):
        if acc[-overlap:] == chunk[:overlap]:
            return acc + chunk[overlap:]
    return acc + chunk


def _completion_inner(model: str, messages: list[dict], temperature: float = 0,
                      max_tokens: int = 4096, cache: bool = False,
                      response_format: dict | None = None,
                      reasoning_effort: str | None = None) -> tuple[str, str | None, int]:
    """Low-level completion call. Returns (raw_text, finish_reason, completion_tokens).

    - raw_text is UNSTRIPPED: the single terminal .strip() lives at completion()'s
      return boundary, so continuation seams keep the whitespace/indentation that
      separated chunk N from chunk N+1.
    - completion_tokens is usage_info.completion_tokens (includes reasoning
      tokens never present in the text — the only correct number for the
      discarded-tokens alert); parse_usage already falls back to 0 when the
      response carries no usage.
    - reasoning_effort is added to the request kwargs only when resolved
      non-None: the explicit argument wins, then the KB_AI_REASONING_EFFORT
      env knob, and the module-level disable flag (set on the first 400
      refusal) suppresses both.

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
    global _reasoning_effort_disabled
    if not _reasoning_effort_disabled:
        effort = reasoning_effort or os.environ.get(_REASONING_EFFORT_ENV) or None
        if effort is not None:
            kwargs["reasoning_effort"] = effort

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
    attempt = 0
    while True:
        cancel_ev = ctx.cancel_event
        if cancel_ev is not None and cancel_ev.is_set():
            raise PipelineCancelledError("pipeline cancelled: client disconnected")
        try:
            response = client.chat.completions.create(**kwargs)
            break
        except (APITimeoutError, APIStatusError) as e:
            # A 400 while reasoning_effort was sent is the gateway rejecting
            # the param itself, not the request: alert, strip it, retry the
            # same attempt once, and never send it again in this process. It
            # fires at most once (the flag plus the kwargs deletion below).
            if (isinstance(e, APIStatusError) and e.status_code == 400
                    and "reasoning_effort" in kwargs):
                emit_alert(
                    f"op={op} model={model} reasoning_effort={kwargs['reasoning_effort']} "
                    f"unsupported, retrying without it",
                    model, attempt + 1, "reasoning_effort_unsupported",
                    content_hash=content_hash, caller=_ALERT_CALLER,
                )
                del kwargs["reasoning_effort"]
                _reasoning_effort_disabled = True
                continue
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
            attempt += 1

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
    return text, finish_reason, usage_info.completion_tokens


def completion(model: str, messages: list[dict], temperature: float = 0, max_tokens: int = 4096,
               cache: bool = False, response_format: dict | None = None, *,
               continue_on_length: bool = False) -> str:
    """Simple completion helper. Returns the response text, .strip()ed exactly
    once at this return boundary — every caller receives stripped text in both
    truncation modes, so non-opting callers stay byte-identical. Tracks cost.

    Truncation policy (finish_reason matched case-insensitively against
    _TRUNCATION_FINISH_REASONS):
    - Default (restart ladder): discard the truncated output and re-call with
      doubled max_tokens, up to _MAX_TOKENS_CEILING, then raise
      OutputTruncatedError. Each restart emits an [LLM-WARN]
      output_truncated_restart alert carrying discarded_tokens=N (N = the
      discarded call's completion_tokens; falls back to the cap that was hit
      when usage was absent).
    - continue_on_length=True: keep the truncated partial as an assistant
      message plus _CONTINUATION_USER and re-call for the continuation,
      concatenating raw chunks with _dedup_overlap. Each round grants the
      same size as the previous one, bounded by cumulative granted-accounting
      against _MAX_TOKENS_CEILING (grant <= 0 raises OutputTruncatedError
      immediately); at most _CONTINUATION_MAX continuations, then
      OutputTruncatedError. Each round emits an [LLM-WARN]
      output_truncated_continue alert carrying discarded_tokens=0
      kept_tokens=N (N = the kept call's completion_tokens).

    Both paths keep the 60s deadline guard per round and the byte-stable stderr
    line formats the .bench/ replay regexes depend on:
        restart:  '  [truncated] max_tokens={cap} hit, retrying with {next}'
        continue: '  [truncated] max_tokens={cap} hit, continuing with {grant}'

    Args:
        cache: Enable Anthropic prompt caching on system messages.
               Use True for sequential calls sharing the same system prefix.
               Use False for parallel calls (cache writes cost 25% extra with no reads).
               Auto-disables after consecutive cache misses.
        response_format: Optional OpenAI response_format spec, e.g.
                         {"type": "json_object"} to enforce JSON output.
        continue_on_length: Opt in to raw-text continuation of truncated
                         outputs — keep the partial instead of discarding it
                         (plain-text callers only; completion_json refuses).
    """
    from kb_ai._context import get_context

    current_max = max_tokens

    text, finish_reason, completion_tokens = _completion_inner(
        model=model, messages=messages, temperature=temperature,
        max_tokens=current_max, cache=cache,
        response_format=response_format,
    )

    if not _is_truncated(finish_reason) and not text:
        # Reasoning-style models occasionally stop with the whole answer in
        # the reasoning channel and an empty content body (measured 3/3 on
        # one document against deepseek-v4-flash: finish=stop, content="").
        # An empty body is never a valid answer for any kb-ai caller, so
        # retry once; the retried response then flows through the normal
        # truncated/non-truncated handling below.
        ctx = get_context()
        emit_alert(
            f"op={ctx.phase} model={model} max_tokens={current_max} "
            f"finish_reason={finish_reason!r}",
            model, 1, "empty_completion",
            content_hash=ctx.content_hash, caller=_ALERT_CALLER,
        )
        print(f"  [empty-completion] finish_reason={finish_reason!r}, retrying once",
              file=sys.stderr)
        text, finish_reason, completion_tokens = _completion_inner(
            model=model, messages=messages, temperature=temperature,
            max_tokens=current_max, cache=cache,
            response_format=response_format,
        )

    if not _is_truncated(finish_reason):
        if not text:
            raise EmptyCompletionError(
                f"LLM returned an empty body twice (finish_reason="
                f"{finish_reason!r}, max_tokens={current_max})."
            )
        return text.strip()

    if continue_on_length:
        # Continuation mode: the truncated partial is kept work, not waste.
        # Appending it raw (never stripped at a seam) plus _CONTINUATION_USER
        # shows the model exactly where it stopped, including trailing
        # whitespace — the raw-text seam contract.
        acc = text
        granted = current_max  # the first round's cap counts against the ceiling
        continuations = 0
        while True:
            grant = min(current_max, _MAX_TOKENS_CEILING - granted)
            if grant <= 0:
                raise OutputTruncatedError(
                    f"LLM output truncated at ceiling (max_tokens={current_max}, "
                    f"granted={granted}). Reduce input size."
                )
            ctx = get_context()
            if (dl := ctx.deadline_abs) and time.monotonic() + 60 > dl:
                raise DeadlineExceededError(
                    f"LLM output truncated (max_tokens={current_max}) but "
                    f"deadline_too_close to continue."
                )
            if continuations >= _CONTINUATION_MAX:
                raise OutputTruncatedError(
                    f"LLM output still truncated after {continuations} continuations "
                    f"(max_tokens={current_max}). Reduce input size."
                )
            # Nothing was discarded; kept_tokens reports the banked generation
            # (completion_tokens includes reasoning tokens the text never shows).
            emit_alert(
                f"op={ctx.phase} model={model} max_tokens={current_max} "
                f"discarded_tokens=0 kept_tokens={completion_tokens}",
                model, 0, "output_truncated_continue",
                content_hash=ctx.content_hash, caller=_ALERT_CALLER,
            )
            print(f"  [truncated] max_tokens={current_max} hit, continuing with {grant}",
                  file=sys.stderr)
            granted += grant
            continuations += 1
            continuation_messages = messages + [
                {"role": "assistant", "content": acc},
                {"role": "user", "content": _CONTINUATION_USER},
            ]
            chunk, finish_reason, completion_tokens = _completion_inner(
                model=model, messages=continuation_messages,
                temperature=temperature, max_tokens=grant, cache=cache,
                response_format=response_format,
            )
            acc = _dedup_overlap(acc, chunk)
            if not _is_truncated(finish_reason):
                return acc.strip()  # the single terminal strip, on the assembled text
            current_max = grant

    # Default restart ladder: discard the truncated output, double the cap.
    while _is_truncated(finish_reason):
        ctx = get_context()
        next_max = min(current_max * 2, _MAX_TOKENS_CEILING)
        if next_max == current_max:
            raise OutputTruncatedError(
                f"LLM output truncated at ceiling (max_tokens={current_max}). "
                f"Reduce input size."
            )
        if (dl := ctx.deadline_abs) and time.monotonic() + 60 > dl:
            raise DeadlineExceededError(
                f"LLM output truncated (max_tokens={current_max}) but deadline_too_close to retry."
            )
        # completion_tokens includes reasoning tokens the text never shows — the
        # correct measure of discarded generation. It parses to 0 when usage is
        # absent; fall back to the cap that was hit (an upper-bound estimate).
        discarded = completion_tokens if completion_tokens > 0 else current_max
        emit_alert(
            f"op={ctx.phase} model={model} max_tokens={current_max} "
            f"discarded_tokens={discarded} retrying_with={next_max}",
            model, 0, "output_truncated_restart",
            content_hash=ctx.content_hash, caller=_ALERT_CALLER,
        )
        print(f"  [truncated] max_tokens={current_max} hit, retrying with {next_max}",
              file=sys.stderr)
        current_max = next_max
        text, finish_reason, completion_tokens = _completion_inner(
            model=model, messages=messages, temperature=temperature,
            max_tokens=current_max, cache=cache,
            response_format=response_format,
        )
    return text.strip()


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

    Raises ValueError when kwargs['continue_on_length'] is truthy: JSON cannot be
    stitched mid-object, so a caller requesting JSON continuation has a design
    error worth surfacing rather than silently ignoring.
    """
    if kwargs.get("continue_on_length"):
        raise ValueError(
            "completion_json does not accept continue_on_length=True: JSON output "
            "cannot be stitched mid-object. Use completion() for raw-text continuation."
        )
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
