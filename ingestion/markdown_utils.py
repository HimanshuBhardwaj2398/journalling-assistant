"""Shared markdown text helpers for parsers and the chunker."""

import re
from typing import Optional

_H1_PATTERN = re.compile(r"^#\s+(.+)$")


def extract_first_h1(markdown: str, max_lines: int = 20) -> Optional[str]:
    """Return the text of the first level-1 heading within the leading lines.

    Args:
        markdown: Markdown text to scan.
        max_lines: How many leading lines to inspect (titles live near the top;
            scanning further mostly finds section headings of embedded content).

    Returns:
        The heading text, or None if no H1 is found in range.
    """
    for line in markdown.split("\n")[:max_lines]:
        match = _H1_PATTERN.match(line.strip())
        if match:
            return match.group(1).strip()
    return None
