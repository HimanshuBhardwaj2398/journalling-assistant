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


def test_agent_state_defaults():
    state = AgentState(user_message="what is jhana?")
    assert state.iterations == 0
    assert state.retrieved == []
    assert state.outcome is None
    assert state.messages == []


def test_sufficiency_grade_shape():
    g = SufficiencyGrade(sufficient=False, missing_info="which sutta", clarifying_question="Which text?")
    assert not g.sufficient
