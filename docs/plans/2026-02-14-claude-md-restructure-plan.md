# CLAUDE.md Restructure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce CLAUDE.md from 482 lines to ~80 lines, moving domain-specific rules to path-scoped `.claude/rules/` files.

**Architecture:** Root CLAUDE.md keeps universal instructions (style, commands, principles). Domain-specific patterns go into `.claude/rules/{db,ingestion,config}.md` with YAML frontmatter for path scoping.

**Tech Stack:** Markdown, `.claude/rules/` directory convention with YAML frontmatter.

---

### Task 1: Create `.claude/rules/` directory

**Files:**
- Create: `.claude/rules/` (directory)

**Step 1: Create the directory**

Run: `mkdir -p .claude/rules`

**Step 2: Verify**

Run: `ls -la .claude/`
Expected: `rules/` directory listed alongside `settings.local.json`

---

### Task 2: Create `.claude/rules/db.md`

**Files:**
- Create: `.claude/rules/db.md`

**Step 1: Write the rules file**

```markdown
---
paths:
  - "db/**"
---

# Database Layer Rules

## Session Management
- Always use `session_scope()` context manager for database operations
- Never create raw sessions — `session_scope()` handles commit/rollback/close

## Document Status Flow
PENDING -> PARSING -> PARSED -> CHUNKING -> CHUNKED -> EMBEDDING -> COMPLETED
- Update status at each pipeline stage transition
- Check current status before processing (idempotent)

## CRUD Pattern
- Use `DocumentCRUD(session)` and `ChunkCRUD(session)` for all data access
- Do not write raw SQL or direct session queries outside CRUD classes

## Data Model
- Chunks link to vector embeddings via UUID (`chunks.uuid` <-> `langchain_pg_embedding.uuid`)
- pgvector extension handles vector similarity search
- Metadata stored as JSON columns for flexibility
- Documents and chunks have parent-child relationship via `document_id`

## Key Files
- `db/schema.py`: ORM models (Document, Chunk)
- `db/database.py`: Connection management, `session_scope()`
- `db/crud.py`: DocumentCRUD, ChunkCRUD
```

**Step 2: Verify line count**

Run: `wc -l .claude/rules/db.md`
Expected: ~25 lines

**Step 3: Commit**

```bash
git add .claude/rules/db.md
git commit -m "Add path-scoped database rules for Claude Code"
```

---

### Task 3: Create `.claude/rules/ingestion.md`

**Files:**
- Create: `.claude/rules/ingestion.md`

**Step 1: Write the rules file**

```markdown
---
paths:
  - "ingestion/**"
---

# Ingestion Pipeline Rules

## Pipeline Architecture
DAG orchestrator runs 4 stages in order: Parse -> Chunk -> Embed -> Persist
- Each stage is idempotent (safe to re-run on failure)
- Orchestrator handles dependency resolution and error propagation

## Parsing (Strategy Pattern)
- `ParserFactory` auto-selects parser based on input type
- `URLParser`: HTTP/HTTPS web content -> markdown
- `PDFParser`: PDF files via LlamaParse -> markdown
- Add new parsers by implementing the parser interface and registering in factory

## Chunking
- Semantic chunking with BAAI/bge-small-en-v1.5 for boundary detection
- Header-based splitting as fallback
- Size range: 700-2000 characters per chunk
- `ThreadSafeEmbeddingsCache` for parallel processing
- Configurable workers via `CHUNKING_MAX_WORKERS`

## Embedding
- Voyage AI (voyage-3.5), 1024 dimensions
- Batch processing: 100 documents per API call
- Each chunk gets a UUID assigned before embedding

## Async Pattern
- All I/O operations (parsing, embedding, DB) must be async
- Use `await` for all pipeline stage calls
- Parallel processing for chunking (configurable workers)
```

**Step 2: Verify line count**

Run: `wc -l .claude/rules/ingestion.md`
Expected: ~30 lines

**Step 3: Commit**

```bash
git add .claude/rules/ingestion.md
git commit -m "Add path-scoped ingestion pipeline rules for Claude Code"
```

---

### Task 4: Create `.claude/rules/config.md`

**Files:**
- Create: `.claude/rules/config.md`

**Step 1: Write the rules file**

```markdown
---
paths:
  - "config/**"
---

# Configuration Rules

## Pydantic Settings
- All configuration lives in `config/settings.py` using Pydantic Settings
- Nested settings classes: `DatabaseSettings`, `EmbeddingSettings`, `ParsingSettings`, `ChunkingSettings`
- Environment variables override defaults (see `.env.example` for full list)

## Required Environment Variables
- `DB_URL`: PostgreSQL connection string
- `VOYAGE_API_KEY`: Voyage AI API key for embeddings
- `LLAMAPARSE_API`: LlamaParse API key for PDF parsing

## Adding New Settings
- Add field to the appropriate nested settings class
- Provide a sensible default where possible
- Document in `.env.example`
```

**Step 2: Verify line count**

Run: `wc -l .claude/rules/config.md`
Expected: ~18 lines

**Step 3: Commit**

```bash
git add .claude/rules/config.md
git commit -m "Add path-scoped config rules for Claude Code"
```

---

### Task 5: Rewrite `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (full rewrite)

**Step 1: Write the new CLAUDE.md**

Replace the entire file with:

```markdown
# Meditation Philosophy Database

Semantic knowledge base for Buddhist/meditation texts. Ingests PDFs and web content, chunks semantically, embeds with Voyage AI, stores in PostgreSQL + pgvector. Python 3.11+, async-first, Poetry for package management.

## Guiding Principles

- Prioritize data quality: clean, well-chunked, accurately embedded texts are critical
- Design choices should support future RAG/GraphRAG query patterns
- End users are meditation practitioners seeking guidance
- Preserve deep structure and context of Buddhist source texts (primarily Pali Canon)
- Plan for scale: thousands of texts across many contemplative traditions

## Code Style

- Async/await for all I/O operations (parsing, embedding, database)
- `session_scope()` context manager for all database operations
- Custom exceptions in `core/exceptions.py` with meaningful messages
- Structured logging with `logger.info/error/warning` (no print statements)
- Full type annotations on all functions and methods
- Pydantic Settings for all configuration (`config/settings.py`)
- CRUD pattern for database access (`db/crud.py`)

## Commands

```bash
# Docker (local dev database)
docker compose -f docker/docker-compose.dev.yml up db -d
docker compose -f docker/docker-compose.dev.yml down

# Dependencies
poetry install

# Database
poetry run python -c "from db.database import init_db; init_db()"

# Quality
poetry run pytest
poetry run ruff check .
poetry run mypy .
```

## Environment Variables

Required: `DB_URL`, `VOYAGE_API_KEY`, `LLAMAPARSE_API`
Optional: `HF_TOKEN`, chunking/embedding overrides
See `.env.example` for full list with defaults and documentation.

## Key Documentation

- [README.md](README.md) — project overview and setup
- [ROADMAP.md](docs/ROADMAP.md) — implementation plans and future sprints
- [CHANGELOG.md](docs/CHANGELOG.md) — version history
- [Sprint 2 Log](docs/sprints/SPRINT_2_IMPLEMENTATION.md) — current sprint progress
- [Deployment Guide](docs/deployment/NEXT_STEPS.md) — Supabase setup steps
- [.env.example](.env.example) — all environment variables with docs

## Project Structure

- `ingestion/` — pipeline: parsing, chunking, embedding, orchestrator
- `db/` — SQLAlchemy models, CRUD operations, connection management
- `config/` — Pydantic settings
- `core/` — shared exceptions
- `Books/` — source texts (Pali Canon translations)
- `experiments/` — Jupyter notebooks for exploratory work
```

**Step 2: Verify line count**

Run: `wc -l CLAUDE.md`
Expected: ~55-65 lines (well under 100)

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "Rewrite CLAUDE.md: 482 lines -> ~60 lines

Moved domain-specific rules to .claude/rules/ with path scoping.
Kept: code style, guiding principles, commands, env vars, doc links.
Removed: architecture diagrams, roadmaps, code examples, tech stack
table, sprint status — all redundant with existing docs or discoverable
from source code."
```

---

### Task 6: Final verification

**Step 1: Verify all files exist and are reasonable size**

Run: `wc -l CLAUDE.md .claude/rules/*.md`
Expected:
- `CLAUDE.md`: under 100 lines
- `.claude/rules/db.md`: ~25 lines
- `.claude/rules/ingestion.md`: ~30 lines
- `.claude/rules/config.md`: ~18 lines
- Total: under 175 lines (vs 482 original)

**Step 2: Verify no broken links in CLAUDE.md**

Manually check that all referenced files exist:
- `README.md`
- `docs/ROADMAP.md`
- `docs/CHANGELOG.md`
- `docs/sprints/SPRINT_2_IMPLEMENTATION.md`
- `docs/deployment/NEXT_STEPS.md`
- `.env.example`

Run: `ls README.md docs/ROADMAP.md docs/CHANGELOG.md docs/sprints/SPRINT_2_IMPLEMENTATION.md docs/deployment/NEXT_STEPS.md .env.example`
Expected: All files listed, no errors.

**Step 3: Verify YAML frontmatter is valid in rules files**

Read each `.claude/rules/*.md` and confirm the `paths:` frontmatter uses valid glob patterns matching actual project directories.
