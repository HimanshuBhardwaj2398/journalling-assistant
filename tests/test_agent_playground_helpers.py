"""Tests for agent playground pure helpers (no streamlit runtime)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

import pytest

from agent.state import AgentState, InterpretedQuery, SufficiencyGrade
from views.agent_playground import debug_summary, execute_turn


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


def test_execute_turn_persists_user_message_and_error_on_failure():
    """Reproduces the bug: a failed run_turn must not silently drop the
    user's question from the transcript."""
    chat: list[dict[str, str]] = [
        {"role": "user", "content": "prior q"},
        {"role": "assistant", "content": "prior a"},
    ]

    def failing_run_turn(prompt, history=None, deps=None):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        execute_turn("new question", chat, failing_run_turn, deps=None)

    assert chat[-2] == {"role": "user", "content": "new question"}
    assert chat[-1]["role"] == "assistant"
    assert "boom" in chat[-1]["content"]


def test_execute_turn_appends_user_then_assistant_on_success():
    chat: list[dict[str, str]] = [{"role": "user", "content": "prior q"}]
    captured_history: dict[str, list[dict[str, str]]] = {}

    class FakeResult:
        text = "the answer"

    def fake_run_turn(prompt, history=None, deps=None):
        captured_history["history"] = list(history or [])
        return FakeResult()

    result = execute_turn("new question", chat, fake_run_turn, deps="deps-marker")

    assert result.text == "the answer"
    # history handed to run_turn is a snapshot taken BEFORE the new user
    # message was appended — no duplication inside the graph's context.
    assert captured_history["history"] == [{"role": "user", "content": "prior q"}]
    assert chat == [
        {"role": "user", "content": "prior q"},
        {"role": "user", "content": "new question"},
        {"role": "assistant", "content": "the answer"},
    ]
