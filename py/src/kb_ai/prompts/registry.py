"""FilePromptRegistry — loads prompt templates from local YAML files.

Each prompt is a YAML file: name.yaml with fields: content, description, variables.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class PromptError(Exception):
    """Base error for prompt registry."""


class NoActivePromptError(PromptError):
    """No prompt found for the requested name."""


class PromptNotFoundError(PromptError):
    """Specific prompt file not found."""


@dataclass
class PromptInstance:
    id: int
    name: str
    version: int
    content: str
    meta: dict[str, Any] = field(default_factory=dict)

    def render(self, **kwargs: Any) -> str:
        """str.format-style substitution. Missing variable → KeyError.
        Extra variables are allowed (forward compatibility)."""
        try:
            return self.content.format(**kwargs)
        except KeyError as e:
            raise KeyError(f"prompt {self.name}#{self.version} missing variable: {e.args[0]}") from e


class PromptRegistry:
    """File-based prompt registry. Loads from a directory of YAML files."""

    def __init__(self, prompts_dir: str):
        self._dir = Path(prompts_dir)
        self._cache: dict[str, PromptInstance] = {}

    def get(self, name: str, **kwargs) -> PromptInstance:
        """Load a prompt by name. kwargs are ignored (compatibility with enterprise API)."""
        if name in self._cache:
            return self._cache[name]
        inst = self._load(name)
        self._cache[name] = inst
        return inst

    def _load(self, name: str) -> PromptInstance:
        # YAML form (structured) takes precedence; .md form holds raw prompt text
        # (used by the extract-stage prompts copied byte-exact from source).
        yaml_path = self._dir / f"{name}.yaml"
        md_path = self._dir / f"{name}.md"

        if yaml_path.exists():
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "content" not in data:
                raise PromptError(f"invalid prompt file (missing 'content'): {yaml_path}")
            return PromptInstance(
                id=0,
                name=name,
                version=data.get("version", 1),
                content=data["content"],
                meta={
                    "description": data.get("description", ""),
                    "variables": data.get("variables", []),
                },
            )

        if md_path.exists():
            return PromptInstance(
                id=0,
                name=name,
                version=1,
                content=md_path.read_text(encoding="utf-8"),
                meta={"description": "", "variables": []},
            )

        raise NoActivePromptError(f"prompt file not found: {yaml_path} or {md_path}")
