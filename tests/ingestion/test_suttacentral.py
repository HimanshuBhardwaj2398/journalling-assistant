"""Tests for SuttaCentral ingestion: HTML reconstruction, parser, catalog."""

import pytest

from core.exceptions import ParsingError
from ingestion.suttacentral import (
    SuttaCentralParser,
    SuttaRef,
    bilara_to_html,
    parse_sutta_ref,
)


def test_bilara_to_html_substitutes_in_key_order():
    bilara = {
        "keys_order": ["mn1:0.1", "mn1:0.2", "mn1:1.1"],
        "html_text": {
            "mn1:0.1": "<article id='mn1'><header><ul><li class='division'>{}</li></ul></header>",
            "mn1:0.2": "<h1>{}</h1>",
            "mn1:1.1": "<p>{}</p></article>",
        },
        "translation_text": {
            "mn1:0.1": "Middle Discourses",
            "mn1:0.2": "The Root of All Things",
            "mn1:1.1": "So I have heard.",
        },
    }

    html = bilara_to_html(bilara)

    assert "<h1>The Root of All Things</h1>" in html
    assert (
        html.index("Middle Discourses")
        < html.index("The Root of All Things")
        < html.index("So I have heard.")
    )


def test_bilara_to_html_handles_missing_segment_text():
    bilara = {"keys_order": ["x:1"], "html_text": {"x:1": "<p>{}</p>"}, "translation_text": {}}

    assert bilara_to_html(bilara) == "<p></p>"


def test_parse_ref_shorthand():
    assert parse_sutta_ref("sc:mn1/sujato") == SuttaRef(uid="mn1", author="sujato", lang="en")


def test_parse_ref_shorthand_with_explicit_lang():
    assert parse_sutta_ref("sc:mn1/sujato/en") == SuttaRef(uid="mn1", author="sujato", lang="en")


def test_parse_ref_reading_url():
    assert parse_sutta_ref("https://suttacentral.net/mn1/en/sujato") == SuttaRef(
        uid="mn1", author="sujato", lang="en"
    )


def test_parse_ref_reading_url_with_query_is_ignored():
    assert parse_sutta_ref("https://suttacentral.net/sn12.2/en/bodhi?highlight=x") == SuttaRef(
        uid="sn12.2", author="bodhi", lang="en"
    )


def test_parse_ref_invalid_raises():
    with pytest.raises(ParsingError):
        parse_sutta_ref("https://example.com/foo")


def test_can_parse_accepts_suttacentral_url_and_shorthand():
    parser = SuttaCentralParser()

    assert parser.can_parse("https://suttacentral.net/mn1/en/sujato") is True
    assert parser.can_parse("sc:mn1/sujato") is True


def test_can_parse_rejects_other_sources():
    parser = SuttaCentralParser()

    assert parser.can_parse("https://example.com") is False
    assert parser.can_parse("/path/to/doc.pdf") is False
