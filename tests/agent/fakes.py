"""Shared fakes for the agent test suite.

Canonical home for all agent-test doubles. Graph tests (Task 7) import
from here too — never from other test modules.
"""

from contextlib import contextmanager

from retrieval.answering import AnswerResponse, AnswerTrace
from retrieval.query import SearchResult


class FakeLLMClient:
    """Scripted LLM client: pops responses in order, records every call.

    A response that is an Exception instance is raised instead of returned,
    so tests can script transport failures.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.max_tokens_seen = []

    def complete(self, messages, temperature=0.0, max_tokens=200):
        self.calls.append(messages)
        self.max_tokens_seen.append(max_tokens)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeTracer:
    """Records every observe() call and every handle.update() per span.

    Each entry in ``spans`` is ``{"kwargs": <observe kwargs>, "updates":
    [<update kwargs>, ...]}`` so tests can assert both span names and what
    the node reported as output.
    """

    def __init__(self):
        self.spans = []

    def observe(self, **kwargs):
        record = {"kwargs": kwargs, "updates": []}
        self.spans.append(record)

        @contextmanager
        def _cm():
            class Handle:
                def update(self, **kw):
                    record["updates"].append(kw)

            yield Handle()

        return _cm()


class FakeRetriever:
    """Returns scripted results per query string; records (query, k) calls."""

    def __init__(self, results_by_query):
        self.results_by_query = results_by_query
        self.name = "hybrid"
        self.calls = []

    def retrieve(self, query, k=5):
        self.calls.append((query, k))
        return self.results_by_query.get(query, [])


class FakeInterpreter:
    """Always returns the same InterpretedQuery."""

    def __init__(self, result):
        self.result = result

    def interpret(self, user_message, history=None):
        return self.result


class FakeAnswerService:
    """Canned grounded answer; mirrors the real service's empty-input contract."""

    def answer(self, query, search_results):
        if not search_results:
            # GroundedAnswerService raises here too (retrieval/answering.py);
            # keeping the fake honest so nodes can't paper over empty context.
            raise ValueError("Cannot synthesize an answer without search results.")
        return AnswerResponse(
            query=query,
            answer="Jhana is absorption. [1]",
            citations=[],
            trace=AnswerTrace(
                model_id="fake",
                context_chunk_count=len(search_results),
                context_char_count=0,
                duration_ms=1.0,
                langfuse_trace_id=None,
                langfuse_trace_url=None,
                system_prompt="",
                user_prompt="",
            ),
        )


def make_result(uuid, text="chunk text"):
    return SearchResult(text=text, chunk_uuid=uuid, rank=1)
