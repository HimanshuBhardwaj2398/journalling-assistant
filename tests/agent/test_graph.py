"""End-to-end graph tests with scripted fakes: all four paths."""

from agent.graph import build_agent_graph
from agent.nodes import AgentConfig, AgentDeps
from agent.state import AgentState, InterpretedQuery
from tests.agent.fakes import (
    FakeAnswerService,
    FakeInterpreter,
    FakeLLMClient,
    FakeRetriever,
    FakeTracer,
    make_result,
)


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


def invoke(deps, message="what is jhana?"):
    graph = build_agent_graph(deps)
    final = graph.invoke(AgentState(user_message=message))
    return AgentState.model_validate(final)


def test_happy_path_answers():
    state = invoke(make_deps())
    assert state.outcome == "answer"
    assert "absorption" in state.final_text
    assert state.iterations == 0


def test_direct_path_skips_retrieval():
    deps = make_deps(interpreter=FakeInterpreter(InterpretedQuery(intent="other", queries=["hi"])))
    state = invoke(deps, message="hello!")
    assert state.outcome == "direct"
    assert state.retrieved == []


def test_rewrite_then_answer():
    grader = FakeLLMClient(
        [
            '{"sufficient": false, "missing_info": "wrong vocabulary"}',
            '{"sufficient": true}',
        ]
    )
    retriever = FakeRetriever({"q1": [make_result("u1")], "alt": [make_result("u2")]})
    direct = FakeLLMClient(['{"queries": ["alt"]}'])
    deps = make_deps(grader_client=grader, retrievers={"hybrid": retriever}, direct_client=direct)
    state = invoke(deps)
    assert state.outcome == "answer"
    assert state.iterations == 1
    assert {r.chunk_uuid for r in state.retrieved} == {"u1", "u2"}


def test_budget_exhausted_clarifies():
    grader = FakeLLMClient(
        [
            '{"sufficient": false, "clarifying_question": "Which text?"}',
            '{"sufficient": false, "clarifying_question": "Which text?"}',
        ]
    )
    direct = FakeLLMClient(['{"queries": ["alt"]}'])
    deps = make_deps(grader_client=grader, direct_client=direct)
    state = invoke(deps)
    assert state.outcome == "clarify"
    assert state.final_text == "Which text?"
