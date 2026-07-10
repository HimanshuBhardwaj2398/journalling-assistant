# Development Roadmap

---

## Sprint Status

| Sprint | Status | Key Deliverables |
|--------|--------|------------------|
| Sprint 1 | ✅ Complete | Docker setup, Pydantic config, critical fixes |
| Sprint 2 | ✅ Complete | Strategy pattern, DAG orchestrator, full database layer |
| Sprint 3 | ✅ Complete | Alembic migrations, test suite, UI polish, CI, reprocessing |
| Phase 2 | 🔄 In Progress | RAG retrieval evaluation, query API |

---

## Phase 2: Query Layer (In Progress)

### RAG Retrieval Evaluation (Active)

Evaluating 4 retrieval strategies against the meditation corpus:

1. **Top-K similarity** — dense vector search via PGVector + Voyage AI
2. **MMR** — Maximal Marginal Relevance, reduces redundant results
3. **Score threshold** — only return chunks above a similarity cutoff
4. **Hybrid BM25 + Semantic** — sparse keyword + dense vector via LangChain `EnsembleRetriever`

LLM-as-judge scoring: Groq `llama-3.3-70b-versatile` rates each chunk 1–5 for relevance.

**Output**: A comparison table and visualisation identifying the best retrieval strategy for the meditation corpus, informing the query API design.

### RAG Query API (Planned)

```
[Vector Database]
       │
       ▼
[Retrieval Layer]
  - Top-K / MMR / Hybrid
  - Re-ranking
  - Citation tracking (chunk → source sutta)
       │
       ▼
[Response Layer]
  - Context window management
  - Streaming responses
  - Source attribution
```

**Design considerations**:
- Context window management for long-form answers
- Citation tracking back to source suttas (chunk → document → Nikāya)
- Relevance scoring and ranking

### GraphRAG API (Future)

- Knowledge graph from chunk entities (concepts, practices, teachers)
- Relationship mapping (prerequisite practices, related concepts)
- Multi-hop reasoning for complex queries

---

## Phase 3: Application Integration (Future)

**Use Cases**:
1. **Meditation Journaling** — suggest teachings based on journal entries
2. **Practice Guidance** — answer technique questions with source citations
3. **Path Exploration** — navigate interconnected concepts and practices
4. **Daily Reflections** — contextual wisdom for specific situations

**Technical**:
- REST API with FastAPI
- Authentication and rate limiting
- Streaming responses
- Query result caching

---

## Phase 4: Scale & Optimize (Future)

- Multi-modal support (audio dharma talks, video transcripts)
- Incremental indexing (detect and process only new content)
- Query performance optimization
- Monitoring and observability
- Multi-language support

---

## Completed Work Reference

### Sprint 3 — Testing, UI Polish & CI ✅
- Alembic migrations (`alembic/`)
- Test suite: 7 test modules covering embedding integrity, chunking, TOC validation, reprocessing
- GitHub Actions CI (ruff lint + format)
- Reprocessing support (CLI + UI)
- Ingestion validation (pre-flight checks)
- Document detail page with TOC navigation and chunk inspector
- Services layer decoupling UI from business logic

### Sprint 2 — Pipeline Architecture & Database ✅
- Strategy pattern for parsers (`URLParser`, `PDFParser`, `ParserFactory`)
- Thread-safe embeddings cache (fixes race conditions)
- DAG-based `PipelineOrchestrator` with topological sort
- Complete database schema (`Document`, `Chunk`, UUID linking)
- Enhanced CRUD (`DocumentCRUD`, `ChunkCRUD`)
- `DatabasePersistenceStage` as 4th pipeline stage
- Verification script (`scripts/verify_database.py`)

### Sprint 1 — Critical Fixes & Docker ✅
- Docker setup (dev + production compose)
- Centralized Pydantic Settings configuration
- Removed hard-coded paths
