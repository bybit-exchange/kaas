"""Prompt registry package — file-based prompt loading for open-source KaaS."""
from __future__ import annotations

import os

from kb_ai.prompts.registry import (
    NoActivePromptError,
    PromptError,
    PromptInstance,
    PromptNotFoundError,
    PromptRegistry,
)

__all__ = [
    "PromptRegistry",
    "PromptInstance",
    "PromptError",
    "NoActivePromptError",
    "PromptNotFoundError",
    "default_registry",
]

_registry: PromptRegistry | None = None


def default_registry() -> PromptRegistry:
    """Build a file-based registry from the defaults directory or KAAS_PROMPTS_DIR env var."""
    global _registry
    if _registry is None:
        prompts_dir = os.environ.get("KAAS_PROMPTS_DIR", "")
        if not prompts_dir:
            prompts_dir = os.path.join(os.path.dirname(__file__), "defaults")
        _registry = PromptRegistry(prompts_dir)
    return _registry
