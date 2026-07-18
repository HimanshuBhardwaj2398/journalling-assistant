"""Agent Playground: conversational agentic RAG with a visible loop."""

from __future__ import annotations

from typing import Any

import streamlit as st

from agent.state import AgentState


@st.cache_resource
def _agent_deps():
    """One deps graph per process — a fresh one per rerun would open a new
    vector-store connection per chat message."""
    from agent.service import build_default_deps

    return build_default_deps()


def execute_turn(
    prompt: str,
    chat: list[dict[str, str]],
    run_turn_fn: Any,
    deps: Any,
) -> Any:
    """Run one turn and keep `chat` (Streamlit's persisted transcript)
    consistent with what actually happened, even on failure.

    Appends the user's message to `chat` immediately, using a snapshot of the
    prior history (taken before that append) as `run_turn_fn`'s `history=`
    argument so the new turn isn't duplicated inside the graph's context. On
    success, appends the assistant's reply and returns the result. On
    failure, appends an assistant-role entry recording the error and
    re-raises so the caller can still surface it (e.g. via `st.error`).
    """
    history = list(chat)
    chat.append({"role": "user", "content": prompt})
    try:
        result = run_turn_fn(prompt, history=history, deps=deps)
    except Exception as exc:
        chat.append({"role": "assistant", "content": f"_Error: {exc}_"})
        raise
    chat.append({"role": "assistant", "content": result.text})
    return result


def debug_summary(state: AgentState) -> dict[str, Any]:
    """Pure helper: loop facts for the per-turn debug expander."""
    return {
        "intent": state.interpreted.intent if state.interpreted else None,
        "queries": state.interpreted.queries if state.interpreted else [],
        "strategy_hint": state.interpreted.strategy_hint if state.interpreted else None,
        "sufficient": state.grade.sufficient if state.grade else None,
        "missing_info": state.grade.missing_info if state.grade else None,
        "iterations": state.iterations,
        "outcome": state.outcome,
        "chunks": len(state.retrieved),
    }


def render() -> None:
    st.header("Agent Playground")
    st.caption(
        "Interpret → retrieve → grade → answer/clarify. "
        "Local qwen3 routes the loop; Groq answers. Compare with the RAG Playground."
    )

    if "agent_chat" not in st.session_state:
        st.session_state.agent_chat = []  # [{"role", "content"}] — full transcript, incl. failed turns

    for message in st.session_state.agent_chat:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask about meditation or the texts…")
    if not prompt:
        return

    with st.chat_message("user"):
        st.markdown(prompt)

    from agent.service import run_turn  # deferred: heavy deps (DB, embeddings)

    with st.chat_message("assistant"), st.spinner("Thinking…"):
        try:
            result = execute_turn(prompt, st.session_state.agent_chat, run_turn, _agent_deps())
        except Exception as exc:
            st.error(f"Agent turn failed: {exc}")
            return

        st.markdown(result.text)
        summary = debug_summary(result.state)
        with st.expander("Loop debug"):
            st.json(summary)
            if result.trace_url:
                st.markdown(f"[Langfuse trace]({result.trace_url})")
        if result.outcome == "answer" and result.citations:
            with st.expander(f"Citations ({len(result.citations)})"):
                for citation in result.citations:
                    st.markdown(f"**{citation.label}** — {citation.source_title or 'unknown'}")
                    st.caption(citation.excerpt)
