"""QueryInterpreter port + LLM-backed implementation (seam design §3).

Sits above retrieval: retrievers never see the raw user message.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from agent.parsing import parse_structured_with_retry
from agent.state import InterpretedQuery

if TYPE_CHECKING:
    from retrieval.llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You classify and rewrite user messages for a search system over early Buddhist texts (the Pali Canon).

Return ONLY a JSON object:
{
  "intent": "corpus_question" | "other",
  "queries": ["1-3 short, self-contained search queries"],
  "strategy_hint": null | "similarity" | "mmr" | "threshold" | "hybrid"
}

Rules:
- "corpus_question": the user asks about meditation, Buddhist concepts, practices, or texts.
- "other": greetings, small talk, or questions unrelated to the corpus.
- Rewrite follow-ups into self-contained queries using the conversation history.
- Leave strategy_hint null unless the user explicitly asks for keyword/exact matching (then "hybrid").
"""


@runtime_checkable
class QueryInterpreter(Protocol):
    def interpret(
        self, user_message: str, history: Optional[list[dict[str, str]]] = None
    ) -> InterpretedQuery: ...


class LLMQueryInterpreter:
    """Small-model interpreter with one validation-feedback retry."""

    def __init__(self, client: "LLMClient") -> None:
        self._client = client

    def interpret(
        self, user_message: str, history: Optional[list[dict[str, str]]] = None
    ) -> InterpretedQuery:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if history:
            # Known tradeoff: flattened history could spoof turns via injected
            # "role:" prefixes in content; acceptable v1 blast radius.
            transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
            messages.append({"role": "user", "content": f"Conversation so far:\n{transcript}"})
        messages.append({"role": "user", "content": f"User message: {user_message}"})

        interpreted = parse_structured_with_retry(self._client, messages, InterpretedQuery)
        if interpreted is None:
            logger.warning("interpreter failed twice; falling back to raw message")
            interpreted = InterpretedQuery(intent="corpus_question", queries=[])
        if not interpreted.queries and interpreted.intent == "corpus_question":
            # Backfill only for corpus questions: for intent="other" the raw
            # message must not leak toward retrieval (seam invariant).
            interpreted = interpreted.model_copy(update={"queries": [user_message]})
        return interpreted
