"""Tests for the QueryInterpreter port and its LLM implementation."""

from agent.interpreter import LLMQueryInterpreter
from agent.state import InterpretedQuery
from tests.agent.fakes import FakeLLMClient


def test_parses_valid_response():
    client = FakeLLMClient(
        ['{"intent": "corpus_question", "queries": ["jhana factors"], "strategy_hint": "hybrid"}']
    )
    result = LLMQueryInterpreter(client).interpret("what are the jhana factors?")
    assert isinstance(result, InterpretedQuery)
    assert result.queries == ["jhana factors"]
    assert result.strategy_hint == "hybrid"


def test_retries_once_on_bad_json_with_error_feedback():
    client = FakeLLMClient(
        ["not json at all", '{"intent": "corpus_question", "queries": ["metta"]}']
    )
    result = LLMQueryInterpreter(client).interpret("metta?")
    assert result.queries == ["metta"]
    assert len(client.calls) == 2
    # retry prompt must carry the parse error back to the model
    assert (
        "Invalid" in client.calls[1][-1]["content"] or "No JSON" in client.calls[1][-1]["content"]
    )


def test_falls_back_to_user_message_after_two_failures():
    client = FakeLLMClient(["nope", "still nope"])
    result = LLMQueryInterpreter(client).interpret("what is vipassana?")
    assert result.intent == "corpus_question"
    assert result.queries == ["what is vipassana?"]


def test_falls_back_to_user_message_when_transport_fails_twice():
    # All-rungs-down LLM client must not crash the turn.
    client = FakeLLMClient([RuntimeError("all rungs down"), RuntimeError("still down")])
    result = LLMQueryInterpreter(client).interpret("what is vipassana?")
    assert result.intent == "corpus_question"
    assert result.queries == ["what is vipassana?"]


def test_empty_queries_backfilled_with_user_message():
    client = FakeLLMClient(['{"intent": "corpus_question", "queries": []}'])
    result = LLMQueryInterpreter(client).interpret("anapanasati steps")
    assert result.queries == ["anapanasati steps"]


def test_other_intent_with_empty_queries_stays_empty():
    # Seam invariant: the raw message must not leak toward retrieval for
    # non-corpus turns, regardless of downstream routing.
    client = FakeLLMClient(['{"intent": "other", "queries": []}'])
    result = LLMQueryInterpreter(client).interpret("hey, how are you?")
    assert result.intent == "other"
    assert result.queries == []


def test_history_is_included_in_prompt():
    client = FakeLLMClient(['{"intent": "corpus_question", "queries": ["second jhana"]}'])
    history = [
        {"role": "user", "content": "tell me about jhana"},
        {"role": "assistant", "content": "Jhana is..."},
    ]
    LLMQueryInterpreter(client).interpret("what about the second one?", history=history)
    prompt_text = str(client.calls[0])
    assert "second one" in prompt_text and "tell me about jhana" in prompt_text


def test_history_capped_to_last_six_messages():
    client = FakeLLMClient(['{"intent": "corpus_question", "queries": ["metta"]}'])
    history = [{"role": "user", "content": f"turn-{i}"} for i in range(8)]
    LLMQueryInterpreter(client).interpret("and metta?", history=history)
    prompt_text = str(client.calls[0])
    assert "turn-2" in prompt_text and "turn-7" in prompt_text
    assert "turn-0" not in prompt_text and "turn-1" not in prompt_text
