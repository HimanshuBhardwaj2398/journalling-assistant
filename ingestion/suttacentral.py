"""SuttaCentral ingestion source.

SuttaCentral serves its texts from a public API, not static HTML pages, so the
generic ``URLParser`` (a plain ``requests.get`` + ``markdownify``) only sees the
empty SPA shell. This module fetches text via the API and, for modern *segmented*
(bilara) translations such as Bhikkhu Sujato's, reconstructs the site's own HTML
from the parallel ``html_text`` + ``translation_text`` layers so it markdownifies
into the clean header-delimited form the chunker expects.
"""

from __future__ import annotations


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
