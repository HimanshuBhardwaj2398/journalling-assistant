# Claude Context: Meditation Philosophy Database

A semantic knowledge base over the Pali Canon, built to power RAG applications
for contemplative practice. The ingestion/data layer is complete: texts flow
from SuttaCentral (plus PDFs and web pages) through parse → semantic chunk →
embed → persist into Postgres + pgvector. The Phase 2 query layer is partially
built — the retrieval core and grounded answering exist; the HTTP API does
not yet.

## Quick links

| Doc | What it covers |
|-----|----------------|
| [README.md](README.md) | Project overview, quickstart, engineering highlights |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, module map, design decisions |
| [docs/README.md](docs/README.md) | Docs index: guides, design docs, engineering journal |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Release history |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Current and planned work |

## Current focus

Retrieval-strategy evaluation and the query layer. Four strategies (top-k
similarity, MMR, score threshold, hybrid) have been compared in LLM-judged
eval runs — the older methodology, kept in the `retrieval/` notebooks. The
approved [evaluation design](docs/plans/2026-07-13-retrieval-eval-strategy-design.md)
supersedes it with an eval-gated ladder: every retrieval upgrade must beat the
incumbent on IR metrics (Recall@5, MRR) against chunk-UUID ground truth. That
IR benchmark has not been run yet — do not describe it as completed.

## Architecture in one paragraph

A document enters as a SuttaCentral reference, a PDF, or a URL. A DAG of four
idempotent pipeline stages (`ingestion/stages.py`) parses it to markdown,
chunks it along semantic boundaries (`BAAI/bge-small-en-v1.5`), embeds the
chunks with Voyage `voyage-3.5`, and persists chunk metadata — all into one
Postgres database (Neon, or local Docker for dev) holding relational tables
and pgvector embeddings linked row-for-row by UUID. `RetrievalEngine`
(`retrieval/query.py`) searches with four strategies; hybrid (the default)
fuses dense retrieval with Postgres full-text search (tsvector) using
rank-only weighted RRF (semantic 0.6, FTS 0.4, `rrf_k=60`).
`GroundedAnswerService` (`retrieval/answering.py`) synthesizes citation-backed
answers through a multi-provider LLM client (Groq/Ollama/OpenAI via litellm),
with optional Langfuse tracing. A Streamlit UI (`app.py` + `views/`) covers
ingestion, browsing, validation, and a RAG playground. Depth and rationale:
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Gotcha worth knowing: `DocumentStatus` has no "persisting" state — the
persistence stage reports under `EMBEDDING` until it flips the document to
`COMPLETED`.

## Commands

```bash
poetry install
poetry run alembic upgrade head          # create/upgrade the schema
poetry run streamlit run app.py          # web UI: ingest, monitor, browse, validate

# SuttaCentral CLIs — positional args only (no selection flags).
# ingest_one.py and ingest_batch.py hard-require NEON_DIRECT_URL in the env/.env.
poetry run python scripts/ingest_one.py sc:mn10/sujato
poetry run python scripts/ingest_batch.py sc:mn1/sujato sc:mn2/sujato
poetry run python scripts/build_catalog.py dn mn   # -> data/suttacentral_catalog.jsonl

# PDF / URL ingestion
poetry run python scripts/ingest.py "Books/sutra.pdf" --title "Diamond Sutra"

# Quality gates (CI runs lint, format check, mypy, and tests on every push/PR to main)
poetry run pytest --cov                  # 23 test modules; external services faked
poetry run ruff check . && poetry run mypy .   # mypy is non-blocking in CI for now

# Docs link integrity (run locally before doc changes; not in CI)
poetry run python scripts/check_doc_links.py
```

## Code conventions

- **Async for I/O-bound paths** (parsing, embedding, network calls); keep
  async/await consistent when extending them.
- **Callers own transactions**: CRUD methods flush but never commit; wrap
  multi-step writes in a single `session_scope()` (`db/database.py`).
  Enforced by `tests/test_crud_transaction_ownership.py`.
- **Configuration via Pydantic Settings** in `config/settings.py` — new code
  reads config through settings, not `os.getenv` (a few legacy getenv reads
  remain in `retrieval/` and `services/`). The `CHUNKING_*` env settings are
  live: they reach the chunker via `Config.from_settings()`.
- **Full type hints** (Python 3.11+); mypy runs in CI (non-blocking for now).
- **Custom exceptions**: one `MeditationDBError` hierarchy in
  `core/exceptions.py` — raise from it rather than adding parallel
  hierarchies.
- **Structured logging** via `config/logging_config.py`; use module-level
  loggers, not `print`.
- **Injectable `Database`** — no import-time engine. Composition roots (e.g.
  the SuttaCentral CLIs) call `set_default_database()` to point the whole
  pipeline at a specific database; tests inject in-memory SQLite.

## Questions to ask when uncertain

1. **Data Model Changes**: "Will this affect existing embeddings or require re-processing?"
2. **New Features**: "Does this belong in data layer or should it wait for query layer?"
3. **Configuration**: "Should this be configurable or hard-coded for this use case?"
4. **Error Handling**: "What should happen if this step fails mid-pipeline?"
5. **Performance**: "Will this work with 10,000+ documents and 100,000+ chunks?"
