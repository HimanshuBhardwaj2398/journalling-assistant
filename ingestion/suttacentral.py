"""SuttaCentral ingestion source.

SuttaCentral serves its texts from a public API, not static HTML pages, so the
generic ``URLParser`` (a plain ``requests.get`` + ``markdownify``) only sees the
empty SPA shell. This module fetches text via the API and, for modern *segmented*
(bilara) translations such as Bhikkhu Sujato's, reconstructs the site's own HTML
from the parallel ``html_text`` + ``translation_text`` layers so it markdownifies
into the clean header-delimited form the chunker expects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from core.exceptions import ParsingError

_SC_URL = re.compile(r"^https?://(www\.)?suttacentral\.net/", re.IGNORECASE)
_SC_SHORTHAND = re.compile(r"^sc:", re.IGNORECASE)


def bilara_to_html(bilara: dict, *, use: str = "translation_text") -> str:
    """Reconstruct a sutta's HTML from SuttaCentral bilara layers.

    Each segment id in ``keys_order`` maps to an ``html_text`` template containing
    a ``{}`` placeholder; the placeholder is filled with the corresponding text
    from the requested layer (``translation_text`` for English, ``root_text`` for
    Pali). Segments absent from ``html_text`` fall back to a bare ``{}`` so their
    text is still emitted; segments absent from the text layer render empty.

    Args:
        bilara: Parsed ``/api/bilarasuttas`` response.
        use: Which text layer to substitute (default English translation).

    Returns:
        The reconstructed HTML string, segments concatenated in ``keys_order``.
    """
    text = bilara.get(use, {})
    html = bilara.get("html_text", {})
    return "".join(
        html.get(seg_id, "{}").replace("{}", text.get(seg_id, ""))
        for seg_id in bilara["keys_order"]
    )


@dataclass(frozen=True)
class SuttaRef:
    """A resolved reference to a specific translation of a sutta."""

    uid: str
    author: str
    lang: str = "en"


def parse_sutta_ref(source: str) -> SuttaRef:
    """Resolve a SuttaCentral reading URL or ``sc:`` shorthand into a SuttaRef.

    Accepts:
        - ``sc:<uid>/<author>[/<lang>]`` (e.g. ``sc:mn1/sujato``)
        - ``https://suttacentral.net/<uid>/<lang>/<author>`` (the reading URL)

    Raises:
        ParsingError: If the source is not a recognizable SuttaCentral reference.
    """
    if _SC_SHORTHAND.match(source):
        parts = [p for p in source[3:].split("/") if p]
        if len(parts) < 2:
            raise ParsingError(
                f"SuttaCentral shorthand must be 'sc:<uid>/<author>[/<lang>]': {source!r}"
            )
        uid, author = parts[0], parts[1]
        lang = parts[2] if len(parts) > 2 else "en"
        return SuttaRef(uid=uid, author=author, lang=lang)

    if _SC_URL.match(source):
        parts = [p for p in urlparse(source).path.split("/") if p]
        if len(parts) < 3:
            raise ParsingError(
                f"SuttaCentral URL must be '/<uid>/<lang>/<author>': {source!r}"
            )
        uid, lang, author = parts[0], parts[1], parts[2]
        return SuttaRef(uid=uid, author=author, lang=lang)

    raise ParsingError(f"Not a SuttaCentral reference: {source!r}")


class SuttaCentralParser:
    """Parser strategy for SuttaCentral texts (implements the Parser protocol).

    Fetches via the SuttaCentral API and returns markdown. Registered ahead of
    the generic ``URLParser`` so ``suttacentral.net`` URLs route here instead of
    being naively fetched as an (empty) SPA shell.
    """

    def __init__(self, fetch_json: Optional[Callable[[str], dict]] = None):
        """Args:
        fetch_json: Injectable ``url -> parsed JSON`` fetcher (defaults to a real
            HTTP fetcher, wired in the parse step). Tests inject a fake.
        """
        self._fetch_json = fetch_json

    def can_parse(self, source: str) -> bool:
        """True for SuttaCentral reading URLs or ``sc:`` shorthand."""
        return bool(_SC_URL.match(source) or _SC_SHORTHAND.match(source))
