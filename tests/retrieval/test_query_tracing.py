"""Tests for retrieval query tracing metadata."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from observability.langfuse import LangfuseTracer
from retrieval.query import RetrievalEngine, RetrievalStrategy, SearchResult


class FakeLangfuseObservation:
    """Context-managed fake Langfuse observation."""

    def __init__(self):
        self.updates = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeLangfuseClient:
    """Fake Langfuse client for retrieval tracing tests."""

    def __init__(self):
        self.flush_calls = 0
        self.observations = []

    def start_as_current_observation(self, **kwargs):
        observation = FakeLangfuseObservation()
        observation.start_kwargs = kwargs
        self.observations.append(observation)
        return observation

    def get_current_trace_id(self):
        return "trace-search-123"

    def get_trace_url(self, *_args):
        return "https://langfuse.local/trace/trace-search-123"

    def flush(self):
        self.flush_calls += 1


def test_retrieval_engine_attaches_langfuse_trace(monkeypatch):
    fake_client = FakeLangfuseClient()
    engine = RetrievalEngine(tracer=LangfuseTracer(client=fake_client))
    monkeypatch.setattr(
        engine,
        "_similarity_search",
        lambda query, **kwargs: [
            SearchResult(
                text="Mindfulness keeps the mind steady.",
                source_title="Middle Discourses",
                document_id=4,
                chunk_index=2,
                rank=1,
            )
        ],
    )
    monkeypatch.setattr(engine, "_enrich_with_document_info", lambda results: None)

    response = engine.search("What is mindfulness?", strategy=RetrievalStrategy.SIMILARITY)

    assert response.trace is not None
    assert response.trace.langfuse_trace_id == "trace-search-123"
    assert response.trace.langfuse_trace_url == "https://langfuse.local/trace/trace-search-123"
    assert fake_client.flush_calls == 1
