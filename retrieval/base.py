"""Retriever port: the seam every retrieval capability plugs into.

Future adapters (reranking, query expansion, concept/graph retrieval) implement
or wrap this protocol; the eval harness and UI consume it. See
docs/plans/2026-07-13-retrieval-eval-strategy-design.md §7.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from retrieval.query import SearchResult


@runtime_checkable
class Retriever(Protocol):
    name: str

    def retrieve(self, query: str, k: int = 5) -> list[SearchResult]: ...
