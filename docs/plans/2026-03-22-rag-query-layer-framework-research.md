# RAG Query Layer Framework Research

**Date**: 2026-03-22
**Status**: Proposed
**Goal**: Add a usable RAG query layer on top of the existing database layer, with a strong search experience, a playground-style UI, and enough tracing/debugging to judge chunk quality, retrieval quality, and answer grounding.

## What We Already Have

This repo is not starting from zero.

- We already have a Streamlit shell with multiple pages and routing in [app.py](../../app.py#L23).
- We already have reusable chunk inspection UI in [views/components/chunk_inspector.py](../../views/components/chunk_inspector.py#L8).
- We already have a strong document detail view with TOC navigation and side-by-side markdown/chunk inspection in [views/document_detail.py](../../views/document_detail.py#L13).
- We already persist chunk-level metadata and a document-level table of contents in [ingestion/stages.py](../../ingestion/stages.py#L284).
- There is already an initial retrieval engine draft with similarity, MMR, threshold, and hybrid retrieval in [retrieval/query.py](../../retrieval/query.py#L82).
- There is already a retrieval evaluation direction in `docs/plans/2026-02-27-rag-retrieval-eval-design.md` (internal draft, not published).

## Recommendation

### Recommended stack

Use:

1. **Existing PostgreSQL + pgvector storage**
2. **LangChain-style retrieval layer on top of the current DB**
3. **Streamlit for the first RAG playground UI**
4. **Langfuse for tracing, scores, prompt/version tracking, and experiments**
5. **LangSmith later if we want an alternative managed workflow**

### Why this is the best fit

- It reuses the current app and data model instead of throwing away existing work.
- It gives us a search playground fast.
- It keeps observability separate from product UI, which is cleaner.
- It lets us inspect retrieval, reranking, prompts, citations, and latency without forcing a framework migration.
- It keeps the query layer simple enough to evaluate before we add agent complexity.

## Framework Research Summary

### 1. LangChain on top of the current repo

**Fit**: Best near-term fit

Why:

- The repo already depends on LangChain and uses PGVector.
- The draft retrieval engine already follows this shape.
- We can add a proper query service without changing ingestion/storage.
- Phoenix and LangSmith both integrate well with LangChain traces.

Use LangChain here mainly for:

- retrievers
- hybrid retrieval composition
- optional reranking
- answer synthesis with citations
- structured trace hooks

### 2. LlamaIndex

**Fit**: Good framework, worse migration fit right now

Why it is interesting:

- Strong RAG-oriented abstractions
- Good workflow/orchestration story
- Good observability integrations

Why I would not switch to it first:

- We already have LangChain patterns, PGVector usage, and Streamlit views in place
- A migration would slow down the feedback loop
- The main missing piece is not storage or orchestration anymore; it is the query playground and quality loop

### 3. Chainlit

**Fit**: Strong alternative UI, but not my first recommendation for this repo

Why it is interesting:

- Excellent chat-native UX
- Good step visualization for app-level reasoning traces
- Useful if we want a dedicated assistant UI later

Why I would not start there:

- We already have a working Streamlit UI shell
- We would duplicate some exploration/admin surfaces
- The immediate goal is a retrieval/RAG playground, not a separate chat product

## Observability Recommendation

### Primary recommendation: Langfuse

Langfuse is the best fit here because it combines tracing with prompt/version tracking, scores, datasets, and experiments. That lines up well with the current goal: build a useful internal RAG playground and turn it into a quality loop without splitting observability across multiple tools.

### Secondary recommendation: LangSmith

LangSmith becomes attractive once we want:

- managed experiment comparison
- annotation queues
- dashboards and alerts
- online evaluators on real usage
- team-facing regression workflows

I would treat LangSmith as a later maturity step, not a prerequisite for v1.

## Important Note On "Reasoning Trace"

We should **not** aim to expose hidden model chain-of-thought.

We **should** expose a structured execution trace that we control:

- original query
- rewritten query
- applied filters
- retrieval strategy used
- retrieved chunks and scores
- reranker inputs/outputs
- selected context chunks
- answer prompt version
- citations used
- final answer
- latency and token usage
- evaluator scores / human labels

That gives us explainability and quality visibility without depending on raw hidden reasoning.

## Proposed Architecture

```text
User Query
   |
   v
Query Service
   |
   +--> Query normalization / optional rewrite
   |
   +--> Candidate retrieval
   |      - semantic
   |      - BM25
   |      - hybrid
   |
   +--> Optional reranking
   |
   +--> Answer synthesis with citations
   |
   +--> Trace object + evaluation hooks
   |
   v
Streamlit RAG Playground
   |
   +--> Search Results tab
   +--> Answer tab
   +--> Trace tab
   +--> Evaluation tab
   |
   v
Langfuse
   |
   +--> traces
   +--> prompt inspection
   +--> evaluator runs
   +--> experiments
```

## Proposed Query Layer Shape

Add a dedicated query service rather than letting UI pages call retrievers directly.

Suggested modules:

- `retrieval/query_models.py`
- `retrieval/query_service.py`
- `retrieval/rerank.py`
- `retrieval/synthesis.py`
- `retrieval/tracing.py`
- `views/search.py` or `views/rag_playground.py`

Suggested core dataclasses:

- `QueryRequest`
- `RetrievedChunk`
- `RerankedChunk`
- `AnswerCitation`
- `QueryTrace`
- `QueryResponse`

## Retrieval Workflow

### Phase 1: Search-only mode

Build this first. It gives the highest learning value.

Flow:

1. User enters query
2. Run one or more retrieval strategies
3. Show chunk results side by side
4. Show metadata, header paths, source docs, chunk indices, and scores
5. Let us mark relevance manually
6. Persist feedback for evals later

This should become the place where we answer:

- Are chunks too small or too large?
- Are header paths helping?
- Is hybrid retrieval better than pure semantic?
- Are the top results actually useful?

### Phase 2: Grounded answer mode

After search-only mode feels trustworthy:

1. Retrieve top candidates
2. Optional rerank
3. Select final context window
4. Generate answer from context only
5. Require inline citations back to chunk UUIDs / source docs
6. Return answer plus trace

### Phase 3: Comparison / eval mode

Once we have a stable baseline:

1. Run the same query against multiple strategies
2. Compare retrieved chunks, answer quality, citation coverage, and latency
3. Score with LLM-as-judge and human review
4. Promote the best configuration

## UI Recommendation

Add a new Streamlit page: `RAG Playground`

### Left-side controls

- query input
- mode: search-only / answer / compare
- strategy: similarity / MMR / threshold / hybrid
- top-k
- score threshold
- fetch-k
- reranker on/off
- answer model
- document filters
- tag/category/type filters

### Main body tabs

1. **Answer**
   - final answer
   - citations
   - grounded / abstained status

2. **Retrieved Chunks**
   - ranked results
   - score columns
   - source title
   - chunk index
   - header path
   - expand full chunk text
   - open document detail view

3. **Trace**
   - query rewrite
   - retrieved candidates
   - rerank deltas
   - selected context
   - prompt version
   - timings
   - token usage

4. **Evaluation**
   - thumbs up/down
   - manual relevance labels
   - LLM judge outputs
   - notes

### Reuse from current UI

- Reuse the existing chunk inspector instead of creating a new chunk viewer from scratch.
- Reuse the document detail page as the deeper inspection surface.
- Reuse the TOC and header-path structures to explain why a chunk was selected.

## Retrieval Strategy Recommendation

For v1, support these modes:

1. `similarity`
2. `hybrid`
3. `mmr`
4. `threshold`

This lines up with the draft engine already present in [retrieval/query.py](../../retrieval/query.py#L178).

Recommended default for the playground:

- **Hybrid retrieval** for broad search
- **Search-only mode** as the default UI state
- **No answer generation by default** until we trust retrieval quality

## Reranking Recommendation

Make reranking optional, not required for the first cut.

Start with:

- retrieval only
- compare strategies
- gather feedback

Then add reranking once we know the candidate set is reasonable.

## Evaluation Workflow

### Retrieval evals

Use a small hand-labeled dataset first.

Measure:

- hit rate @ k
- recall @ k
- MRR
- nDCG
- chunk relevance labels

### Answer evals

Measure:

- citation correctness
- faithfulness to sources
- answer helpfulness
- abstention behavior when evidence is weak

### Suggested eval loop

1. Curate 25-50 real queries
2. Label strong chunks for each query
3. Run strategy comparisons offline
4. Expose the same cases in the playground
5. Log manual feedback from real exploration
6. Turn failures into regression cases

## Delivery Plan

### Milestone 1: Search Playground

- formalize `RetrievalEngine` into a stable service
- add `RAG Playground` Streamlit page
- support similarity/MMR/threshold/hybrid
- show chunks, scores, metadata, source links
- log structured query traces locally

### Milestone 2: Phoenix Tracing

- instrument retrieval + generation calls
- send traces to Phoenix
- connect trace IDs back into the Streamlit page
- inspect latency, chunk selection, prompt versions

### Milestone 3: Grounded Answering

- add answer synthesis from retrieved chunks
- add citation objects
- add abstain behavior
- add answer + trace tabs

### Milestone 4: Quality Loop

- build labeled query dataset
- run offline evals
- store human feedback
- compare prompt/retrieval variants

## Decision

### What I would build first

**Keep the current stack and add a dedicated RAG playground page in Streamlit, backed by a cleaned-up retrieval/query service, with Phoenix as the tracing/eval layer.**

This is the fastest path to something useful and inspectable.

### What I would avoid for now

- migrating the whole query layer to LlamaIndex before we have a baseline
- building an agentic workflow before retrieval quality is visible
- switching the UI to Chainlit before we know Streamlit is insufficient
- optimizing answer generation before search quality is measurable

## External References

- LangSmith observability: https://docs.langchain.com/langsmith/observability
- LangSmith evaluation: https://docs.langchain.com/langsmith/evaluation
- LlamaIndex workflows: https://developers.llamaindex.ai/python/llamaagents/workflows/
- LlamaIndex observability: https://developers.llamaindex.ai/python/framework/module_guides/observability/
- Phoenix overview: https://arize.com/docs/phoenix
- Phoenix LangChain tracing: https://arize.com/docs/phoenix/integrations/python/langchain/langchain-tracing
- Streamlit chat input: https://docs.streamlit.io/develop/api-reference/chat/st.chat_input
- Streamlit chat message: https://docs.streamlit.io/develop/api-reference/chat/st.chat_message
- Chainlit overview: https://docs.chainlit.io/
- Chainlit step class: https://docs.chainlit.io/api-reference/step-class
