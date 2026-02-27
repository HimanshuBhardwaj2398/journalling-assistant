# RAG Retrieval Quality Evaluation — Design Doc

**Date**: 2026-02-27
**Status**: Approved
**Location**: `experiments/rag_retrieval_eval.ipynb`

## Goal

Evaluate and compare retrieval quality across 4 strategies against the existing meditation corpus (Pali Canon embeddings in PGVector). Results will inform which retrieval strategy to use when building the production query layer.

## Retrieval Strategies

| # | Strategy | Type | What it tests |
|---|---|---|---|
| 1 | Top-K similarity | Dense vector | Pure semantic relevance |
| 2 | MMR | Dense + diversity | Reduces redundant chunks |
| 3 | Similarity score threshold | Dense + quality gate | Precision over recall |
| 4 | Hybrid: BM25 + Semantic | Sparse + Dense (RRF) | Keyword + meaning combined |

## Architecture

```
PostgreSQL (chunks table)
    └── load all chunk_text + metadata at startup
            │
            ├──► BM25Retriever (in-memory index, rank_bm25)
            │
            └──► PGVector (langchain_pg_embedding)
                        │
                        ├── Strategy 1: similarity_search_with_score(k=5)
                        ├── Strategy 2: max_marginal_relevance_search(k=5, fetch_k=20)
                        └── Strategy 3: similarity_search_with_score(k=5, score_threshold=0.7)

BM25Retriever + PGVector retriever
    └──► EnsembleRetriever(weights=[0.4, 0.6]) — Strategy 4
```

**LLM-as-judge**: Groq API (`llama-3.3-70b-versatile`) — OpenAI-compatible, free tier

## Notebook Structure

1. **Setup & imports** — env vars, DB connection, Groq client
2. **Load chunks** — fetch all `chunk_text` + metadata from `chunks` table; build BM25 index
3. **Connect PGVector** — initialize `VectorStoreManager` with existing collection
4. **Define test queries** — 10 queries spanning conceptual, practice, and Pali-specific
5. **Run all 4 strategies** — per query, collect results + similarity scores
6. **Manual inspection display** — rich tables showing chunks + scores side by side
7. **Groq LLM-as-judge** — rate each chunk 1–5 for relevance, collect JSON responses
8. **Summary table** — pandas DataFrame: strategy × avg Groq score × avg similarity × avg # results

## Test Query Set (10 queries)

| Type | Query |
|---|---|
| Conceptual | What is the nature of impermanence? |
| Conceptual | How does craving lead to suffering? |
| Conceptual | What is the relationship between mind and consciousness? |
| Practice | How to establish mindfulness of breathing? |
| Practice | What are the factors of the noble eightfold path? |
| Practice | How does one develop concentration in meditation? |
| Pali-specific | What does anicca mean? |
| Pali-specific | Explain the jhanas and their qualities |
| Cross-document | What does the Buddha say about loving-kindness? |
| Cross-document | How is equanimity described across the discourses? |

## Groq Judge Prompt

```
Given this query: "{query}"
And this retrieved chunk: "{chunk_text}"

Rate the relevance of this chunk to the query on a scale of 1-5:
1 = Not relevant at all
2 = Tangentially related
3 = Partially relevant
4 = Mostly relevant
5 = Highly relevant, directly answers the query

Reply with only valid JSON: {"score": <int>, "reason": "<one sentence>"}
```

## Expected Output

A pandas summary table per strategy:

| Strategy | Avg Relevance (Groq) | Avg Similarity Score | Avg # Results | Notes |
|---|---|---|---|---|
| Top-K | — | — | 5.0 | Baseline |
| MMR | — | — | 5.0 | Diversity boost |
| Threshold | — | — | ~3 | Quality gate |
| Hybrid (BM25+Semantic) | — | — | 5.0 | Keyword coverage |

## Dependencies

```toml
rank-bm25 = "*"   # BM25 indexing
groq = "*"        # Groq SDK (OpenAI-compatible)
```

New env var: `GROQ_API_KEY`

## Out of Scope

- Full RAG chain (retrieval + answer generation)
- RAGAS framework metrics
- Re-embedding or modifying the existing vector store
- Persisting evaluation results to the database
