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


class _FakeFetcher:
    """Returns a canned JSON payload for the first URL substring that matches."""

    def __init__(self, by_substring: dict):
        self._by_substring = by_substring
        self.calls: list[str] = []

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        for substring, payload in self._by_substring.items():
            if substring in url:
                return payload
        raise AssertionError(f"unexpected URL fetched: {url}")


def test_parse_segmented_reconstructs_markdown_and_metadata():
    suttas = {"segmented": True, "suttaplex": {"original_title": "Mūlapariyāya"}}
    bilara = {
        "keys_order": ["mn1:0.2", "mn1:1.1"],
        "html_text": {"mn1:0.2": "<h1>{}</h1>", "mn1:1.1": "<p>{}</p>"},
        "translation_text": {
            "mn1:0.2": "The Root of All Things",
            "mn1:1.1": "So I have heard.",
        },
    }
    fetch = _FakeFetcher(
        {"/api/suttas/mn1/sujato": suttas, "/api/bilarasuttas/mn1/sujato": bilara}
    )

    result = SuttaCentralParser(fetch_json=fetch).parse("sc:mn1/sujato")

    assert "# The Root of All Things" in result.content
    assert "So I have heard." in result.content
    assert result.metadata["uid"] == "mn1"
    assert result.metadata["author_uid"] == "sujato"
    assert result.metadata["segmented"] is True
    assert result.metadata["source"] == "suttacentral"


def test_parse_legacy_uses_inline_translation_html():
    suttas = {
        "segmented": False,
        "translation": {
            "text": "<article><h1>The Root of All Things</h1><p>So I have heard.</p></article>"
        },
    }
    fetch = _FakeFetcher({"/api/suttas/mn1/bodhi": suttas})

    result = SuttaCentralParser(fetch_json=fetch).parse("sc:mn1/bodhi")

    assert "# The Root of All Things" in result.content
    assert "So I have heard." in result.content
    assert result.metadata["segmented"] is False
    assert result.metadata["author_uid"] == "bodhi"


def test_factory_routes_suttacentral_ahead_of_urlparser():
    from ingestion.parsing import ParserFactory, URLParser

    factory = ParserFactory()

    assert isinstance(
        factory.get_parser("https://suttacentral.net/mn1/en/sujato"), SuttaCentralParser
    )
    assert isinstance(factory.get_parser("https://example.com/article"), URLParser)


def test_catalog_entries_from_tree_extracts_uid_nikaya_and_reading_url():
    from ingestion.suttacentral import catalog_entries_from_tree

    paths = [
        "translation/en/sujato/sutta/mn/mn1_translation-en-sujato.json",
        "translation/en/sujato/sutta/sn/sn1/sn1.1_translation-en-sujato.json",
        "translation/en/sujato/sutta/dn/dn1_translation-en-sujato.json",
        "root/pli/ms/sutta/mn/mn1_root-pli-ms.json",  # different layer -> ignored
        "translation/de/sabbamitta/sutta/mn/mn1_translation-de-sabbamitta.json",  # other lang/author
        "translation/en/sujato/sutta/mn/_index.json.bak",  # not .json -> ignored
    ]

    entries = catalog_entries_from_tree(paths, lang="en", author="sujato")
    by_uid = {e["uid"]: e for e in entries}

    assert set(by_uid) == {"mn1", "sn1.1", "dn1"}
    assert by_uid["sn1.1"]["nikaya"] == "sn"
    assert by_uid["mn1"]["reading_url"] == "https://suttacentral.net/mn1/en/sujato"
    assert by_uid["dn1"]["author"] == "sujato"


def test_catalog_entries_from_tree_handles_plain_uid_filenames():
    from ingestion.suttacentral import catalog_entries_from_tree

    entries = catalog_entries_from_tree(
        ["translation/en/sujato/sutta/mn/mn1.json"], lang="en", author="sujato"
    )

    assert entries[0]["uid"] == "mn1"


def test_catalog_crawl_collects_entries_across_nikayas():
    from ingestion.suttacentral import SuttaCentralCatalog

    contents = [
        {"name": "mn", "type": "dir", "sha": "shaMN"},
        {"name": "dn", "type": "dir", "sha": "shaDN"},
    ]
    tree_mn = {
        "tree": [
            {"path": "mn1_translation-en-sujato.json", "type": "blob"},
            {"path": "mn2_translation-en-sujato.json", "type": "blob"},
        ]
    }
    tree_dn = {"tree": [{"path": "dn1_translation-en-sujato.json", "type": "blob"}]}
    fetch = _FakeFetcher(
        {
            "/contents/translation/en/sujato/sutta": contents,
            "/git/trees/shaMN": tree_mn,
            "/git/trees/shaDN": tree_dn,
        }
    )

    entries = SuttaCentralCatalog(fetch_json=fetch).crawl(nikayas=("mn", "dn"))

    assert {e["uid"] for e in entries} == {"mn1", "mn2", "dn1"}
    assert {e["nikaya"] for e in entries} == {"mn", "dn"}


def test_nikaya_tags_code_pali_and_english():
    from ingestion.suttacentral import nikaya_tags

    tags = nikaya_tags("mn1")

    assert tags["nikaya"] == "mn"
    assert tags["nikaya_name"] == "majjhima_nikaya"
    assert tags["nikaya_english"] == "middle_discourses"
    assert tags["tags"] == [
        "buddhism",
        "pali_canon",
        "sutta",
        "mn",
        "majjhima_nikaya",
        "middle_discourses",
    ]


def test_nikaya_tags_extracts_code_from_complex_uid():
    from ingestion.suttacentral import nikaya_tags

    assert nikaya_tags("sn12.2")["nikaya"] == "sn"
    assert nikaya_tags("an1.1")["nikaya_name"] == "anguttara_nikaya"


def test_nikaya_tags_unknown_nikaya_is_safe():
    from ingestion.suttacentral import nikaya_tags

    tags = nikaya_tags("xyz9")

    assert tags["nikaya"] == "xyz"
    assert "nikaya_name" not in tags
    assert tags["tags"] == ["buddhism", "pali_canon", "sutta", "xyz"]


def test_parse_includes_nikaya_tags_in_metadata():
    suttas = {"segmented": True}
    bilara = {
        "keys_order": ["mn1:0.2"],
        "html_text": {"mn1:0.2": "<h1>{}</h1>"},
        "translation_text": {"mn1:0.2": "The Root of All Things"},
    }
    fetch = _FakeFetcher(
        {"/api/suttas/mn1/sujato": suttas, "/api/bilarasuttas/mn1/sujato": bilara}
    )

    result = SuttaCentralParser(fetch_json=fetch).parse("sc:mn1/sujato")

    assert result.metadata["nikaya"] == "mn"
    assert result.metadata["nikaya_name"] == "majjhima_nikaya"
    assert "majjhima_nikaya" in result.metadata["tags"]
