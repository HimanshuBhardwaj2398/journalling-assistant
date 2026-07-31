"""Tests for the @traced decorator that wraps graph nodes.

The decorator only ever touches `deps.tracer`, so these tests use a minimal
deps stand-in rather than a full AgentDeps — that is the contract.
"""

from contextlib import contextmanager

import pytest

from agent.state import AgentState
from agent.tracing import traced
from tests.agent.fakes import FakeTracer


class FakeDeps:
    """Minimal stand-in: @traced needs `.tracer` and nothing else."""

    def __init__(self, tracer):
        self.tracer = tracer
        self.marker = "deps-value"


class ClosingTracer(FakeTracer):
    """FakeTracer that also records whether each span's context exited."""

    def observe(self, **kwargs):
        record = {"kwargs": kwargs, "updates": [], "closed": False}
        self.spans.append(record)

        @contextmanager
        def _cm():
            class Handle:
                def update(self, **kw):
                    record["updates"].append(kw)

            try:
                yield Handle()
            finally:
                record["closed"] = True

        return _cm()


def test_span_opens_before_the_node_body_runs():
    tracer = FakeTracer()

    @traced("agent.example")
    def node(state, *, deps, span):
        # Already recorded by the time the body executes: a node that raises
        # mid-body must still leave a span behind.
        assert tracer.spans[0]["kwargs"]["name"] == "agent.example"
        return {"ok": True}

    assert node(AgentState(user_message="x"), deps=FakeDeps(tracer)) == {"ok": True}


def test_undeclared_kwargs_are_omitted():
    tracer = FakeTracer()

    @traced("agent.bare")
    def node(state, *, deps, span):
        return {}

    node(AgentState(user_message="x"), deps=FakeDeps(tracer))
    assert tracer.spans[0]["kwargs"] == {"name": "agent.bare"}


def test_extractors_receive_state_and_deps():
    tracer = FakeTracer()

    @traced(
        "agent.extract",
        input=lambda s, d: s.user_message,
        metadata=lambda s, d: {"marker": d.marker},
    )
    def node(state, *, deps, span):
        return {}

    node(AgentState(user_message="jhana?"), deps=FakeDeps(tracer))
    assert tracer.spans[0]["kwargs"] == {
        "name": "agent.extract",
        "input": "jhana?",
        "metadata": {"marker": "deps-value"},
    }


def test_node_reports_output_through_the_injected_span():
    tracer = FakeTracer()

    @traced("agent.report")
    def node(state, *, deps, span):
        span.update(output="done")
        return {}

    node(AgentState(user_message="x"), deps=FakeDeps(tracer))
    assert tracer.spans[0]["updates"] == [{"output": "done"}]


def test_exception_propagates_and_span_still_closes():
    tracer = ClosingTracer()

    @traced("agent.boom", input=lambda s, d: s.user_message)
    def node(state, *, deps, span):
        raise RuntimeError("node failed")

    with pytest.raises(RuntimeError, match="node failed"):
        node(AgentState(user_message="x"), deps=FakeDeps(tracer))

    span = tracer.spans[0]
    assert span["kwargs"]["input"] == "x"  # input survived the failure
    assert span["closed"] is True


def test_failing_extractor_drops_the_key_but_keeps_the_span():
    tracer = FakeTracer()

    def bad_input(s, d):
        raise ValueError("boom")

    @traced(
        "agent.partial",
        input=bad_input,
        metadata=lambda s, d: {"marker": d.marker},
    )
    def node(state, *, deps, span):
        return {"ran": True}

    result = node(AgentState(user_message="x"), deps=FakeDeps(tracer))

    assert result == {"ran": True}
    assert tracer.spans[0]["kwargs"] == {
        "name": "agent.partial",
        "metadata": {"marker": "deps-value"},
    }


def test_wrapped_node_keeps_its_name():
    @traced("agent.named")
    def some_node(state, *, deps, span):
        return {}

    assert some_node.__name__ == "some_node"
