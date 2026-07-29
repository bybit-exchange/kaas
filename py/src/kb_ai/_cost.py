"""Cost estimation utilities for LLM calls.

Extracted from llm.py to provide a standalone module for pricing resolution,
cost tracking, and cost estimation.
"""

import sys
import threading
import time
from dataclasses import dataclass, field

# Per-1M-token pricing (cache reads billed at 10% of input price per Anthropic)
PRICING = {
    "claude-opus-4-6":   {"input": 5.0,  "output": 25.0},
    "claude-sonnet-4-6": {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":  {"input": 1.0,  "output": 5.0},
}


def resolve_pricing(model: str) -> dict | None:
    """Resolve pricing dict for a given model name.

    Supports exact match, prefix match, and substring fallback for routed model
    names (e.g. "ai.kaas.chat.bedrock.claude-sonnet").

    Returns:
        Pricing dict with "input" and "output" keys (per-1M-token), or None.
    """
    p = PRICING.get(model)
    if p:
        return p
    for key, val in PRICING.items():
        if model.startswith(key.rsplit("-", 1)[0]):
            return val
    # Fallback: substring match for routed model names
    model_lower = model.lower()
    if "opus" in model_lower:
        return PRICING["claude-opus-4-6"]
    if "sonnet" in model_lower:
        return PRICING["claude-sonnet-4-6"]
    if "haiku" in model_lower:
        return PRICING["claude-haiku-4-5"]
    return None


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float:
    """Estimate the cost (USD) for a single LLM call.

    This is the unified entry point for cost estimation. Uses resolve_pricing()
    to find the correct pricing for the model, then applies Anthropic's cache
    pricing model (cache reads at 10% of input price).

    Args:
        model: Model name (exact, prefixed, or routed).
        prompt_tokens: Total prompt/input tokens (including cached).
        completion_tokens: Completion/output tokens.
        cached_tokens: Number of tokens served from cache (subset of prompt_tokens).

    Returns:
        Estimated cost in USD. Returns 0.0 if model pricing is unknown.
    """
    p = resolve_pricing(model)
    if not p:
        return 0.0
    non_cached = prompt_tokens - cached_tokens
    return (non_cached * p["input"] + cached_tokens * p["input"] * 0.1
            + completion_tokens * p["output"]) / 1_000_000


@dataclass
class CostTracker:
    """Thread-safe tracker for accumulating LLM call costs."""

    total_cost: float = 0.0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    calls: int = 0
    details: list = field(default_factory=list)
    store_details: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, model: str, prompt_tokens: int, completion_tokens: int,
               cached_tokens: int = 0, cost: float | None = None, duration_s: float = 0,
               attempts: int = 1) -> float:
        if cost is None:
            cost = estimate_cost(model, prompt_tokens, completion_tokens, cached_tokens)
        with self._lock:
            self.total_cost += cost
            self.total_prompt_tokens += prompt_tokens
            self.total_completion_tokens += completion_tokens
            self.total_cached_tokens += cached_tokens
            self.calls += 1
            if self.store_details:
                detail = {
                    "model": model, "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens, "cached_tokens": cached_tokens,
                    "cost": cost, "duration_s": duration_s,
                }
                if attempts > 1:
                    detail["attempts"] = attempts
                self.details.append(detail)
        return cost

    def snapshot(self) -> dict:
        """Capture current state for computing deltas (includes wall-clock timestamp)."""
        with self._lock:
            return {
                "cost": self.total_cost,
                "prompt": self.total_prompt_tokens,
                "completion": self.total_completion_tokens,
                "cached": self.total_cached_tokens,
                "calls": self.calls,
                "_time": time.monotonic(),
            }

    def delta(self, before: dict) -> dict:
        """Compute delta from a previous snapshot (includes elapsed seconds)."""
        with self._lock:
            return {
                "cost": round(self.total_cost - before["cost"], 6),
                "prompt": self.total_prompt_tokens - before["prompt"],
                "completion": self.total_completion_tokens - before["completion"],
                "cached": self.total_cached_tokens - before["cached"],
                "calls": self.calls - before["calls"],
                "elapsed": round(time.monotonic() - before["_time"], 2),
                "call_details": self.details[before["calls"]:],
            }

    def summary(self) -> dict:
        with self._lock:
            return {
                "total_cost_usd": round(self.total_cost, 6),
                "total_prompt_tokens": self.total_prompt_tokens,
                "total_completion_tokens": self.total_completion_tokens,
                "total_cached_tokens": self.total_cached_tokens,
                "calls": self.calls,
            }

    def summary_with_details(self) -> dict:
        """Return full cost data including call_details (same shape as delta())."""
        with self._lock:
            return {
                "cost": round(self.total_cost, 6),
                "prompt": self.total_prompt_tokens,
                "completion": self.total_completion_tokens,
                "cached": self.total_cached_tokens,
                "calls": self.calls,
                "call_details": list(self.details),
            }

    def print_summary(self, file=sys.stderr):
        s = self.summary()
        cached_part = ""
        if s["total_cached_tokens"] > 0:
            cached_part = f" ({s['total_cached_tokens']} cached)"
        print(f"\n[LLM Cost] ${s['total_cost_usd']:.4f} | "
              f"{s['calls']} calls | "
              f"{s['total_prompt_tokens']} prompt + {s['total_completion_tokens']} completion"
              f"{cached_part} tokens",
              file=file)
