"""Graph node functions. Plain functions over AgentState with injected deps.

Every node opens a tracer-port span; LangGraph never sees the tracer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from agent.parsing import extract_json, parse_structured_with_retry
from agent.state import AgentState, InterpretedQuery, SufficiencyGrade
from agent.tracing import Span, traced

logger = logging.getLogger(__name__)

DEFAULT_CLARIFYING_QUESTION = (
    "I could not find enough in the texts to answer confidently. "
    "Could you say more about what you are looking for — a specific "
    "practice, concept, or text?"
)

DIRECT_SYSTEM_PROMPT = (
    "You are a friendly assistant for a meditation-texts knowledge base. "
    "The user's message is small talk or out of scope. Reply briefly and, "
    "when natural, mention you can answer questions about meditation and "
    "the Pali Canon."
)

GRADER_SYSTEM_PROMPT = """You judge whether retrieved text chunks contain enough information to answer a question about Buddhist texts and meditation.

Return ONLY a JSON object:
{
  "sufficient": true | false,
  "missing_info": null | "what is missing",
  "clarifying_question": null | "one specific question to ask the user"
}

Set "clarifying_question" only when asking the user would genuinely help
(ambiguous question, missing context). Judge strictly: partial or tangential
chunks are not sufficient. Excerpts may be truncated previews of longer
chunks — judge on what is present rather than penalizing apparent
incompleteness."""

REWRITE_SYSTEM_PROMPT = """You write alternate search queries for a semantic search system over Buddhist texts.

Given the user's question, the queries already tried, and what was missing,
return ONLY a JSON object with 1-2 new short search queries, for example:
{"queries": ["jhana absorption factors", "samadhi first jhana"]}
Try different vocabulary (Pali terms vs English, broader or narrower)."""


@dataclass(frozen=True)
class AgentConfig:
    default_strategy: str = "hybrid"  # eval winner, RETRIEVAL_EVALS.md §"hybrid wins"
    k: int = 5
    max_context_chunks: int = 8
    max_rewrites: int = 2


@dataclass
class AgentDeps:
    interpreter: Any  # QueryInterpreter
    grader_client: Any  # LLMClient (grader role)
    direct_client: Any  # LLMClient (interpreter/small role)
    answer_service: Any  # GroundedAnswerService
    retrievers: dict[str, Any]  # registry: name -> Retriever
    tracer: Any  # LangfuseTracer (or fake)
    config: AgentConfig = field(default_factory=AgentConfig)

    def __post_init__(self) -> None:
        # Fail at wiring time, not mid-turn: retrieve_node falls back to the
        # default strategy, so it must always be in the registry.
        if self.config.default_strategy not in self.retrievers:
            raise ValueError(
                f"default_strategy {self.config.default_strategy!r} missing "
                f"from retrievers registry {sorted(self.retrievers)}"
            )


@traced("agent.interpret", input=lambda s, d: s.user_message)
def interpret_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    interpreted = deps.interpreter.interpret(state.user_message, history=state.messages)
    span.update(output=interpreted.model_dump())
    return {"interpreted": interpreted}


def _interpreted_or_default(state: AgentState) -> InterpretedQuery:
    """The interpreter's output, or a stand-in wrapping the raw message for
    states that reached retrieval without interpretation."""
    return state.interpreted or InterpretedQuery(queries=[state.user_message])


def _retriever_for(state: AgentState, deps: AgentDeps) -> Any:
    """The hinted retriever, falling back to the configured default.

    Called once to open the span and once in the body; both are dict lookups,
    so resolving twice is free and keeps the span's metadata honest.
    """
    strategy = _interpreted_or_default(state).strategy_hint or deps.config.default_strategy
    return deps.retrievers.get(strategy) or deps.retrievers[deps.config.default_strategy]


@traced(
    "agent.retrieve",
    input=lambda s, d: _interpreted_or_default(s).queries,
    metadata=lambda s, d: {
        "strategy": _retriever_for(s, d).name,
        "k": d.config.k,
        "iterations": s.iterations,
    },
)
def retrieve_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    retriever = _retriever_for(state, deps)
    old = list(state.retrieved)
    seen = {r.chunk_uuid or r.text for r in old}
    new: list[Any] = []
    for query in _interpreted_or_default(state).queries:
        for result in retriever.retrieve(query, k=deps.config.k):
            key = result.chunk_uuid or result.text
            if key in seen:
                continue
            seen.add(key)
            new.append(result)
    # Fresh results get guaranteed entry: the grader judged the old context
    # insufficient (that is why we are retrieving again), so new evidence
    # outranks stale slots. Keep all new results up to the cap (trimming new's
    # own tail if it alone exceeds it) and fill the remaining slots with old
    # results in their existing order.
    cap = deps.config.max_context_chunks
    n_new_unique = len(new)
    new = new[:cap]
    merged = old[: cap - len(new)] + new
    span.update(
        output={
            "chunks": len(merged),
            "new": n_new_unique,
            "dropped": len(old) + n_new_unique - len(merged),
        }
    )
    return {"retrieved": merged}


def _grader_messages(state: AgentState) -> list[dict[str, str]]:
    """Grader prompt: the question plus numbered excerpts of what we retrieved."""
    # 1000-char excerpts: corpus min chunk size is 700, so most chunks fit
    # whole; the prompt tells the grader longer ones are truncated previews.
    excerpts = (
        "\n\n".join(f"[{i + 1}] {r.text[:1000]}" for i, r in enumerate(state.retrieved))
        or "(no chunks retrieved)"
    )
    return [
        {"role": "system", "content": GRADER_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Question: {state.user_message}\n\nRetrieved chunks:\n{excerpts}",
        },
    ]


@traced(
    "agent.grade",
    input=lambda s, d: {"chunks": len(s.retrieved)},
    metadata=lambda s, d: {"iterations": s.iterations},
)
def grade_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    grade = parse_structured_with_retry(
        deps.grader_client, _grader_messages(state), SufficiencyGrade
    )
    if grade is None:
        logger.warning("grader failed twice; treating context as insufficient")
        grade = SufficiencyGrade(sufficient=False, missing_info="grader unavailable")
    span.update(output=grade.model_dump())
    return {"grade": grade}


def _rewrite_messages(state: AgentState) -> list[dict[str, str]]:
    """Rewrite prompt: the question, the queries already tried, what was missing."""
    missing = state.grade.missing_info if state.grade else None
    return [
        {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question: {state.user_message}\n"
                f"Tried queries: {_interpreted_or_default(state).queries}\n"
                f"Missing: {missing or 'unknown'}"
            ),
        },
    ]


@traced("agent.rewrite", input=lambda s, d: _rewrite_messages(s)[-1]["content"])
def rewrite_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    new_queries: list[str] = []
    try:
        raw = deps.direct_client.complete(_rewrite_messages(state), max_tokens=200)
        parsed = extract_json(raw)
        new_queries = [q for q in parsed.get("queries", []) if isinstance(q, str)][:2]
    except Exception as exc:
        logger.warning("rewrite failed (%s); reusing original question", exc)
    if not new_queries:
        new_queries = [state.user_message]
    span.update(output=new_queries)
    # Accepted limitation: replacing queries means a second rewrite does not
    # see the original tried set. Dedupe in retrieve_node absorbs re-proposals;
    # revisit if traces show wasted iterations.
    return {
        "interpreted": _interpreted_or_default(state).model_copy(
            update={"queries": new_queries}
        ),
        "iterations": state.iterations + 1,
    }


@traced("agent.answer", metadata=lambda s, d: {"chunks": len(s.retrieved)})
def answer_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    if not state.retrieved:
        # The grader can hallucinate "sufficient" on empty context, and
        # GroundedAnswerService raises on empty search_results — degrade to a
        # clarify turn instead of crashing the graph. The span records the
        # degradation so it stays visible in Langfuse.
        logger.warning("answer_node reached with no retrieved chunks; clarifying")
        span.update(
            output=DEFAULT_CLARIFYING_QUESTION,
            metadata={"degraded": "empty_retrieval"},
        )
        return {"outcome": "clarify", "final_text": DEFAULT_CLARIFYING_QUESTION}
    response = deps.answer_service.answer(state.user_message, state.retrieved)
    span.update(output=response.answer)
    return {
        "outcome": "answer",
        "final_text": response.answer,
        "citations": list(response.citations),
    }


@traced("agent.clarify")
def clarify_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    question = (
        state.grade.clarifying_question
        if state.grade and state.grade.clarifying_question
        else DEFAULT_CLARIFYING_QUESTION
    )
    span.update(output=question)
    return {"outcome": "clarify", "final_text": question}


@traced("agent.respond_direct", input=lambda s, d: s.user_message)
def respond_direct_node(state: AgentState, *, deps: AgentDeps, span: Span) -> dict:
    # state.messages is PRIOR turns only; the in-flight user_message is
    # appended here. The service layer must not pre-include it in messages.
    messages = [
        {"role": "system", "content": DIRECT_SYSTEM_PROMPT},
        *state.messages[-4:],
        {"role": "user", "content": state.user_message},
    ]
    text = deps.direct_client.complete(messages, max_tokens=150)
    span.update(output=text)
    return {"outcome": "direct", "final_text": text}
