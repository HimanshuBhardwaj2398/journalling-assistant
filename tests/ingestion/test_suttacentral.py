"""Tests for SuttaCentral ingestion: HTML reconstruction, parser, catalog."""

from ingestion.suttacentral import bilara_to_html


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
