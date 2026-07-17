"""Tests for tolerant JSON extraction from small-model output."""

import logging

import pytest
from pydantic import BaseModel

from agent.parsing import extract_json, parse_structured_with_retry
from tests.agent.conftest import FakeLLMClient


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


class _StrictModel(BaseModel):
    value: int


def test_retry_helper_first_try_success():
    client = FakeLLMClient(['{"value": 7}'])
    result = parse_structured_with_retry(client, [{"role": "user", "content": "go"}], _StrictModel)
    assert result == _StrictModel(value=7)
    assert len(client.calls) == 1


def test_retry_helper_feedback_carries_error_and_succeeds():
    # First reply fails pydantic validation; retry prompt must include the
    # raw reply and the error, and the second reply must be accepted.
    client = FakeLLMClient(['{"value": "not an int"}', '{"value": 3}'])
    messages = [{"role": "user", "content": "go"}]
    result = parse_structured_with_retry(client, messages, _StrictModel)
    assert result == _StrictModel(value=3)
    assert len(client.calls) == 2
    retry = client.calls[1]
    assert retry[-2] == {"role": "assistant", "content": '{"value": "not an int"}'}
    assert retry[-1]["role"] == "user"
    assert "Invalid" in retry[-1]["content"]
    # only the first line of the (multiline) pydantic error is fed back
    assert "\n" not in retry[-1]["content"]
    # original messages are not mutated
    assert messages == [{"role": "user", "content": "go"}]


def test_retry_helper_returns_none_after_two_failures(caplog):
    client = FakeLLMClient(["nope", "still nope"])
    with caplog.at_level(logging.WARNING, logger="agent.parsing"):
        result = parse_structured_with_retry(
            client, [{"role": "user", "content": "go"}], _StrictModel
        )
    assert result is None
    assert len(client.calls) == 2
    # final failure reason is logged before returning None
    assert any("No JSON" in r.getMessage() for r in caplog.records)


def test_retry_helper_transport_failure_then_success():
    client = FakeLLMClient([RuntimeError("all rungs down"), '{"value": 5}'])
    messages = [{"role": "user", "content": "go"}]
    result = parse_structured_with_retry(client, messages, _StrictModel)
    assert result == _StrictModel(value=5)
    assert len(client.calls) == 2
    # transport failure retries the SAME messages — no feedback to echo
    assert client.calls[1] == messages


def test_retry_helper_returns_none_after_two_transport_failures():
    client = FakeLLMClient([RuntimeError("down"), RuntimeError("still down")])
    result = parse_structured_with_retry(client, [{"role": "user", "content": "go"}], _StrictModel)
    assert result is None
    assert len(client.calls) == 2


def test_retry_helper_passes_max_tokens_through():
    client = FakeLLMClient(['{"value": 1}'])
    parse_structured_with_retry(
        client, [{"role": "user", "content": "go"}], _StrictModel, max_tokens=512
    )
    assert client.max_tokens_seen == [512]


def test_retry_helper_default_max_tokens_is_300():
    client = FakeLLMClient(['{"value": 1}'])
    parse_structured_with_retry(client, [{"role": "user", "content": "go"}], _StrictModel)
    assert client.max_tokens_seen == [300]
