"""Grounded answer synthesis on top of retrieved chunks."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from observability.langfuse import LangfuseTracer, get_langfuse_tracer
from retrieval.llm_client import EvalLLMClient
from retrieval.query import SearchResult


def _extract_header_paths(metadata: dict | None) -> list[str]:
    """Return a normalized list of header paths from chunk metadata."""
    if not isinstance(metadata, dict):
        return []

    paths: list[str] = []

    def add(raw: object) -> None:
        if not isinstance(raw, str):
            return
        cleaned = " > ".join(part.strip() for part in raw.split(">") if part.strip())
        if cleaned and cleaned not in paths:
            paths.append(cleaned)

    all_header_paths = metadata.get("all_header_paths", [])
    if isinstance(all_header_paths, str):
        add(all_header_paths)
    elif isinstance(all_header_paths, list):
        for path in all_header_paths:
            add(path)

    add(metadata.get("header_path"))
    add(metadata.get("section_path"))

    if not paths:
        legacy_headers = []
        for level in range(1, 7):
            value = metadata.get(f"Header {level}")
            if isinstance(value, str) and value.strip():
                legacy_headers.append(value.strip())
        if legacy_headers:
            paths.append(" > ".join(legacy_headers))

    return paths


@dataclass
class AnswerCitation:
    """Chunk context supplied to the answering step."""

    label: str
    source_title: str | None
    document_id: int | None
    chunk_index: int | None
    chunk_uuid: str | None
    header_path: str | None
    excerpt: str


@dataclass
class AnswerTrace:
    """Prompt/latency metadata for answer generation."""

    model_id: str
    context_chunk_count: int
    context_char_count: int
    duration_ms: float
    langfuse_trace_id: Optional[str]
    langfuse_trace_url: Optional[str]
    system_prompt: str
    user_prompt: str


@dataclass
class AnswerResponse:
    """Grounded answer plus prompt trace."""

    query: str
    answer: str
    citations: List[AnswerCitation]
    trace: AnswerTrace


class GroundedAnswerService:
    """Synthesize an answer from retrieved chunks with inline citation labels."""

    SYSTEM_PROMPT = (
        "You answer questions using only the provided retrieved chunks from the meditation "
        "knowledge base. Cite supporting chunks inline using square bracket references like "
        "[1] or [2]. If the retrieved evidence is insufficient, say you do not have enough "
        "evidence from the retrieved sources."
    )

    def __init__(
        self,
        llm_client: EvalLLMClient | None = None,
        tracer: LangfuseTracer | None = None,
        max_chunks: int = 4,
        max_chunk_chars: int = 1200,
        max_excerpt_chars: int = 240,
    ) -> None:
        self._llm_client = llm_client or EvalLLMClient()
        self._tracer = tracer or get_langfuse_tracer()
        self._max_chunks = max_chunks
        self._max_chunk_chars = max_chunk_chars
        self._max_excerpt_chars = max_excerpt_chars

    def answer(self, query: str, search_results: Sequence[SearchResult]) -> AnswerResponse:
        """Generate a grounded answer from retrieved chunks."""
        if not query.strip():
            raise ValueError("Query must not be empty.")
        if not search_results:
            raise ValueError("Cannot synthesize an answer without search results.")

        selected_results = list(search_results[: self._max_chunks])
        citations = [self._build_citation(result, idx) for idx, result in enumerate(selected_results, 1)]
        user_prompt = self._build_user_prompt(query=query, search_results=selected_results)

        with self._tracer.observe(
            name="retrieval.answer",
            input={
                "query": query,
                "context_chunk_count": len(selected_results),
                "model_id": self._llm_client.model_id,
            },
            metadata={
                "sources": [
                    {
                        "document_id": result.document_id,
                        "source_title": result.source_title,
                        "chunk_index": result.chunk_index,
                        "chunk_uuid": result.chunk_uuid,
                    }
                    for result in selected_results
                ]
            },
        ) as observation:
            started = time.perf_counter()
            try:
                answer = self._llm_client.complete(
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=700,
                )
            except Exception as exc:
                observation.update(
                    output={"error": str(exc)},
                    metadata={"status": "failed", "model_id": self._llm_client.model_id},
                    status_message=str(exc),
                    model=self._llm_client.model_id,
                )
                raise

            duration_ms = (time.perf_counter() - started) * 1000
            observation.update(
                output={"answer": answer},
                metadata={"status": "completed", "context_chunk_count": len(selected_results)},
                model=self._llm_client.model_id,
                model_parameters={"temperature": 0.1, "max_tokens": 700},
            )

        return AnswerResponse(
            query=query,
            answer=answer,
            citations=citations,
            trace=AnswerTrace(
                model_id=self._llm_client.model_id,
                context_chunk_count=len(selected_results),
                context_char_count=sum(len(result.text) for result in selected_results),
                duration_ms=duration_ms,
                langfuse_trace_id=observation.trace_id,
                langfuse_trace_url=observation.trace_url,
                system_prompt=self.SYSTEM_PROMPT,
                user_prompt=user_prompt,
            ),
        )

    def _build_user_prompt(self, query: str, search_results: Sequence[SearchResult]) -> str:
        """Assemble the numbered context blocks shown to the answering model."""
        context_blocks = [
            self._build_context_block(result=result, label=idx)
            for idx, result in enumerate(search_results, start=1)
        ]
        joined_context = "\n\n".join(context_blocks)
        return (
            f"Query:\n{query.strip()}\n\n"
            "Retrieved chunks:\n"
            f"{joined_context}\n\n"
            "Write a concise answer grounded only in the retrieved chunks. "
            "Use inline citations like [1] and [2]."
        )

    def _build_context_block(self, result: SearchResult, label: int) -> str:
        """Format a single retrieved chunk for prompt context."""
        header_paths = _extract_header_paths(result.metadata)
        source_title = result.source_title or f"Document {result.document_id or 'unknown'}"
        chunk_label = result.chunk_index if result.chunk_index is not None else "unknown"
        header_preview = ", ".join(header_paths[:2]) if header_paths else "(no header path)"
        chunk_text = result.text.strip()
        if len(chunk_text) > self._max_chunk_chars:
            chunk_text = chunk_text[: self._max_chunk_chars].rstrip() + "..."

        return (
            f"[{label}] Source: {source_title}\n"
            f"Chunk index: {chunk_label}\n"
            f"Header path: {header_preview}\n"
            f"Text:\n{chunk_text}"
        )

    def _build_citation(self, result: SearchResult, label: int) -> AnswerCitation:
        """Create a citation record for UI display."""
        header_paths = _extract_header_paths(result.metadata)
        excerpt = result.text.strip().replace("\n", " ")
        if len(excerpt) > self._max_excerpt_chars:
            excerpt = excerpt[: self._max_excerpt_chars].rstrip() + "..."

        return AnswerCitation(
            label=f"[{label}]",
            source_title=result.source_title,
            document_id=result.document_id,
            chunk_index=result.chunk_index,
            chunk_uuid=result.chunk_uuid,
            header_path=header_paths[0] if header_paths else None,
            excerpt=excerpt,
        )
