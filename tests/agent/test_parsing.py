"""Tests for tolerant JSON extraction from small-model output."""

import pytest

from agent.parsing import extract_json


def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    text = 'Here you go:\n```json\n{"intent": "corpus_question"}\n```\nDone.'
    assert extract_json(text) == {"intent": "corpus_question"}


def test_prose_around_braces():
    text = 'Sure! {"sufficient": false, "missing_info": "dates"} hope that helps'
    assert extract_json(text)["sufficient"] is False


def test_nested_objects():
    text = '{"a": {"b": [1, 2]}}'
    assert extract_json(text) == {"a": {"b": [1, 2]}}


def test_prose_brace_before_fenced_block():
    # Regression: braces in prose outside the fence must not out-compete
    # the fenced JSON block.
    text = (
        "I considered the {intent} field and several other options "
        "before deciding.\n"
        '```json\n{"intent": "corpus_question"}\n```'
    )
    assert extract_json(text) == {"intent": "corpus_question"}


def test_trailing_prose_with_braces():
    # Regression: a stray "}" in trailing prose must not extend the match.
    text = '{"a": 1}\nNote: replace {placeholder} with a value'
    assert extract_json(text) == {"a": 1}


def test_two_inline_objects_returns_first():
    assert extract_json('{"a": 1} or maybe {"b": 2}') == {"a": 1}


def test_two_fenced_blocks_returns_first():
    text = (
        '```json\n{"a": 1}\n```\nAlternatively:\n'
        '```json\n{"b": 2, "why": "longer"}\n```'
    )
    assert extract_json(text) == {"a": 1}


def test_brace_inside_string_value():
    assert extract_json('{"a": "curly } brace"}') == {"a": "curly } brace"}


def test_no_json_raises():
    with pytest.raises(ValueError, match="No JSON object"):
        extract_json("I cannot answer that.")


def test_malformed_json_raises():
    with pytest.raises(ValueError, match="Invalid JSON"):
        extract_json('{"a": unquoted}')
