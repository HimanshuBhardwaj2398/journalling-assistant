"""Tests for the shared first-H1 extraction helper (replaces 4 copies)."""

from ingestion.markdown_utils import extract_first_h1


def test_extracts_first_h1():
    assert extract_first_h1("intro text\n# The Title\n## A Section") == "The Title"


def test_returns_none_when_no_h1():
    assert extract_first_h1("## only a subsection\nbody text") is None


def test_h2_is_not_mistaken_for_h1():
    assert extract_first_h1("## Not This\n# This One") == "This One"


def test_respects_max_lines():
    text = "\n" * 30 + "# Late Title"

    assert extract_first_h1(text, max_lines=10) is None
    assert extract_first_h1(text, max_lines=40) == "Late Title"
