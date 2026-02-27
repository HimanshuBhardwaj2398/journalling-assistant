# Meditation Philosophy Database Layer

A robust database and retrieval infrastructure for meditation philosophy texts. This project provides semantic search capabilities over Buddhist scripture and meditation literature, designed to power various AI tools and assistants focused on contemplative practice.

## Overview

This repository serves as the foundational data layer for a broader ecosystem of meditation-focused AI tools. It provides both the database infrastructure and query layer for AI-assisted contemplative practice applications.

**Current Focus (Phase 1)**: Building the data foundation
- **Document Ingestion**: Parse PDFs and web content into structured markdown
- **Semantic Chunking**: Intelligent text splitting that preserves meaning and context
- **Vector Embeddings**: High-quality embeddings for semantic similarity search
- **PostgreSQL + pgvector**: Scalable vector storage with full SQL capabilities

**Future Focus (Phase 2)**: Query layer with multiple API interfaces (RAG, GraphRAG) for different use cases like meditation journaling, technique guidance, and path exploration.

## Architecture

```
Source Documents (PDF/URL)
         │
         ▼
    ┌─────────┐
    │ PARSING │  LlamaParse (PDF) / HTML-to-Markdown
    └────┬────┘
         │
         ▼
    ┌──────────┐
    │ CHUNKING │  Semantic + Header-based splitting
    └────┬─────┘
         │
         ▼
    ┌───────────┐
    │ EMBEDDING │  Voyage AI embeddings
    └─────┬─────┘
         │
         ▼
    ┌─────────┐
    │ STORAGE │  PostgreSQL + pgvector
    └─────────┘
```

## Project Structure

```
├── app.py                   # Streamlit web interface entry point
│
├── views/                   # Streamlit page components
│   ├── ingest.py            # Document ingestion UI
│   ├── queue.py             # Processing queue monitor
│   ├── browse.py            # Database browser
│   ├── stats.py             # Analytics dashboard
│   └── validation.py        # Chunk/TOC validation UI
│
├── services/                # Business logic layer
│   └── ingestion_service.py # Ingestion orchestration service
│
├── db/                      # Database layer
│   ├── database.py          # Connection & session management
│   ├── schema.py            # SQLAlchemy ORM models
│   └── crud.py              # Data access operations
│
├── ingestion/               # Document processing pipeline
│   ├── parsing.py           # PDF/URL parsing utilities
│   ├── chunking.py          # Semantic document chunking
│   ├── embed.py             # Vector embedding & storage
│   └── orchestrator.py      # Pipeline orchestration
│
├── core/                    # Core utilities
│   └── exceptions.py        # Custom exception hierarchy
│
├── config/                  # Configuration management
│   └── settings.py          # Pydantic settings models
│
├── experiments/             # Jupyter notebooks for R&D
│
├── Books/                   # Source texts (Pali Canon)
│   ├── Long Discourses/     # Dīgha Nikāya
│   ├── Medium Discourses/   # Majjhima Nikāya
│   ├── Linked Discourses/   # Saṃyutta Nikāya
│   └── Numbered Discourses/ # Aṅguttara Nikāya
│
└── docs/                    # Documentation
    ├── CHANGELOG.md         # Version history
    ├── ROADMAP.md           # Future plans
    └── deployment/          # Deployment guides
```

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Database** | PostgreSQL + pgvector |
| **ORM** | SQLAlchemy 2.0 |
| **Web Interface** | Streamlit |
| **Embeddings** | Voyage AI (`voyage-3.5`) |
| **PDF Parsing** | LlamaParse |
| **Chunking** | Custom semantic chunker + BAAI/bge-small-en-v1.5 |
| **LLM Framework** | LangChain |
| **Local LLM** | Ollama (optional) |

## Setup

### Prerequisites

- Python 3.11 or 3.12
- PostgreSQL with pgvector extension
- Poetry for dependency management

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd journalling-assistant
   ```

2. **Install dependencies**
   ```bash
   poetry install
   ```

3. **Configure environment variables**

   Create a `.env` file in the project root:
   ```env
   DATABASE_URL=postgresql://user:password@localhost:5432/meditation_db
   LLAMAPARSE_API=your_llamaparse_api_key
   VOYAGE_API_KEY=your_voyage_api_key
   HF_TOKEN=your_huggingface_token  # Optional
   ```

4. **Initialize the database**
   ```python
   from db.database import init_db
   init_db()
   ```

## Code Quality

Run linting and formatting checks:

```bash
poetry run ruff check .
poetry run ruff format --check .
```

Auto-fix lint issues and apply formatting:

```bash
poetry run ruff check . --fix
poetry run ruff format .
```

Quality checks run automatically in GitHub Actions on pushes and pull requests targeting `main`.

## Usage

### Web Interface (Streamlit)

The easiest way to interact with the database is through the Streamlit web interface:

```bash
streamlit run app.py
```

The interface provides five main views:

1. **Ingest New Document**: Upload PDFs or provide URLs to add new texts
   - Drag-and-drop file upload
   - URL ingestion support
   - Configure document metadata (title, tags)
   - Real-time processing status

2. **Processing Queue**: Monitor document processing pipeline
   - View all documents and their current status
   - Track progress through the ingestion stages
   - Retry failed ingestions
   - Delete documents from the queue

3. **Browse Database**: Explore successfully ingested content
   - Search and filter documents by title or tags
   - View chunk counts and metadata
   - Preview document content
   - Export data

4. **Statistics**: Database analytics and insights
   - Total documents and chunks
   - Processing success/failure rates
   - Storage metrics
   - Tag distribution

5. **Validation**: Run integrity checks and inspect a visual report
   - Validation modes: random sample, single document, multiple documents
   - Chunk order/reconstruction checks
   - Markdown headers vs TOC coverage checks
   - Chunk metadata checks with per-document drilldown
   - Downloadable markdown report output

![Streamlit Interface](docs/images/streamlit-ui.png)

### Programmatic Access

The `IngestionOrchestrator` handles the complete pipeline:

```python
from ingestion.orchestrator import IngestionOrchestrator

orchestrator = IngestionOrchestrator()

# Ingest a PDF
orchestrator.process("path/to/meditation_text.pdf")

# Ingest from URL
orchestrator.process("https://example.com/article")

# Resume failed ingestion by document ID
orchestrator.process(document_id=123)
```

### Document Status Tracking

Documents progress through these states:

```
PENDING → PARSING → PARSED → CHUNKING → CHUNKED → EMBEDDING → COMPLETED
                                                                    │
                                                              (or FAILED)
```

### Chunking Configuration

The `MarkdownChunker` supports customization:

```python
from ingestion.chunking import MarkdownChunker

chunker = MarkdownChunker(
    max_size=2000,           # Maximum chunk size (characters)
    min_size=700,            # Minimum chunk size
    enable_semantic=True,    # Enable semantic splitting
    enable_parallel=True,    # Parallel processing
    max_workers=4
)

chunks = await chunker.chunk(markdown_content, doc_title="Satipatthana Sutta")
```

### Direct Database Access

```python
from db.database import session_scope
from db.crud import DocumentCRUD

with session_scope() as session:
    crud = DocumentCRUD(session)

    # Create a document
    doc = crud.create_document(
        title="Anapanasati Sutta",
        markdown="...",
        tags=["breathing", "mindfulness"]
    )

    # Retrieve documents
    all_docs = crud.get_all_documents()
```

## Validation And Testing

### Run integrity audit from CLI

```bash
poetry run python scripts/validate_chunk_toc_integrity.py \
  --sample-size 5 \
  --seed 42 \
  --chunk-sample-per-doc 3 \
  --check-embeddings \
  --output reports/chunk_toc_validation.md
```

### Run integrity audit from UI

1. Start Streamlit:
   ```bash
   streamlit run app.py
   ```
2. Open the **Validation** page.
3. Choose mode:
   - `Random sample`
   - `Single document`
   - `Multiple documents`
4. Run validation and review the report cards/tables.

### Run validator unit tests

```bash
poetry run pytest tests/test_chunk_toc_validation.py
```

## Source Texts

This project includes translations of the Pali Canon by Bhikkhu Sujato:

- **Dīgha Nikāya** (Long Discourses) - Extended teachings on meditation and philosophy
- **Majjhima Nikāya** (Medium Discourses) - Core meditation instructions
- **Saṃyutta Nikāya** (Linked Discourses) - Thematically organized teachings
- **Aṅguttara Nikāya** (Numbered Discourses) - Progressive numerical collections

## Roadmap

### Phase 1: Data Layer (Current)
- [x] PDF and web content parsing pipeline
- [x] Semantic chunking with context preservation
- [x] Vector embedding and storage (Voyage AI + pgvector)
- [x] Document status tracking and resume capabilities
- [ ] Incremental indexing for new content
- [ ] Additional text traditions (Zen, Tibetan, Vedantic literature)

### Phase 2: Query Layer (Upcoming)
- [ ] **RAG API**: Simple semantic search with context-aware retrieval
  - Citation tracking back to source suttas
  - Relevance scoring and ranking
  - Streaming responses for long-form answers
- [ ] **GraphRAG API**: Relationship-aware queries with multi-hop reasoning
  - Knowledge graph construction from chunks
  - Entity extraction (concepts, practices, teachers)
  - Conceptual connections and prerequisite relationships
- [ ] **Custom Query APIs**: Specialized endpoints for specific use cases
  - Technique-specific searches
  - Practice progression tracking
  - Personalized recommendations

### Phase 3: Application Integration
- [ ] **Meditation Journaling App**: Suggest relevant teachings based on journal entries
- [ ] **Practice Guidance Tool**: Answer technique questions with citations
- [ ] **Path Exploration Interface**: Navigate interconnected concepts
- [ ] **Daily Reflection Generator**: Contextual wisdom for specific situations
- [ ] Multi-modal support (audio dharma talks, video transcripts)

## License

This project is for personal and educational use. The included Buddhist texts are translations by Bhikkhu Sujato, available under Creative Commons.
