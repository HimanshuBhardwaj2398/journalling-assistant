"""run_turn service tests with injected fake deps — no network, no DB."""

import logging
from contextlib import contextmanager

import pytest

from agent.nodes import DEFAULT_CLARIFYING_QUESTION, AgentConfig, AgentDeps
from agent.service import AgentTurnResult, build_default_deps, run_turn
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


class GraphWithoutOutcome:
    """Simulates a wiring bug: the graph ends without any terminal node."""

    def invoke(self, initial):
        return {"user_message": initial.user_message}


def test_run_turn_missing_outcome_warns_and_falls_back(monkeypatch, caplog):
    deps = make_deps()
    monkeypatch.setattr("agent.service.build_agent_graph", lambda _deps: GraphWithoutOutcome())

    with caplog.at_level(logging.WARNING, logger="agent.service"):
        result = run_turn("what is jhana?", deps=deps)

    assert result.outcome == "clarify"
    assert result.text == DEFAULT_CLARIFYING_QUESTION
    assert any("outcome" in record.message for record in caplog.records)


class TraceIdTracer:
    """Fake tracer whose root-span handle exposes trace_id/trace_url."""

    def observe(self, **kwargs):
        @contextmanager
        def _cm():
            class Handle:
                trace_id = "trace-abc"
                trace_url = "https://langfuse.local/trace/trace-abc"

                def update(self, **kw):
                    pass

            yield Handle()

        return _cm()


def test_run_turn_exposes_trace_id_and_url_from_root_span():
    deps = make_deps(tracer=TraceIdTracer())
    result = run_turn("what is jhana?", deps=deps)
    assert result.trace_id == "trace-abc"
    assert result.trace_url == "https://langfuse.local/trace/trace-abc"


def test_build_default_deps_shares_one_interpreter_client(monkeypatch):
    roles_requested = []

    def fake_client_for_role(role, settings=None, tracer=None):
        roles_requested.append(role)
        return FakeLLMClient([])

    monkeypatch.setattr("agent.service.client_for_role", fake_client_for_role)
    monkeypatch.setattr("agent.service.get_langfuse_tracer", lambda: FakeTracer())
    monkeypatch.setattr(
        "agent.service.default_retrievers", lambda: {"hybrid": FakeRetriever({})}
    )
    monkeypatch.setattr(
        "agent.service.GroundedAnswerService", lambda **kwargs: FakeAnswerService()
    )

    deps = build_default_deps()

    # One small-model client serves both the interpreter and direct replies.
    assert roles_requested.count("interpreter") == 1
    assert deps.direct_client is deps.interpreter._client


def test_run_turn_records_error_on_root_span_and_reraises():
    deps = make_deps(answer_service=ExplodingAnswerService())
    with pytest.raises(RuntimeError, match="all answerer models down"):
        run_turn("what is jhana?", deps=deps)

    span = root_span(deps.tracer)
    error_updates = [u for u in span["updates"] if u.get("level") == "ERROR"]
    assert error_updates
    assert "all answerer models down" in error_updates[-1]["status_message"]
