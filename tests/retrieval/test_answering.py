"""Tests for grounded answer synthesis helpers."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
os.environ["DEBUG"] = "false"

from observability.langfuse import LangfuseTracer
from retrieval.answering import GroundedAnswerService
from retrieval.query import SearchResult


class FakeLLMClient:
    """Simple fake LLM client for deterministic answer tests."""

    model_id = "fake/provider-model"

    def __init__(self):
        self.calls = []

    def complete(self, messages, temperature=0.0, max_tokens=200):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return "Craving conditions suffering according to the retrieved passages. [1]"


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
    """Tiny fake Langfuse client used for tracing tests."""

    def __init__(self):
        self.flush_calls = 0
        self.observations = []

    def start_as_current_observation(self, **kwargs):
        observation = FakeLangfuseObservation()
        observation.start_kwargs = kwargs
        self.observations.append(observation)
        return observation

    def get_current_trace_id(self):
        return "trace-answer-123"

    def get_trace_url(self, *_args):
        return "https://langfuse.local/trace/trace-answer-123"

    def flush(self):
        self.flush_calls += 1


def test_grounded_answer_service_builds_prompt_and_citations(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    client = FakeLLMClient()
    service = GroundedAnswerService(llm_client=client, max_chunks=2, max_chunk_chars=80)
    results = [
        SearchResult(
            text="Craving leads to renewed becoming and suffering through attachment.",
            score=0.88,
            chunk_uuid="uuid-1",
            document_id=7,
            source_title="Linked Discourses",
            chunk_index=3,
            metadata={"all_header_paths": ["SN > Craving > Sutta 1"]},
            rank=1,
        ),
        SearchResult(
            text="Mindfulness reveals the arising and passing of feeling.",
            score=0.71,
            chunk_uuid="uuid-2",
            document_id=8,
            source_title="Middle Discourses",
            chunk_index=5,
            metadata={"Header 1": "MN", "Header 2": "Mindfulness"},
            rank=2,
        ),
    ]

    response = service.answer("How does craving lead to suffering?", results)

    assert response.answer.endswith("[1]")
    assert response.citations[0].label == "[1]"
    assert response.citations[0].header_path == "SN > Craving > Sutta 1"
    assert response.trace.model_id == "fake/provider-model"
    assert "How does craving lead to suffering?" in response.trace.user_prompt
    assert "[1] Source: Linked Discourses" in response.trace.user_prompt
    assert "[2] Source: Middle Discourses" in response.trace.user_prompt


def test_grounded_answer_service_requires_search_results(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    service = GroundedAnswerService(llm_client=FakeLLMClient())

    try:
        service.answer("What is impermanence?", [])
    except ValueError as exc:
        assert "without search results" in str(exc)
    else:
        raise AssertionError("Expected ValueError when answering without search results")


def test_grounded_answer_service_includes_langfuse_trace(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost/testdb")
    client = FakeLLMClient()
    tracer = LangfuseTracer(client=FakeLangfuseClient())
    service = GroundedAnswerService(llm_client=client, tracer=tracer)

    response = service.answer(
        "What is mindfulness?",
        [
            SearchResult(
                text="Mindfulness guards the mind.",
                document_id=5,
                source_title="Middle Discourses",
                chunk_index=1,
                chunk_uuid="uuid-1",
                rank=1,
            )
        ],
    )

    assert response.trace.langfuse_trace_id == "trace-answer-123"
    assert response.trace.langfuse_trace_url == "https://langfuse.local/trace/trace-answer-123"
