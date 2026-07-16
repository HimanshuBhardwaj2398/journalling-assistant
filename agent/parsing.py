"""Tolerant JSON extraction from LLM output (fences, surrounding prose)."""

from __future__ import annotations

import json
from typing import Any, Optional


def extract_json(text: str) -> dict[str, Any]:
    """Extract the first JSON object from model output.

    Prefers ```-fenced blocks: the first fence body containing a brace wins,
    with any leading "json" language tag stripped, so stray braces in
    surrounding prose never compete. Within the chosen text, the object is
    delimited by a string-aware balanced-brace scan from the first "{", so
    braces in trailing prose or inside JSON string values do not extend the
    match.

    Args:
        text: Raw model output, possibly wrapping JSON in code fences
            and/or prose.

    Returns:
        The first JSON object in the output, parsed into a dict.

    Raises:
        ValueError: If no "{" is found, or the extracted candidate is not
            valid JSON. Never raises json.JSONDecodeError, so callers have
            one error type to feed back into a retry prompt.
    """
    cleaned = text.strip()
    if "```" in cleaned:
        # split("```") alternates prose (even indices) and fence bodies
        # (odd indices); only fence bodies may be candidates.
        bodies = cleaned.split("```")[1::2]
        candidates = [b.strip().removeprefix("json") for b in bodies if "{" in b]
        if candidates:
            cleaned = candidates[0]

    start = cleaned.find("{")
    if start == -1:
        raise ValueError(f"No JSON object found in model output: {text[:120]!r}")

    try:
        return json.loads(_first_balanced_object(cleaned, start))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in model output: {exc}") from exc


def parse_structured_with_retry(
    client: Any, messages: list[dict], model_cls: Any
) -> Optional[Any]:
    """One try + one validation-feedback retry against a Pydantic model.

    Shared by the interpreter and the graph nodes (grader). Returns None when
    both attempts fail; callers own the fallback.
    """
    attempt = list(messages)
    for _ in range(2):
        raw = client.complete(attempt, max_tokens=300)
        try:
            return model_cls.model_validate(extract_json(raw))
        except Exception as exc:  # ValueError from extract_json or pydantic ValidationError
            attempt = list(messages) + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": f"Invalid. Error: {exc}. Reply with ONLY the JSON object.",
                },
            ]
    return None


def _first_balanced_object(text: str, start: int) -> str:
    """Return the first balanced ``{...}`` span in ``text`` from ``start``.

    Tracks brace depth, ignoring braces inside JSON strings (honoring
    backslash escapes). If the braces never balance, returns the remainder
    of the text and lets json.loads report the syntax error.

    Args:
        text: Text to scan; ``text[start]`` must be ``"{"``.
        start: Index of the opening brace.

    Returns:
        The substring spanning the first complete object, or ``text[start:]``
        if no closing brace balances it.
    """
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        char = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return text[start:]
