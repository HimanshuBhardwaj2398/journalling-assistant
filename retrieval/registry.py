"""Registry of named retrieval strategies conforming to the Retriever port.

Consumed by the eval harness (iterates all strategies), the Streamlit
playground, and the future API layer. New adapters register here.
"""

from __future__ import annotations

from typing import Optional

from retrieval.query import RetrievalEngine, RetrievalStrategy, SearchResult


class EngineRetriever:
    """Adapts one RetrievalEngine strategy to the Retriever protocol."""

    def __init__(self, name: str, engine: RetrievalEngine, strategy: RetrievalStrategy):
        self.name = name
        self._engine = engine
        self._strategy = strategy

    def retrieve(self, query: str, k: int = 5) -> list[SearchResult]:
        return self._engine.search(query, strategy=self._strategy, k=k).results


def default_retrievers(engine: Optional[RetrievalEngine] = None) -> dict[str, EngineRetriever]:
    """All registered strategies, sharing a single engine (one vector-store connection)."""
    engine = engine or RetrievalEngine()
    return {s.value: EngineRetriever(s.value, engine, s) for s in RetrievalStrategy}
