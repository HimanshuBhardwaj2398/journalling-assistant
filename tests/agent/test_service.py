"""run_turn service tests with injected fake deps — no network, no DB."""

import pytest

from agent.nodes import AgentConfig, AgentDeps
from agent.service import AgentTurnResult, run_turn
from agent.state import InterpretedQuery
from tests.agent.fakes import (
    FakeAnswerService,
    FakeInterpreter,
    FakeLLMClient,
    FakeRetriever,
    FakeTracer,
    make_result,
)


class ExplodingAnswerService:
    """Simulates the answerer's whole model chain failing."""

    def answer(self, query, search_results):
        raise RuntimeError("all answerer models down")


def make_deps(**overrides):
    defaults = dict(
        interpreter=FakeInterpreter(InterpretedQuery(intent="corpus_question", queries=["q1"])),
        grader_client=FakeLLMClient(['{"sufficient": true}']),
        direct_client=FakeLLMClient(["Hello!"]),
        answer_service=FakeAnswerService(),
        retrievers={"hybrid": FakeRetriever({"q1": [make_result("u1")]})},
        tracer=FakeTracer(),
        config=AgentConfig(max_rewrites=1),
    )
    defaults.update(overrides)
    return AgentDeps(**defaults)


def root_span(tracer):
    spans = [s for s in tracer.spans if s["kwargs"].get("name") == "agent.turn"]
    assert len(spans) == 1
    return spans[0]


def test_run_turn_returns_result_and_opens_root_span():
    deps = make_deps()
    result = run_turn("what is jhana?", deps=deps)
    assert isinstance(result, AgentTurnResult)
    assert result.outcome == "answer"
    assert "absorption" in result.text
    assert result.state.outcome == "answer"

    span = root_span(deps.tracer)
    assert span["kwargs"]["input"] == "what is jhana?"
    metadata_updates = [u for u in span["updates"] if "metadata" in u]
    assert metadata_updates, "root span update must carry outcome metadata"
    metadata = metadata_updates[-1]["metadata"]
    assert metadata["outcome"] == "answer"
    assert metadata["iterations"] == 0
    assert metadata["chunks"] == 1


def test_run_turn_passes_history_to_interpreter():
    interpreter = FakeInterpreter(
        InterpretedQuery(intent="corpus_question", queries=["q1"])
    )
    deps = make_deps(interpreter=interpreter)
    history = [
        {"role": "user", "content": "tell me about breath meditation"},
        {"role": "assistant", "content": "Anapanasati is..."},
    ]
    run_turn("what is jhana?", history=history, deps=deps)

    called_message, called_history = interpreter.calls[-1]
    assert called_message == "what is jhana?"
    assert called_history == history
    # History is PRIOR turns only: the in-flight message must not be in it.
    assert all(m["content"] != "what is jhana?" for m in called_history)


def test_run_turn_records_error_on_root_span_and_reraises():
    deps = make_deps(answer_service=ExplodingAnswerService())
    with pytest.raises(RuntimeError, match="all answerer models down"):
        run_turn("what is jhana?", deps=deps)

    span = root_span(deps.tracer)
    error_updates = [u for u in span["updates"] if u.get("level") == "ERROR"]
    assert error_updates
    assert "all answerer models down" in error_updates[-1]["status_message"]
