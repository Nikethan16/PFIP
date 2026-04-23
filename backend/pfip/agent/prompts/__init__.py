"""Prompt loader — reads markdown files from this directory.

Prompts live in Markdown files (not Python string literals) so non-devs
can tune the voice without redeploying code. ``load(name)`` returns the
raw text; the agent graph wraps it with sanitized retrieved content.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def load(name: str) -> str:
    """Load a prompt Markdown file by base name (no extension).

    Raises FileNotFoundError if the prompt is missing — which is a config
    bug, not a runtime condition, so we don't want it silently masked.
    """
    path = _DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text(encoding="utf-8")


__all__ = ["load"]
