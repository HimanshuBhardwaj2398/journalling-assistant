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
| ORM | SQLAlchemy 2.0 |
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
poetry run python -c "from db.database import init_db; init_db()"
```

## Usage

### Web Interface

```bash
streamlit run app.py
```

The Streamlit UI provides pages for document ingestion, processing queue monitoring, database browsing, statistics, and chunk/TOC validation.

### Programmatic Access

```python
from ingestion.orchestrator import IngestionOrchestrator

orchestrator = IngestionOrchestrator()
orchestrator.process("path/to/text.pdf")       # Ingest a PDF
orchestrator.process("https://example.com/article")  # Ingest from URL
```

## Code Quality

```bash
poetry run ruff check .          # Lint
poetry run ruff format --check . # Format check
```

Checks run automatically via GitHub Actions on pushes and PRs to `main`.

## Roadmap

- **Phase 1 (Current)**: Data ingestion pipeline, semantic chunking, vector storage
- **Phase 2**: RAG and GraphRAG query APIs with citation tracking
- **Phase 3**: Application integration — journaling, practice guidance, path exploration

See [ROADMAP.md](docs/ROADMAP.md) for details.

## License

Personal and educational use. Buddhist texts are translations by Bhikkhu Sujato, available under Creative Commons.
