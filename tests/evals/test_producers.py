"""Query producers turn a dataset question into the queries actually searched."""

from evals.producers import Production, interpreter_producer, raw_producer


class FakeClient:
    """Stands in for LLMClient; returns canned completions in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, messages, temperature=0.0, max_tokens=200):
        self.calls += 1
        if not self._responses:
            raise RuntimeError("no canned response left")
        return self._responses.pop(0)


def test_raw_producer_passes_the_question_through():
    result = raw_producer("why is my mind restless?")
    assert isinstance(result, Production)
    assert result.queries == ["why is my mind restless?"]
    assert result.fallback is False


def test_interpreter_producer_returns_model_rewrites():
    client = FakeClient(
        ['{"intent": "corpus_question", "queries": ["restlessness", "hindrances"]}']
    )
    result = interpreter_producer(client)("why is my mind restless?")
    assert result.queries == ["restlessness", "hindrances"]
    assert result.fallback is False
    assert result.intent == "corpus_question"


def test_interpreter_producer_flags_the_silent_fallback():
    # Unparseable twice -> interpreter backfills the raw question. If this is
    # not flagged, the contender arm silently becomes the control.
    client = FakeClient(["not json at all", "still not json"])
    result = interpreter_producer(client)("why is my mind restless?")
    assert result.queries == ["why is my mind restless?"]
    assert result.fallback is True
    assert client.calls == 2


def test_interpreter_producer_records_strategy_hint():
    client = FakeClient(
        ['{"intent": "corpus_question", "queries": ["q"], "strategy_hint": "hybrid"}']
    )
    result = interpreter_producer(client)("q2")
    assert result.strategy_hint == "hybrid"


def test_first_only_keeps_a_single_query():
    client = FakeClient(['{"intent": "corpus_question", "queries": ["a", "b", "c"]}'])
    result = interpreter_producer(client, first_only=True)("q")
    assert result.queries == ["a"]


def test_interpreter_producer_never_returns_empty_queries():
    # An empty queries list would retrieve nothing and score 0 -- indistinguishable
    # from a genuine retrieval miss. Backfill to the raw question instead.
    client = FakeClient(['{"intent": "corpus_question", "queries": []}'])
    result = interpreter_producer(client)("why is my mind restless?")
    assert result.queries == ["why is my mind restless?"]
    assert result.fallback is True


def test_production_records_raw_model_output_for_audit():
    client = FakeClient(['{"intent": "corpus_question", "queries": ["a"]}'])
    result = interpreter_producer(client)("q")
    assert result.raw["queries"] == ["a"]
