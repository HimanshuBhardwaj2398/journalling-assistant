"""Typed state for the agent graph.

"user_message" (raw) and "queries" (retrieval rewrites) are distinct by
design — retrievers never see the raw user message (seam design §3).
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

from retrieval.query import RetrievalStrategy, SearchResult

_VALID_STRATEGIES = {s.value for s in RetrievalStrategy}


class InterpretedQuery(BaseModel):
    """Output of the QueryInterpreter: intent + retrieval rewrites."""

    intent: Literal["corpus_question", "other"] = "corpus_question"
    queries: list[str] = []
    strategy_hint: Optional[str] = None

    @field_validator("intent", mode="before")
    @classmethod
    def coerce_intent(cls, v: Any) -> str:
        return v if v in ("corpus_question", "other") else "other"

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
    messages: list[dict[str, str]] = []  # prior turns, chat format
    interpreted: Optional[InterpretedQuery] = None
    retrieved: list[SearchResult] = []
    grade: Optional[SufficiencyGrade] = None
    iterations: int = 0
    outcome: Optional[Literal["answer", "clarify", "direct"]] = None
    final_text: Optional[str] = None
    citations: list[Any] = []  # AnswerCitation list when outcome == "answer"
