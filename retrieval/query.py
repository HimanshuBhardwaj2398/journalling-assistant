"""
Core retrieval engine for the meditation knowledge base.

Provides a unified interface for multiple search strategies over existing
pgvector embeddings. Designed to be imported by the RAG pipeline, Streamlit UI,
and future API endpoints.

Usage:
    from retrieval.query import RetrievalEngine, RetrievalStrategy

    engine = RetrievalEngine()
    results = engine.search("what is mindfulness?", strategy=RetrievalStrategy.HYBRID, k=5)
    for r in results:
        print(f"[{r.score:.3f}] {r.text[:100]}... (from {r.source_title})")
"""

import enum
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from langchain_community.vectorstores.pgvector import PGVector
from langchain_core.documents import Document
from langchain_voyageai import VoyageAIEmbeddings
from sqlalchemy import text

from db.database import session_scope
from observability.langfuse import LangfuseTracer, get_langfuse_tracer

logger = logging.getLogger(__name__)


class RetrievalStrategy(enum.Enum):
    """Available retrieval strategies."""

    SIMILARITY = "similarity"
    MMR = "mmr"
    THRESHOLD = "threshold"
    HYBRID = "hybrid"


@dataclass
class SearchResult:
    """A single search result with provenance tracking.

    Attributes:
        text: The chunk text content.
        score: Relevance score (higher = more relevant). None for strategies
               that don't produce raw scores (MMR, hybrid).
        chunk_uuid: UUID linking to langchain_pg_embedding and chunks tables.
        document_id: Parent document ID in the documents table.
        source_title: Title of the source document.
        chunk_index: Position of this chunk within the parent document.
        metadata: Full chunk metadata (headers, semantic boundaries, etc.).
        rank: Position in result list (1-indexed).
    """

    text: str
    score: Optional[float] = None
    chunk_uuid: Optional[str] = None
    document_id: Optional[int] = None
    source_title: Optional[str] = None
    chunk_index: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    rank: int = 0


@dataclass
class SearchResponse:
    """Container for search results with metadata about the search itself."""

    query: str
    strategy: RetrievalStrategy
    results: List[SearchResult]
    trace: Optional["SearchTrace"] = None
    total_results: int = 0

    def __post_init__(self):
        self.total_results = len(self.results)


@dataclass
class SearchTrace:
    """Debug-friendly metadata describing how a search was executed."""

    collection_name: str
    embedding_model: str
    requested_k: int
    fetch_k: int
    score_threshold: float
    started_at: str
    duration_ms: float
    total_results: int
    fts_query_used: bool = False
    langfuse_trace_id: Optional[str] = None
    langfuse_trace_url: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _minmax_normalize(scores: list[float]) -> list[float]:
    """Normalize a list of scores to [0, 1]. Returns 0.5 for uniform inputs."""
    min_s, max_s = min(scores), max(scores)
    rng = max_s - min_s
    if rng == 0:
        return [0.5] * len(scores)
    return [(s - min_s) / rng for s in scores]


def _doc_key(doc: Document) -> str:
    """Stable dedup key: UUID when present, SHA-256 of content otherwise."""
    uuid = doc.metadata.get("uuid")
    if uuid:
        return str(uuid)
    return hashlib.sha256(doc.page_content.encode()).hexdigest()


class RetrievalEngine:
    """Unified search interface over the meditation knowledge base.

    Wraps the existing VectorStoreManager and adds PostgreSQL FTS for hybrid search.
    Supports four retrieval strategies: similarity, MMR, threshold, and hybrid.

    The engine lazily initializes its components (vector store, BM25 index)
    on first use so construction is cheap.
    """

    def __init__(
        self,
        collection_name: str = "buddhist_texts",
        db_url: Optional[str] = None,
        embedding_model: str = "voyage-3.5",
        tracer: Optional[LangfuseTracer] = None,
    ):
        self._collection_name = collection_name
        self._db_url = db_url or os.getenv("DB_URL") or os.getenv("DATABASE_URL")
        self._embedding_model = embedding_model
        self._tracer = tracer or get_langfuse_tracer()

        # Lazily initialized
        self._vector_store: Optional[PGVector] = None
        self._all_chunks: None = None  # kept for test assertions; never populated
        self._embeddings: Optional[VoyageAIEmbeddings] = None

    # ------------------------------------------------------------------
    # Lazy initialization
    # ------------------------------------------------------------------

    @property
    def embeddings(self) -> VoyageAIEmbeddings:
        if self._embeddings is None:
            self._embeddings = VoyageAIEmbeddings(model=self._embedding_model)
        return self._embeddings

    @property
    def vector_store(self) -> PGVector:
        if self._vector_store is None:
            self._vector_store = PGVector(
                connection_string=self._db_url,
                embedding_function=self.embeddings,
                collection_name=self._collection_name,
                use_jsonb=True,
            )
            logger.info(f"Connected to vector store: {self._collection_name}")
        return self._vector_store

    def _bm25_search(self, query: str, k: int = 5) -> List[Document]:
        """Full-text search using PostgreSQL tsvector (replaces in-memory BM25)."""
        with session_scope() as session:
            result = session.execute(
                text(
                    """
                    SELECT c.uuid, c.chunk_text, c.chunk_metadata, c.document_id,
                           ts_rank(to_tsvector('english', c.chunk_text),
                                   plainto_tsquery('english', :query)) AS fts_score
                    FROM chunks c
                    WHERE to_tsvector('english', c.chunk_text) @@ plainto_tsquery('english', :query)
                    ORDER BY fts_score DESC
                    LIMIT :k
                    """
                ),
                {"query": query, "k": k},
            )
            rows = result.fetchall()

        return [
            Document(
                page_content=row[1],
                metadata={
                    **(row[2] or {}),
                    "uuid": row[0],
                    "document_id": row[3],
                    "_fts_score": float(row[4]),
                },
            )
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Search strategies
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
        k: int = 5,
        score_threshold: float = 0.5,
        fetch_k: int = 20,
    ) -> SearchResponse:
        """Run a search using the specified strategy.

        Args:
            query: Natural language search query.
            strategy: Which retrieval strategy to use.
            k: Number of results to return.
            score_threshold: Minimum score for threshold strategy.
            fetch_k: Candidate pool size for MMR.

        Returns:
            SearchResponse with ranked results.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        started = time.perf_counter()
        strategy_map = {
            RetrievalStrategy.SIMILARITY: self._similarity_search,
            RetrievalStrategy.MMR: self._mmr_search,
            RetrievalStrategy.THRESHOLD: self._threshold_search,
            RetrievalStrategy.HYBRID: self._hybrid_search,
        }

        with self._tracer.observe(
            name="retrieval.search",
            input={
                "query": query,
                "strategy": strategy.value,
                "k": k,
                "fetch_k": fetch_k,
                "score_threshold": score_threshold,
            },
            metadata={
                "collection_name": self._collection_name,
                "embedding_model": self._embedding_model,
            },
        ) as observation:
            try:
                search_fn = strategy_map[strategy]
                results = search_fn(query, k=k, score_threshold=score_threshold, fetch_k=fetch_k)

                # Enrich results with document titles
                self._enrich_with_document_info(results)
            except Exception as exc:
                observation.update(
                    output={"error": str(exc)},
                    metadata={"status": "failed"},
                    status_message=str(exc),
                )
                raise

            notes = self._build_trace_notes(strategy, score_threshold=score_threshold)
            observation.update(
                output={
                    "total_results": len(results),
                    "top_results": [
                        {
                            "rank": result.rank,
                            "source_title": result.source_title,
                            "document_id": result.document_id,
                            "chunk_index": result.chunk_index,
                            "score": result.score,
                        }
                        for result in results[:5]
                    ],
                },
                metadata={
                    "status": "completed",
                    "fts_query_used": strategy == RetrievalStrategy.HYBRID,
                },
            )

            trace = SearchTrace(
                collection_name=self._collection_name,
                embedding_model=self._embedding_model,
                requested_k=k,
                fetch_k=fetch_k,
                score_threshold=score_threshold,
                started_at=started_at,
                duration_ms=(time.perf_counter() - started) * 1000,
                total_results=len(results),
                fts_query_used=strategy == RetrievalStrategy.HYBRID,
                langfuse_trace_id=observation.trace_id,
                langfuse_trace_url=observation.trace_url,
                notes=notes,
            )
            return SearchResponse(query=query, strategy=strategy, results=results, trace=trace)

    def _similarity_search(self, query: str, k: int = 5, **kwargs) -> List[SearchResult]:
        """Top-K similarity search using pgvector."""
        raw = self.vector_store.similarity_search_with_score(query, k=k)
        return [
            SearchResult(
                text=doc.page_content,
                score=float(score),
                chunk_uuid=doc.metadata.get("uuid"),
                document_id=doc.metadata.get("document_id")
                or doc.metadata.get("original_doc_id"),
                metadata=doc.metadata,
                rank=i + 1,
            )
            for i, (doc, score) in enumerate(raw)
        ]

    def _mmr_search(self, query: str, k: int = 5, fetch_k: int = 20, **kwargs) -> List[SearchResult]:
        """Maximal Marginal Relevance search for diverse results."""
        raw = self.vector_store.max_marginal_relevance_search(query, k=k, fetch_k=fetch_k)
        return [
            SearchResult(
                text=doc.page_content,
                score=None,
                chunk_uuid=doc.metadata.get("uuid"),
                document_id=doc.metadata.get("document_id")
                or doc.metadata.get("original_doc_id"),
                metadata=doc.metadata,
                rank=i + 1,
            )
            for i, doc in enumerate(raw)
        ]

    def _threshold_search(
        self, query: str, k: int = 5, score_threshold: float = 0.5, **kwargs
    ) -> List[SearchResult]:
        """Similarity search filtered by minimum score."""
        retriever = self.vector_store.as_retriever(
            search_type="similarity_score_threshold",
            search_kwargs={"k": k, "score_threshold": score_threshold},
        )
        raw = retriever.invoke(query)
        return [
            SearchResult(
                text=doc.page_content,
                score=None,
                chunk_uuid=doc.metadata.get("uuid"),
                document_id=doc.metadata.get("document_id")
                or doc.metadata.get("original_doc_id"),
                metadata=doc.metadata,
                rank=i + 1,
            )
            for i, doc in enumerate(raw)
        ]

    def _hybrid_search(self, query: str, k: int = 5, **kwargs) -> List[SearchResult]:
        """Hybrid FTS + semantic search with reciprocal rank fusion."""
        semantic_retriever = self.vector_store.as_retriever(search_kwargs={"k": k})
        semantic_results = semantic_retriever.invoke(query)
        fts_results = self._bm25_search(query, k=k)

        # Normalize FTS scores before fusion so they're on the same [0,1] scale
        fts_scores = [doc.metadata.get("_fts_score", 0.0) for doc in fts_results]
        if fts_scores:
            normed = _minmax_normalize(fts_scores)
            for doc, norm_score in zip(fts_results, normed):
                doc.metadata["_fts_score"] = norm_score

        fused = self._reciprocal_rank_fusion(
            [semantic_results, fts_results],
            weights=[0.6, 0.4],
            k=k,
        )

        return [
            SearchResult(
                text=doc.page_content,
                score=rrf_score,
                chunk_uuid=doc.metadata.get("uuid"),
                document_id=doc.metadata.get("document_id")
                or doc.metadata.get("original_doc_id"),
                metadata=doc.metadata,
                rank=i + 1,
            )
            for i, (doc, rrf_score) in enumerate(fused)
        ]

    def _reciprocal_rank_fusion(
        self,
        result_lists: List[List[Document]],
        weights: List[float],
        k: int = 5,
        rrf_k: int = 60,
    ) -> List[tuple]:
        """Combine multiple result lists using weighted Reciprocal Rank Fusion.

        RRF score = sum(weight_i / (rrf_k + rank_i)) for each list i.
        """
        doc_scores: Dict[str, float] = {}
        doc_map: Dict[str, Document] = {}

        for results, weight in zip(result_lists, weights):
            for rank, doc in enumerate(results, start=1):
                key = _doc_key(doc)
                doc_map[key] = doc
                doc_scores[key] = doc_scores.get(key, 0.0) + weight / (rrf_k + rank)

        # Sort by RRF score descending
        sorted_keys = sorted(doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True)
        return [(doc_map[key], doc_scores[key]) for key in sorted_keys[:k]]

    # ------------------------------------------------------------------
    # Enrichment
    # ------------------------------------------------------------------

    def _build_trace_notes(
        self,
        strategy: RetrievalStrategy,
        score_threshold: float,
    ) -> List[str]:
        """Provide a concise explanation of the chosen retrieval strategy."""
        notes = {
            RetrievalStrategy.SIMILARITY: [
                "Similarity search returns the closest vector matches from pgvector.",
            ],
            RetrievalStrategy.MMR: [
                "MMR trades a little relevance for more diverse results.",
            ],
            RetrievalStrategy.THRESHOLD: [
                f"Threshold search only keeps semantic matches at or above {score_threshold:.2f}.",
            ],
            RetrievalStrategy.HYBRID: [
                "Hybrid search combines semantic retrieval and PostgreSQL full-text search.",
                "Results are merged with weighted reciprocal rank fusion (semantic 0.6, FTS 0.4).",
            ],
        }
        return notes.get(strategy, []).copy()

    def _enrich_with_document_info(self, results: List[SearchResult]) -> None:
        """Add source document titles and chunk indices to results."""
        # Collect UUIDs that need enrichment
        uuids_to_lookup = [r.chunk_uuid for r in results if r.chunk_uuid and not r.source_title]
        if not uuids_to_lookup:
            return

        try:
            with session_scope() as session:
                placeholders = ", ".join([f":uuid_{i}" for i in range(len(uuids_to_lookup))])
                query = text(
                    f"SELECT c.uuid, c.chunk_index, c.document_id, d.title "
                    f"FROM chunks c JOIN documents d ON c.document_id = d.id "
                    f"WHERE c.uuid IN ({placeholders})"
                )
                params = {f"uuid_{i}": uid for i, uid in enumerate(uuids_to_lookup)}
                rows = session.execute(query, params).fetchall()

                lookup = {row[0]: row for row in rows}
                for result in results:
                    if result.chunk_uuid and result.chunk_uuid in lookup:
                        row = lookup[result.chunk_uuid]
                        result.chunk_index = row[1]
                        result.document_id = row[2]
                        result.source_title = row[3]
        except Exception as e:
            logger.warning(f"Could not enrich results with document info: {e}")
