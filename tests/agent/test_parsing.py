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


def test_no_json_raises():
    with pytest.raises(ValueError, match="No JSON object"):
        extract_json("I cannot answer that.")


def test_malformed_json_raises():
    with pytest.raises(ValueError, match="Invalid JSON"):
        extract_json('{"a": unquoted}')
