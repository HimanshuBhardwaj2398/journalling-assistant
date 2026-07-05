# Meditation Philosophy Database

A semantic search infrastructure for Buddhist scripture and meditation literature, designed to power AI-assisted contemplative practice tools.

## What It Does

Ingests meditation texts (PDFs, URLs), splits them into meaningful semantic chunks, generates vector embeddings, and stores everything in PostgreSQL with pgvector for similarity search.

```
Source Documents → Parsing → Semantic Chunking → Embedding → PostgreSQL + pgvector
```

**Current source texts**: Pali Canon translations (Dīgha, Majjhima, Saṃyutta, Aṅguttara Nikāya) by Bhikkhu Sujato.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Database | PostgreSQL + pgvector |
| ORM | SQLAlchemy 2.0 + Alembic |
| Web UI | Streamlit |
| Embeddings | Voyage AI (`voyage-3.5`) |
| PDF Parsing | LlamaParse |
| Chunking | Custom semantic chunker + BAAI/bge-small-en-v1.5 |
| LLM Framework | LangChain |

## Setup

**Prerequisites**: Python 3.11+, PostgreSQL with pgvector, Poetry

```bash
poetry install
cp .env.example .env   # Then fill in your API keys
```

**Required environment variables** (see `.env.example`):
- `DATABASE_URL` — PostgreSQL connection string
- `VOYAGE_API_KEY` — Voyage AI API key
- `LLAMAPARSE_API` — LlamaParse API key

**Initialize the database**:
```bash
poetry run alembic upgrade head
```

## Usage

### Web Interface

```bash
poetry run streamlit run app.py
```

The Streamlit UI provides:
- **Ingest** — add documents (PDF or URL) with metadata (type, category, tags)
- **Queue** — monitor processing status in real time
- **Browse** — filter and explore ingested documents
- **Document Detail** — browse individual chunks and TOC
- **Validation** — verify chunk and embedding integrity
- **Statistics** — corpus overview with charts

See [docs/UI_GUIDE.md](docs/UI_GUIDE.md) for detailed usage.

### CLI

```bash
# Ingest a PDF
poetry run python scripts/ingest.py "Books/sutra.pdf" \
  --title "Diamond Sutra" --type ancient_text --category buddhism

# Ingest from URL
poetry run python scripts/ingest.py "https://suttacentral.net/dn1"

# Reprocess an existing document
poetry run python scripts/ingest.py --resume 5

# List all documents
poetry run python scripts/ingest.py --list
```

### Programmatic Access

```python
from ingestion.orchestrator import IngestionOrchestrator

orchestrator = IngestionOrchestrator()
orchestrator.process("path/to/text.pdf")
orchestrator.process("https://example.com/article")
```

## Code Quality

One-time setup after `poetry install` — installs git hooks that lint/format on every commit:

```bash
poetry run pre-commit install
```

Manual checks:

```bash
poetry run ruff check .           # Lint
poetry run ruff format --check .  # Format check
poetry run mypy .                 # Type check
poetry run pytest --cov           # Tests with coverage
```

CI (GitHub Actions, on pushes and PRs to `main`) runs lint, format check, mypy (non-blocking until existing findings are fixed), and the test suite.

Logging is configured centrally in `config/logging_config.py`; entry points call `setup_logging()` once, and the level is controlled by `LOG_LEVEL` in `.env`.

## Roadmap

- **Phase 1 (Complete)**: Data ingestion pipeline, semantic chunking, vector storage, Streamlit UI
- **Phase 2 (In Progress)**: RAG retrieval evaluation, query API with citation tracking
- **Phase 3 (Planned)**: Application integration — journaling, practice guidance, path exploration

See [docs/ROADMAP.md](docs/ROADMAP.md) for details.

## License

Personal and educational use. Buddhist texts are translations by Bhikkhu Sujato, available under Creative Commons.
