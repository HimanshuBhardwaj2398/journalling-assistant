"""Typed state for the agent graph.

"user_message" (raw) and "queries" (retrieval rewrites) are distinct by
design — retrievers never see the raw user message (seam design §3).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from retrieval.query import RetrievalStrategy, SearchResult

_VALID_STRATEGIES = {s.value for s in RetrievalStrategy}

Outcome = Literal["answer", "clarify", "direct"]


class InterpretedQuery(BaseModel):
    """Output of the QueryInterpreter: intent + retrieval rewrites."""

    intent: Literal["corpus_question", "other"] = "corpus_question"
    queries: list[str] = []
    strategy_hint: Optional[str] = None

    @field_validator("intent", mode="before")
    @classmethod
    def coerce_intent(cls, v: Any) -> str:
        if isinstance(v, str):
            v = v.lower().strip()
        return v if v in ("corpus_question", "other") else "other"

    @field_validator("queries", mode="before")
    @classmethod
    def coerce_queries(cls, v: Any) -> list[str]:
        """Tolerate common small-LLM output shapes instead of failing the parse."""
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return []
        return [q.strip() for q in v if isinstance(q, str) and q.strip()]

    @field_validator("strategy_hint", mode="before")
    @classmethod
    def validate_strategy(cls, v: Any) -> Optional[str]:
        if not isinstance(v, str):
            return None
        normalized = v.lower().strip()
        return normalized if normalized in _VALID_STRATEGIES else None


class SufficiencyGrade(BaseModel):
    """The decider's verdict on whether retrieved context can answer."""

    sufficient: bool
    missing_info: Optional[str] = None
    clarifying_question: Optional[str] = None


class AgentState(BaseModel):
    """Full graph state. Nodes return partial dict updates."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    user_message: str
    # PRIOR turns only, chat format. The in-flight user_message must NOT be
    # included here — nodes append it themselves (see respond_direct_node).
    messages: list[dict[str, str]] = []
    interpreted: Optional[InterpretedQuery] = None
    retrieved: list[SearchResult] = []
    grade: Optional[SufficiencyGrade] = None
    iterations: int = 0
    outcome: Optional[Outcome] = None
    final_text: Optional[str] = None
    citations: list[Any] = []  # AnswerCitation list when outcome == "answer"
