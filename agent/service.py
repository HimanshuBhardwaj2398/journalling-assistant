"""Public entry point: one conversational turn through the agent graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from agent.graph import build_agent_graph
from agent.interpreter import LLMQueryInterpreter
from agent.nodes import DEFAULT_CLARIFYING_QUESTION, AgentConfig, AgentDeps
from agent.router import client_for_role
from agent.state import AgentState, Outcome
from observability.langfuse import get_langfuse_tracer
from retrieval.answering import GroundedAnswerService
from retrieval.registry import default_retrievers

logger = logging.getLogger(__name__)


@dataclass
class AgentTurnResult:
    outcome: Outcome
    text: str
    citations: list[Any]
    state: AgentState
    trace_url: Optional[str]
    trace_id: Optional[str]  # future eval integration links scores by trace id


def build_default_deps() -> AgentDeps:
    tracer = get_langfuse_tracer()
    config = AgentConfig()
    answer_client = client_for_role("answerer", tracer=tracer)
    # Same small model serves both interpretation and direct replies — build
    # the client once and share the instance.
    interpreter_client = client_for_role("interpreter", tracer=tracer)
    return AgentDeps(
        interpreter=LLMQueryInterpreter(interpreter_client),
        grader_client=client_for_role("grader", tracer=tracer),
        direct_client=interpreter_client,
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
        trace_id = getattr(obs, "trace_id", None)

    if final.outcome is None:
        # Every terminal node sets an outcome, so None means a wiring bug —
        # log it loudly and degrade to a clarify turn instead of masking it.
        logger.warning(
            "agent graph finished without an outcome (wiring bug?); "
            "falling back to clarify"
        )
        outcome: Outcome = "clarify"
        text = final.final_text or DEFAULT_CLARIFYING_QUESTION
    else:
        outcome = final.outcome
        text = final.final_text or ""

    return AgentTurnResult(
        outcome=outcome,
        text=text,
        citations=final.citations,
        state=final,
        trace_url=trace_url,
        trace_id=trace_id,
    )
