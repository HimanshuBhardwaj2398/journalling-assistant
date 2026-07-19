"""Tests for agent state models and validation."""

from agent.state import AgentState, InterpretedQuery, SufficiencyGrade


def test_interpreted_query_defaults_queries_to_empty():
    iq = InterpretedQuery(intent="corpus_question")
    assert iq.queries == []
    assert iq.strategy_hint is None


def test_strategy_hint_normalized():
    iq = InterpretedQuery(intent="corpus_question", strategy_hint="HYBRID")
    assert iq.strategy_hint == "hybrid"


def test_invalid_strategy_hint_dropped():
    iq = InterpretedQuery(intent="corpus_question", strategy_hint="reranker")
    assert iq.strategy_hint is None


def test_unknown_intent_coerced_to_other():
    iq = InterpretedQuery(intent="banter")
    assert iq.intent == "other"


def test_intent_case_normalized():
    iq = InterpretedQuery(intent="Corpus_Question")
    assert iq.intent == "corpus_question"


def test_intent_whitespace_normalized():
    iq = InterpretedQuery(intent=" corpus_question ")
    assert iq.intent == "corpus_question"


def test_lone_string_query_wrapped_in_list():
    iq = InterpretedQuery(intent="corpus_question", queries="what is jhana")
    assert iq.queries == ["what is jhana"]


def test_none_queries_coerced_to_empty_list():
    iq = InterpretedQuery(intent="corpus_question", queries=None)
    assert iq.queries == []


def test_queries_filtered_to_nonempty_strings():
    iq = InterpretedQuery(intent="corpus_question", queries=[1, "ok", "  "])
    assert iq.queries == ["ok"]


def test_agent_state_defaults():
    state = AgentState(user_message="what is jhana?")
    assert state.iterations == 0
    assert state.retrieved == []
    assert state.outcome is None
    assert state.messages == []


def test_sufficiency_grade_shape():
    g = SufficiencyGrade(
        sufficient=False, missing_info="which sutta", clarifying_question="Which text?"
    )
    assert not g.sufficient
