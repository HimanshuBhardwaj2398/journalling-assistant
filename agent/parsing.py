"""Tolerant JSON extraction from LLM output (fences, surrounding prose)."""

from __future__ import annotations

import json
from typing import Any


def extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output.

    Handles ```json fences and prose before/after the object. Raises
    ValueError (never json.JSONDecodeError) so callers have one error type
    to feed back into a retry prompt.
    """
    cleaned = text.strip()
    if "```" in cleaned:
        # take the largest fenced block if any fence contains a brace
        parts = cleaned.split("```")
        candidates = [p.removeprefix("json").strip() for p in parts if "{" in p]
        if candidates:
            cleaned = max(candidates, key=len)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"No JSON object found in model output: {text[:120]!r}")

    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in model output: {exc}") from exc
