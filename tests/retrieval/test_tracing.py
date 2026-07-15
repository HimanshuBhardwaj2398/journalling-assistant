"""Per-stage retrieval spans + generation tracing through the tracer port."""

import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from langchain_core.documents import Document

from config.settings import LLMSettings
from observability.langfuse import LangfuseTracer
from retrieval.llm_client import LLMClient
from retrieval.query import RetrievalEngine, RetrievalStrategy


class FakeLangfuseObservation:
    def __init__(self):
        self.updates = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def update(self, **kwargs):
        self.updates.append(kwargs)


class FakeLangfuseClient:
    def __init__(self):
        self.flush_calls = 0
        self.observations = []

    def start_as_current_observation(self, **kwargs):
        observation = FakeLangfuseObservation()
        observation.start_kwargs = kwargs
        self.observations.append(observation)
        return observation

    def get_current_trace_id(self):
        return "trace-123"

    def get_trace_url(self, *_args):
        return "https://langfuse.local/trace/trace-123"

    def flush(self):
        self.flush_calls += 1


def _span_names(client):
    return [o.start_kwargs["name"] for o in client.observations]


def test_observe_passes_as_type_through():
    client = FakeLangfuseClient()
    tracer = LangfuseTracer(client=client)
    with tracer.observe(name="llm.completion", as_type="generation"):
        pass
    assert client.observations[0].start_kwargs["as_type"] == "generation"
    # plain spans don't send as_type at all
    with tracer.observe(name="plain.span"):
        pass
    assert "as_type" not in client.observations[1].start_kwargs


def test_llm_client_records_generation_with_usage(monkeypatch):
    import retrieval.llm_client as llm_module

    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="  the answer  "))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
    )
    monkeypatch.setattr(llm_module.litellm, "completion", lambda **kwargs: response)

    client = FakeLangfuseClient()
    llm = LLMClient(settings=LLMSettings(provider="groq"), tracer=LangfuseTracer(client=client))
    text = llm.complete(messages=[{"role": "user", "content": "q"}])

    assert text == "the answer"
    generation = client.observations[0]
    assert generation.start_kwargs["as_type"] == "generation"
    merged = {k: v for update in generation.updates for k, v in update.items()}
    assert merged["usage_details"] == {"input": 11, "output": 7}
    assert merged["model"] == llm.model_id


class FakeSemanticRetriever:
    def __init__(self, docs):
        self._docs = docs

    def invoke(self, _query):
        return self._docs


class FakeVectorStore:
    def __init__(self, docs):
        self._docs = docs

    def as_retriever(self, **_kwargs):
        return FakeSemanticRetriever(self._docs)

    def similarity_search_with_score(self, _query, k=5):
        return [(doc, 0.9) for doc in self._docs[:k]]


def _engine(client, docs):
    engine = RetrievalEngine(
        collection_name="test",
        db_url="postgresql://user:pass@localhost/testdb",
        embedding_model="voyage-3.5",
        tracer=LangfuseTracer(client=client),
    )
    engine._vector_store = FakeVectorStore(docs)
    return engine


def test_hybrid_search_emits_stage_spans(monkeypatch):
    client = FakeLangfuseClient()
    docs = [Document(page_content="a", metadata={"uuid": "u1", "document_id": 1})]
    engine = _engine(client, docs)
    monkeypatch.setattr(
        engine,
        "_fts_search",
        lambda query, k=5: [
            Document(
                page_content="b",
                metadata={"uuid": "u2", "document_id": 2, "_fts_score": 1.0},
            )
        ],
    )
    monkeypatch.setattr(engine, "_enrich_with_document_info", lambda results: None)

    response = engine.search("q", strategy=RetrievalStrategy.HYBRID, k=2)

    assert len(response.results) == 2
    assert _span_names(client) == [
        "retrieval.search",
        "retrieval.semantic",
        "retrieval.fts",
        "retrieval.fusion",
        "retrieval.enrich",
    ]
    assert client.flush_calls == 1  # only the root observation flushes


def test_similarity_search_emits_semantic_and_enrich_spans(monkeypatch):
    client = FakeLangfuseClient()
    docs = [Document(page_content="a", metadata={"uuid": "u1", "document_id": 1})]
    engine = _engine(client, docs)
    monkeypatch.setattr(engine, "_enrich_with_document_info", lambda results: None)

    engine.search("q", strategy=RetrievalStrategy.SIMILARITY, k=1)

    assert _span_names(client) == [
        "retrieval.search",
        "retrieval.semantic",
        "retrieval.enrich",
    ]
