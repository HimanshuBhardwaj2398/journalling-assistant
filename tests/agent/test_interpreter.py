"""Tests for the QueryInterpreter port and its LLM implementation."""

from agent.interpreter import LLMQueryInterpreter
from agent.state import InterpretedQuery


class FakeLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, temperature=0.0, max_tokens=200):
        self.calls.append(messages)
        return self.responses.pop(0)


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
    assert "Invalid" in client.calls[1][-1]["content"] or "No JSON" in client.calls[1][-1]["content"]


def test_falls_back_to_user_message_after_two_failures():
    client = FakeLLMClient(["nope", "still nope"])
    result = LLMQueryInterpreter(client).interpret("what is vipassana?")
    assert result.intent == "corpus_question"
    assert result.queries == ["what is vipassana?"]


def test_empty_queries_backfilled_with_user_message():
    client = FakeLLMClient(['{"intent": "corpus_question", "queries": []}'])
    result = LLMQueryInterpreter(client).interpret("anapanasati steps")
    assert result.queries == ["anapanasati steps"]


def test_history_is_included_in_prompt():
    client = FakeLLMClient(['{"intent": "corpus_question", "queries": ["second jhana"]}'])
    history = [{"role": "user", "content": "tell me about jhana"},
               {"role": "assistant", "content": "Jhana is..."}]
    LLMQueryInterpreter(client).interpret("what about the second one?", history=history)
    prompt_text = str(client.calls[0])
    assert "second one" in prompt_text and "tell me about jhana" in prompt_text
