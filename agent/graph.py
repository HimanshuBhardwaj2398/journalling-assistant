"""StateGraph wiring. Pure orchestration — no LLM calls, no tracing here."""

from __future__ import annotations

from functools import partial

from langgraph.graph import END, StateGraph

from agent.nodes import (
    AgentDeps,
    answer_node,
    clarify_node,
    grade_node,
    interpret_node,
    respond_direct_node,
    retrieve_node,
    rewrite_node,
)
from agent.state import AgentState


def route_after_interpret(state: AgentState) -> str:
    if state.interpreted and state.interpreted.intent == "other":
        return "respond_direct"
    return "retrieve"


def make_route_after_grade(max_rewrites: int):
    def route_after_grade(state: AgentState) -> str:
        if state.grade and state.grade.sufficient:
            return "answer"
        if state.iterations < max_rewrites:
            return "rewrite"
        return "clarify"

    return route_after_grade


def build_agent_graph(deps: AgentDeps):
    # Longest path (max_rewrites=2 → ~10 supersteps) sits well under
    # LangGraph's default recursion limit of 25.
    graph = StateGraph(AgentState)
    graph.add_node("interpret", partial(interpret_node, deps=deps))
    graph.add_node("retrieve", partial(retrieve_node, deps=deps))
    graph.add_node("grade", partial(grade_node, deps=deps))
    graph.add_node("rewrite", partial(rewrite_node, deps=deps))
    graph.add_node("answer", partial(answer_node, deps=deps))
    graph.add_node("clarify", partial(clarify_node, deps=deps))
    graph.add_node("respond_direct", partial(respond_direct_node, deps=deps))

    graph.set_entry_point("interpret")
    graph.add_conditional_edges(
        "interpret",
        route_after_interpret,
        {"retrieve": "retrieve", "respond_direct": "respond_direct"},
    )
    graph.add_edge("retrieve", "grade")
    graph.add_conditional_edges(
        "grade",
        make_route_after_grade(deps.config.max_rewrites),
        {"answer": "answer", "rewrite": "rewrite", "clarify": "clarify"},
    )
    graph.add_edge("rewrite", "retrieve")
    graph.add_edge("answer", END)
    graph.add_edge("clarify", END)
    graph.add_edge("respond_direct", END)
    return graph.compile()
