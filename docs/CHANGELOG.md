# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### RAG Retrieval Evaluation (In Progress)
- Building evaluation comparing 4 retrieval strategies against the meditation corpus
  - Top-K similarity (dense vector search)
  - MMR — Maximal Marginal Relevance (diverse results)
  - Score threshold filtering
  - Hybrid PostgreSQL full-text (tsvector) + semantic, merged with weighted reciprocal rank fusion
- Scoring per the [eval design](plans/2026-07-13-retrieval-eval-strategy-design.md): IR metrics (Recall@5, MRR) against chunk-UUID ground truth
- Dataset generation for measuring retrieval quality

---

## [0.4.0] — SuttaCentral Ingestion, Retrieval Core & Neon

### Added
- SuttaCentral ingestion source: reconstructs sutta HTML from bilara segmented translation layers via the public API (`ingestion/suttacentral.py`)
- Catalog builder crawling the bilara-data tree (`scripts/build_catalog.py`) and batch ingestion CLI with duplicate skipping (`scripts/ingest_batch.py`)
- Retrieval core: `RetrievalEngine` with similarity / MMR / threshold / hybrid (Postgres FTS + dense, weighted RRF) strategies (`retrieval/query.py`)
- Grounded answer synthesis with per-chunk citations (`retrieval/answering.py`)
- Multi-provider LLM client via litellm — Groq, Ollama, OpenAI (`retrieval/llm_client.py`)
- Optional Langfuse tracing for the query layer (`observability/langfuse.py`)
- RAG playground page in the Streamlit UI (`views/rag_playground.py`)
- Collections partition sources by type; default `buddhist_texts`
- Nikāya tags derived into document and chunk metadata

### Changed
- Migrated hosting from Supabase to Neon — remote Postgres is auto-detected (host-based) and gets resilient connection pooling (pre-ping, recycle, TCP keepalives); SSL comes from the connection URL (`?sslmode=require`)
- Database is injectable; no import-time engine (dependency inversion)
- Callers own transactions; `PipelineContext` is truly immutable
- Consolidated exception hierarchy under `core/exceptions.py`; sealed the config boundary; `CHUNKING_*` settings now live via `Config.from_settings()` (backlog cleanup, PR #6)
- CI: added mypy step (non-blocking) and a dedicated pytest job

---

## [0.3.0] — Sprint 3: Testing, UI Polish & CI

### Added

#### Test Suite
- `tests/conftest.py` — shared fixtures and test database setup
- `tests/test_embedding_integrity.py` — verifies embedding UUID linking
- `tests/test_chunking_metadata.py` — validates chunk metadata structure
- `tests/test_chunk_toc_validation.py` — validates TOC/chunk path integrity
- `tests/test_document_detail_helpers.py` — unit tests for document detail view helpers
- `tests/test_pipeline_callback.py` — tests pipeline stage callbacks
- `tests/test_reprocess_modes.py` — tests all reprocessing modes

#### Alembic Migrations
- `alembic/` directory with migration environment
- `alembic/versions/1367bf7a9116_initial_schema_with_documents_and_.py` — initial schema migration
- `alembic.ini` — Alembic configuration

#### CI/CD
- GitHub Actions workflow for automated linting and format checks (`ruff check`, `ruff format --check`)
- Runs on all pushes and PRs to `main`

#### Reprocessing Support
- `--reprocess` flag in CLI to re-run the pipeline on existing documents
- Multiple reprocess modes: full re-ingestion, re-chunk only, re-embed only
- UI support for triggering reprocessing from the Streamlit interface

#### Ingestion Validation
- Pre-ingestion validation in both CLI and Web UI
- Source reachability checks before starting pipeline
- Duplicate detection for already-ingested documents

#### UI Enhancements
- Document detail page with TOC navigation and chunk inspector
- `views/document_detail.py` — detailed document view with chunk browsing
- `views/components/chunk_inspector.py` — reusable chunk preview component
- `views/validation.py` — ingestion validation feedback page
- Improved Browse page with richer filters and pagination
- Statistics page with document type and category breakdowns

#### Services Layer
- `services/ingestion_service.py` — decouples ingestion logic from UI
- `services/collection_service.py` — vector collection management

### Fixed
- Chunk order preservation during embedding and persistence
- Embedding UUID integrity — chunks now reliably link to their LangChain vector records
- TOC path handling compatibility across document types

---

## [0.2.0] — Sprint 2: Pipeline Architecture & Database

### Sprint 2: Pipeline Architecture Patterns — COMPLETE ✅

#### Phase 1: Code Refactoring
- **New**: `core/exceptions.py` — central exception hierarchy
  - `MeditationDBError` base exception
  - Organized by category: Configuration, Pipeline, Database errors
- **New**: `core/interfaces.py` — core abstractions
  - `Parser` protocol, `ParseResult` dataclass
  - `PipelineStage` ABC, `PipelineContext` with immutable update pattern
  - `StageStatus` enum for execution tracking
- **Refactored**: `ingestion/parsing.py` — Strategy pattern
  - `URLParser`, `PDFParser`, `ParserFactory`
  - Backward-compatible deprecated functions
- **Refactored**: `ingestion/chunking.py` — Thread-safe cache (critical fix)
  - `ThreadSafeEmbeddingsCache` singleton with double-checked locking
  - Fixes race conditions in parallel chunking
- **New**: `ingestion/stages.py` — `ParsingStage`, `ChunkingStage`, `EmbeddingStage`
- **Refactored**: `ingestion/orchestrator.py` — DAG-based `PipelineOrchestrator`
  - Topological sort, cycle detection, dependency resolution
  - Backward-compatible `IngestionOrchestrator` API

#### Phase 2: Database Setup
- **Updated**: `db/schema.py` — complete schema with `Chunk` model
  - `file_path`, `status_details`, `chunks` relationship on Document
  - Index on `status` column
  - Chunk ↔ LangChain embedding UUID linking
- **Updated**: `db/crud.py` — enhanced CRUD
  - `DocumentCRUD`: `update_status`, `update_markdown`, `store_chunks`, `clear_chunks`, `get_documents_by_status`, `get_failed_documents`
  - **New**: `ChunkCRUD` with batch operations
- **Updated**: `config/settings.py` — Supabase-optimized pooling
- **Updated**: `db/database.py` — auto-detects Supabase vs local PostgreSQL
- **New**: `ingestion/stages.py` — `DatabasePersistenceStage` (Stage 4)
- **New**: `scripts/verify_database.py` — 7-check verification script

---

## [0.1.0] — Sprint 1: Critical Fixes & Docker

### Added

#### Configuration Management
- `config/settings.py` — centralized Pydantic Settings
  - `DatabaseSettings`, `EmbeddingSettings`, `ParsingSettings`, `ChunkingSettings`
  - Backward compatibility with legacy env var names

#### Docker Setup
- `docker/Dockerfile`, `docker/Dockerfile.dev` — production and dev images
- `docker/docker-compose.yml`, `docker/docker-compose.dev.yml` — compose configs
- `docker/.dockerignore`, `.env.example`

### Fixed
- Removed hard-coded absolute path in `ingestion/orchestrator.py`

### Changed
- Configuration loading centralized through Pydantic Settings

---

## [0.0.1] — Initial Release

### Added
- Document ingestion pipeline (parsing, chunking, embedding)
- PostgreSQL + pgvector storage
- LlamaParse PDF processing
- Voyage AI embeddings
- SQLAlchemy ORM with status tracking
- Async chunking with parallel processing
- Basic CRUD operations
