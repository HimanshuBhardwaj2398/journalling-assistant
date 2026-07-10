"""SuttaCentral ingestion source.

SuttaCentral serves its texts from a public API, not static HTML pages, so the
generic ``URLParser`` (a plain ``requests.get`` + ``markdownify``) only sees the
empty SPA shell. This module fetches text via the API and, for modern *segmented*
(bilara) translations such as Bhikkhu Sujato's, reconstructs the site's own HTML
from the parallel ``html_text`` + ``translation_text`` layers so it markdownifies
into the clean header-delimited form the chunker expects. Legacy translations
(e.g. Bhikkhu Bodhi) already carry inline HTML and are converted directly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import urlparse

from markdownify import markdownify as md

from core.exceptions import ParsingError
from core.interfaces import ParseResult

_SC_URL = re.compile(r"^https?://(www\.)?suttacentral\.net/", re.IGNORECASE)
_SC_SHORTHAND = re.compile(r"^sc:", re.IGNORECASE)
_API_BASE = "https://suttacentral.net/api"


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
            raise ParsingError(f"SuttaCentral URL must be '/<uid>/<lang>/<author>': {source!r}")
        uid, lang, author = parts[0], parts[1], parts[2]
        return SuttaRef(uid=uid, author=author, lang=lang)

    raise ParsingError(f"Not a SuttaCentral reference: {source!r}")


def catalog_entries_from_tree(
    paths: list[str], *, lang: str = "en", author: str = "sujato"
) -> list[dict]:
    """Extract sutta catalog entries from bilara-data translation file paths.

    Filters a flat list of repo paths (e.g. from the GitHub git-tree API) to the
    requested translator+language under ``translation/<lang>/<author>/sutta/`` and
    derives each sutta's uid and nikaya. Handles both ``<uid>_translation-...json``
    and plain ``<uid>.json`` filenames, and nested collections (e.g. ``sn/sn1/...``).

    Returns:
        One dict per sutta: ``uid``, ``nikaya``, ``author``, ``lang``, ``reading_url``.
    """
    prefix = f"translation/{lang}/{author}/sutta/"
    entries: list[dict] = []
    for path in paths:
        if not (path.startswith(prefix) and path.endswith(".json")):
            continue
        parts = path[len(prefix) :].split("/")
        nikaya = parts[0]
        uid = parts[-1][: -len(".json")].split("_")[0]
        entries.append(
            {
                "uid": uid,
                "nikaya": nikaya,
                "author": author,
                "lang": lang,
                "reading_url": f"https://suttacentral.net/{uid}/{lang}/{author}",
            }
        )
    return entries


def _default_fetch_json(url: str) -> dict:
    """Real HTTP fetcher for the SuttaCentral API (exercised in live runs, not unit tests)."""
    import requests

    response = requests.get(url, timeout=30, headers={"User-Agent": "meditation-db-ingest/0.1"})
    response.raise_for_status()
    return response.json()


class SuttaCentralParser:
    """Parser strategy for SuttaCentral texts (implements the Parser protocol).

    Fetches via the SuttaCentral API and returns markdown. Registered ahead of
    the generic ``URLParser`` so ``suttacentral.net`` URLs route here instead of
    being naively fetched as an (empty) SPA shell.
    """

    def __init__(self, fetch_json: Optional[Callable[[str], dict]] = None):
        """Args:
        fetch_json: Injectable ``url -> parsed JSON`` fetcher (defaults to a real
            HTTP fetcher). Tests inject a fake to avoid network access.
        """
        self._fetch_json = fetch_json

    def can_parse(self, source: str) -> bool:
        """True for SuttaCentral reading URLs or ``sc:`` shorthand."""
        return bool(_SC_URL.match(source) or _SC_SHORTHAND.match(source))

    def parse(self, source: str) -> ParseResult:
        """Fetch a sutta from the SuttaCentral API and return it as markdown.

        Segmented (bilara) translations are reconstructed from ``html_text`` +
        ``translation_text``; legacy translations use their inline HTML directly.

        Raises:
            ParsingError: On an unrecognizable source or empty text content.
        """
        ref = parse_sutta_ref(source)
        fetch = self._fetch_json or _default_fetch_json

        suttas = fetch(f"{_API_BASE}/suttas/{ref.uid}/{ref.author}?lang={ref.lang}")
        segmented = bool(suttas.get("segmented"))
        if segmented:
            bilara = fetch(f"{_API_BASE}/bilarasuttas/{ref.uid}/{ref.author}?lang={ref.lang}")
            html = bilara_to_html(bilara)
        else:
            html = (suttas.get("translation") or {}).get("text") or ""

        markdown = md(html, heading_style="ATX").strip()
        if not markdown:
            raise ParsingError(f"No text content returned for {source!r}")

        suttaplex = suttas.get("suttaplex") or {}
        title = (
            self._first_h1(markdown)
            or suttaplex.get("original_title")
            or suttaplex.get("translated_title")
            or ref.uid
        )
        return ParseResult(
            content=markdown,
            title=title,
            metadata={
                "source": "suttacentral",
                "uid": ref.uid,
                "author_uid": ref.author,
                "lang": ref.lang,
                "segmented": segmented,
                "reading_url": f"https://suttacentral.net/{ref.uid}/{ref.lang}/{ref.author}",
            },
        )

    @staticmethod
    def _first_h1(markdown: str) -> Optional[str]:
        """Return the text of the first level-1 markdown heading, if any."""
        for line in markdown.split("\n")[:40]:
            match = re.match(r"^#\s+(.+)$", line.strip())
            if match:
                return match.group(1).strip()
        return None
