"""Tests for agent playground pure helpers (no streamlit runtime)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from agent.state import AgentState, InterpretedQuery, SufficiencyGrade
from views.agent_playground import debug_summary


def test_debug_summary_extracts_loop_facts():
    state = AgentState(
        user_message="jhana?",
        interpreted=InterpretedQuery(intent="corpus_question", queries=["jhana factors"]),
        grade=SufficiencyGrade(sufficient=True),
        iterations=1,
        outcome="answer",
    )
    summary = debug_summary(state)
    assert summary["intent"] == "corpus_question"
    assert summary["queries"] == ["jhana factors"]
    assert summary["sufficient"] is True
    assert summary["iterations"] == 1
    assert summary["outcome"] == "answer"


def test_debug_summary_handles_empty_state():
    summary = debug_summary(AgentState(user_message="hi"))
    assert summary["intent"] is None
    assert summary["queries"] == []
