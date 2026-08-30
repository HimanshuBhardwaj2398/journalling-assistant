"""Query producers: dataset question -> the queries actually searched.

The control searches the raw question. The interpreter arm searches whatever
LLMQueryInterpreter rewrites it into. Both return a Production so the runner
can record what really happened, not just what was scored.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agent.interpreter import LLMQueryInterpreter

logger = logging.getLogger(__name__)


@dataclass
class Production:
    """What a producer emitted for one row, plus the diagnostics to audit it."""

    queries: list[str]
    intent: Optional[str] = None
    strategy_hint: Optional[str] = None
    fallback: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


Producer = Callable[[str], Production]


def raw_producer(question: str) -> Production:
    """The control arm: search the question exactly as the dataset states it."""
    return Production(queries=[question])


def interpreter_producer(client: Any, *, first_only: bool = False) -> Producer:
    """Build a producer backed by LLMQueryInterpreter over ``client``.

    Args:
        client: An LLMClient (or anything with a compatible ``complete``).
        first_only: Keep only the first rewrite, isolating phrasing quality
            from the breadth advantage of issuing several queries.

    Returns:
        A Producer whose ``Production.fallback`` marks rows where the arm
        collapsed onto the control.

    Fallback detection is a heuristic: ``interpret`` backfills ``[question]``
    both when parsing failed twice and when the model legitimately echoed the
    question back, and the two are indistinguishable from outside. It
    therefore OVER-reports. That is the safe direction -- it makes a run look
    inconclusive rather than reporting a tie that was really a dead
    interpreter -- but a high fallback count should be confirmed against the
    stored raw output before being read as breakage.
    """
    interpreter = LLMQueryInterpreter(client)

    def produce(question: str) -> Production:
        interpreted = interpreter.interpret(question)
        queries = list(interpreted.queries)

        # interpret() backfills [question] on a parse failure AND on an empty
        # queries list; both collapse this arm onto the control, so both are
        # reported as a fallback.
        fallback = queries == [question]
        if not queries:
            queries = [question]
            fallback = True
        if first_only:
            queries = queries[:1]

        return Production(
            queries=queries,
            intent=interpreted.intent,
            strategy_hint=interpreted.strategy_hint,
            fallback=fallback,
            raw=interpreted.model_dump(),
        )

    return produce
