"""Node-level tests with fake deps — no graph, no network."""

from agent.nodes import (
    AgentConfig,
    AgentDeps,
    answer_node,
    clarify_node,
    grade_node,
    interpret_node,
    respond_direct_node,
    retrieve_node,
    rewrite_node,
)
from agent.state import AgentState, InterpretedQuery, SufficiencyGrade
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
        config=AgentConfig(),
    )
    defaults.update(overrides)
    return AgentDeps(**defaults)


def test_interpret_node_sets_interpreted():
    deps = make_deps()
    update = interpret_node(AgentState(user_message="jhana?"), deps=deps)
    assert update["interpreted"].queries == ["q1"]


def test_retrieve_node_dedupes_across_queries_and_iterations():
    retriever = FakeRetriever({
        "q1": [make_result("u1"), make_result("u2")],
        "q2": [make_result("u2"), make_result("u3")],
    })
    deps = make_deps(retrievers={"hybrid": retriever})
    state = AgentState(
        user_message="x",
        interpreted=InterpretedQuery(intent="corpus_question", queries=["q1", "q2"]),
        retrieved=[make_result("u0")],
    )
    update = retrieve_node(state, deps=deps)
    uuids = [r.chunk_uuid for r in update["retrieved"]]
    assert uuids == ["u0", "u1", "u2", "u3"]


def test_retrieve_node_respects_strategy_hint():
    similarity = FakeRetriever({"q1": [make_result("s1")]})
    similarity.name = "similarity"
    deps = make_deps(retrievers={"hybrid": FakeRetriever({}), "similarity": similarity})
    state = AgentState(
        user_message="x",
        interpreted=InterpretedQuery(
            intent="corpus_question", queries=["q1"], strategy_hint="similarity"
        ),
    )
    update = retrieve_node(state, deps=deps)
    assert [r.chunk_uuid for r in update["retrieved"]] == ["s1"]


def test_grade_node_parses_verdict():
    deps = make_deps(grader_client=FakeLLMClient(
        ['{"sufficient": false, "missing_info": "tradition", "clarifying_question": "Which tradition?"}']
    ))
    state = AgentState(user_message="x", retrieved=[make_result("u1")])
    update = grade_node(state, deps=deps)
    assert update["grade"].sufficient is False
    assert update["grade"].clarifying_question == "Which tradition?"


def test_grade_node_bad_json_degrades_to_insufficient():
    deps = make_deps(grader_client=FakeLLMClient(["garbage", "more garbage"]))
    state = AgentState(user_message="x", retrieved=[make_result("u1")])
    update = grade_node(state, deps=deps)
    assert update["grade"].sufficient is False


def test_rewrite_node_replaces_queries_and_increments():
    deps = make_deps(direct_client=FakeLLMClient(['{"queries": ["alt one", "alt two"]}']))
    state = AgentState(
        user_message="x",
        interpreted=InterpretedQuery(intent="corpus_question", queries=["q1"]),
        grade=SufficiencyGrade(sufficient=False, missing_info="needs sutta name"),
        iterations=0,
    )
    update = rewrite_node(state, deps=deps)
    assert update["iterations"] == 1
    assert update["interpreted"].queries == ["alt one", "alt two"]


def test_answer_node_produces_final_text():
    deps = make_deps()
    state = AgentState(user_message="jhana?", retrieved=[make_result("u1")])
    update = answer_node(state, deps=deps)
    assert update["outcome"] == "answer"
    assert "absorption" in update["final_text"]


def test_clarify_node_uses_grade_question():
    state = AgentState(
        user_message="x",
        grade=SufficiencyGrade(sufficient=False, clarifying_question="Which sutta?"),
    )
    update = clarify_node(state, deps=make_deps())
    assert update["outcome"] == "clarify"
    assert update["final_text"] == "Which sutta?"


def test_clarify_node_falls_back_to_default_question():
    state = AgentState(user_message="x", grade=SufficiencyGrade(sufficient=False))
    update = clarify_node(state, deps=make_deps())
    assert update["outcome"] == "clarify"
    assert update["final_text"]  # non-empty canned question


def test_respond_direct_node():
    deps = make_deps(direct_client=FakeLLMClient(["Hi there."]))
    update = respond_direct_node(AgentState(user_message="hello"), deps=deps)
    assert update["outcome"] == "direct"
    assert update["final_text"] == "Hi there."
