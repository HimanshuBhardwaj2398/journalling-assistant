"""Registry adapts RetrievalEngine strategies to the Retriever protocol."""

from retrieval.query import RetrievalStrategy, SearchResponse, SearchResult
from retrieval.registry import EngineRetriever, default_retrievers


class StubEngine:
    def __init__(self):
        self.calls = []

    def search(self, query, strategy, k=5, **kwargs):
        self.calls.append((query, strategy, k))
        results = [SearchResult(text="t", chunk_uuid="u1", document_id=1, rank=1)]
        return SearchResponse(query=query, strategy=strategy, results=results)


def test_engine_retriever_delegates_and_unwraps():
    engine = StubEngine()
    retriever = EngineRetriever("hybrid", engine, RetrievalStrategy.HYBRID)
    results = retriever.retrieve("what is mindfulness?", k=7)
    assert engine.calls == [("what is mindfulness?", RetrievalStrategy.HYBRID, 7)]
    assert [r.chunk_uuid for r in results] == ["u1"]
    assert retriever.name == "hybrid"


def test_default_retrievers_covers_all_strategies_sharing_one_engine():
    engine = StubEngine()
    retrievers = default_retrievers(engine=engine)
    assert set(retrievers) == {"similarity", "mmr", "threshold", "hybrid"}
    for r in retrievers.values():
        r.retrieve("q", k=2)
    assert len(engine.calls) == 4  # all four went through the same engine
