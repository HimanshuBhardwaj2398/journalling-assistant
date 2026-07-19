# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [Unreleased]

### Retrieval Eval Harness + Observability (2026-07-16)

#### Added
- `evals/` package: dataset models (two-level ground truth: chunk UUID + sutta UID), IR
  metrics as pure functions, corpus manifest with re-chunk drift detection, dimension-based
  synthetic QA generation (persona × question type × register) with binary critics,
  eval runner, markdown comparison report
- `retrieval/base.py` + `retrieval/registry.py` — `Retriever` port and strategy registry;
  every retrieval capability is an adapter, consumed by evals/UI/future API alike
- Eval dataset hosted on Langfuse (`evals/sync.py`, upsert by row id; JSONL in git stays the
  source of truth); eval runs logged as Langfuse dataset experiments — one run per strategy,
  per-row metrics as scores, retriever comparison in the Langfuse datasets UI
- Per-stage retrieval spans (`semantic`/`fts`/`fusion`/`enrich`) and LLM generation tracing
  with token usage — all through the single `LangfuseTracer` port
- Dataset v1 (3 seed + 20 synthetic via gpt-4o-mini) + baseline results for 4 strategies:
  hybrid wins (MRR 0.557, recall@5 0.857); measured colloquial-vs-canonical vocabulary gap
  (colloquial MRR 0.41 vs canonical 0.76) confirms query expansion as the Phase-2 priority

#### Fixed
- Doc-level eval scoring deduplicates document ids (repeated chunks of one document
  inflated NDCG past 1.0)

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
