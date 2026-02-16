# Design: CLAUDE.md Restructure

**Date**: 2026-02-14
**Goal**: Reduce CLAUDE.md from 482 lines to under 100 lines following best practices.

## Problem

The current CLAUDE.md is 482 lines. Research shows that files over ~100-150 lines cause Claude to ignore instructions. Most content is either redundant with existing docs (ROADMAP.md, sprint docs, README) or discoverable by reading the code.

## Approach: Lean + Commands (Approach B)

Root CLAUDE.md (~80 lines) with path-scoped `.claude/rules/` files.

## Root CLAUDE.md Structure

### 1. Project Description (~3 lines)
One-line mission + tech stack summary.

### 2. Project Principles (~7 lines)
- Prioritize data quality: clean, well-chunked, accurately embedded texts
- Design for future RAG/GraphRAG query patterns
- End users are meditation practitioners seeking guidance
- Preserve deep structure and context of Buddhist texts
- Plan for scale: many traditions, thousands of texts

### 3. Code Style (~10 lines)
- Async/await for all I/O (parsing, embedding, DB operations)
- `session_scope()` context manager for DB operations
- Dataclasses for configuration and data structures
- Custom exceptions in `core/exceptions.py`
- Structured logging: `logger.info/error/warning`
- Full type annotations (Python 3.11+)
- Pydantic Settings for configuration validation

### 4. Key Commands (~20 lines)
Docker: up, down, logs
Poetry: install, test, lint, type check
DB: init, status check, verify pgvector

### 5. Required Env Vars (~8 lines)
DB_URL, VOYAGE_API_KEY, LLAMAPARSE_API, HF_TOKEN (optional)
Reference `.env.example` for full list.

### 6. Key Docs (~8 lines)
Links to README, ROADMAP, CHANGELOG, sprint docs, .env.example, deployment guide.

## Path-Scoped Rules

### `.claude/rules/db.md` (scoped to `db/**`, ~20 lines)
- session_scope() context manager pattern
- Status flow: PENDING -> PARSING -> PARSED -> CHUNKING -> CHUNKED -> EMBEDDING -> COMPLETED
- CRUD pattern: DocumentCRUD(session), ChunkCRUD(session)
- Chunks link to vector embeddings via UUID
- pgvector for similarity search
- Rich metadata as JSON

### `.claude/rules/ingestion.md` (scoped to `ingestion/**`, ~20 lines)
- Pipeline: Parse -> Chunk -> Embed -> Persist (DAG orchestrator)
- Strategy pattern: ParserFactory auto-selects URLParser or PDFParser
- Async-first for all I/O
- Idempotent stages (can resume failed ingestions)
- Batch embedding: 100 docs/batch via Voyage AI
- Semantic chunking: 700-2000 chars, BAAI/bge-small-en-v1.5

### `.claude/rules/config.md` (scoped to `config/**`, ~10 lines)
- All config via Pydantic Settings in config/settings.py
- Nested settings: Database, Embedding, Parsing, Chunking
- Environment variables override defaults
- See .env.example for all available vars

## What Gets Deleted (Not Moved)

These are removed entirely (redundant or discoverable):
- Quick Links table (replaced by smaller Key Docs section)
- Sprint status table (lives in sprint docs)
- ASCII architecture diagrams (Claude reads the code)
- Future State diagram (lives in ROADMAP.md)
- Core Components file-by-file descriptions (Claude explores codebase)
- Development Workflows with code examples (Claude reads source)
- Technology Stack table (discoverable from pyproject.toml)
- Development Environment section (discoverable from pyproject.toml)
- Future Development Roadmap (lives in ROADMAP.md)
- Common Tasks for Claude (generic guidance Claude follows naturally)
- Questions to Ask When Uncertain (meta-guidance noise)
- Current Limitations (not actionable instructions)

## Files Changed

| Action | File | Lines |
|--------|------|-------|
| Rewrite | `CLAUDE.md` | ~80 |
| Create | `.claude/rules/db.md` | ~20 |
| Create | `.claude/rules/ingestion.md` | ~20 |
| Create | `.claude/rules/config.md` | ~10 |
