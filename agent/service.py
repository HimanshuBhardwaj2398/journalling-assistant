"""Public entry point: one conversational turn through the agent graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from agent.graph import build_agent_graph
from agent.interpreter import LLMQueryInterpreter
from agent.nodes import AgentConfig, AgentDeps
from agent.router import client_for_role
from agent.state import AgentState
from observability.langfuse import get_langfuse_tracer
from retrieval.answering import GroundedAnswerService
from retrieval.registry import default_retrievers


@dataclass
class AgentTurnResult:
    outcome: str  # "answer" | "clarify" | "direct"
    text: str
    citations: list[Any]
    state: AgentState
    trace_url: Optional[str]


def build_default_deps() -> AgentDeps:
    tracer = get_langfuse_tracer()
    config = AgentConfig()
    answer_client = client_for_role("answerer", tracer=tracer)
    return AgentDeps(
        interpreter=LLMQueryInterpreter(client_for_role("interpreter", tracer=tracer)),
        grader_client=client_for_role("grader", tracer=tracer),
        direct_client=client_for_role("interpreter", tracer=tracer),
        answer_service=GroundedAnswerService(
            llm_client=answer_client,
            tracer=tracer,
            max_chunks=config.max_context_chunks,  # align with the agent's context cap
        ),
        retrievers=default_retrievers(),
        tracer=tracer,
        config=config,
    )


def run_turn(
    user_message: str,
    history: Optional[list[dict[str, str]]] = None,
    deps: Optional[AgentDeps] = None,
) -> AgentTurnResult:
    """Run one turn. Clarify mechanic: the caller shows the question and calls
    run_turn again with the reply appended to history — no pause/resume state.

    `history` is PRIOR turns only; the in-flight user_message must not be in it.
    """
    deps = deps or build_default_deps()
    graph = build_agent_graph(deps)
    initial = AgentState(user_message=user_message, messages=list(history or []))

    with deps.tracer.observe(name="agent.turn", input=user_message) as obs:
        try:
            final = AgentState.model_validate(graph.invoke(initial))
        except Exception as exc:
            obs.update(level="ERROR", status_message=str(exc))
            raise
        obs.update(
            output=final.final_text,
            metadata={
                "outcome": final.outcome,
                "iterations": final.iterations,
                "chunks": len(final.retrieved),
            },
        )
        trace_url = getattr(obs, "trace_url", None)

    return AgentTurnResult(
        outcome=final.outcome or "clarify",
        text=final.final_text or "",
        citations=final.citations,
        state=final,
        trace_url=trace_url,
    )
