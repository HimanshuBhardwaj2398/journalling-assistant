# Design: Query Layer Improvements + Instagram Content Pipeline

**Date:** 2026-03-22
**Status:** Approved
**Scope:** Two parallel tracks — (1) query layer code quality + retrieval quality, (2) Instagram content pipeline that reuses the improved query layer.

---

## Track 1: Query Layer Improvements

### Goals

- Fix code quality issues (duplication, naming, fragile dedup key)
- Replace in-memory BM25 with PostgreSQL full-text search for scalability
- Add optional query expansion and cross-encoder re-ranking
- Push document scope filtering down to the retrieval engine
- Normalize scores before hybrid fusion

### Code Quality Fixes

| Issue | Fix |
|-------|-----|
| `_extract_header_paths` duplicated in `answering.py` and `rag_playground.py` | Extract to `retrieval/utils.py`; both files import from there |
| `EvalLLMClient` named for eval but used in production answering | Rename to `LLMClient`; keep `EvalLLMClient` as a deprecated alias so eval notebooks don't break |
| RRF dedup key uses first 200 chars of content (collision-prone) | Use `chunk_uuid` when available, fall back to SHA-256 content hash |
| BM25 loads all chunks into RAM on first search | Replace `BM25Retriever.from_documents()` with PostgreSQL FTS via `to_tsvector` / `plainto_tsquery` SQL |
| Document scope filter is post-retrieval in the UI only | Add `document_ids: list[int] \| None` parameter to `RetrievalEngine.search()` pushed down to the SQL query |

### Retrieval Quality Additions

Both are **optional** and toggleable via `search()` parameters and in the RAG Playground UI.

#### 1. `QueryTransformer` (`retrieval/query_transformer.py`)

Generates 3 rephrased variants of the user query using `LLMClient`, then runs retrieval on all 4 (original + 3 variants), merges with RRF. Improves recall on abstract meditation concepts.

- Adds ~1 LLM call per search
- Controlled by `expand_query: bool = False` on `search()`
- Variants prompt is domain-tuned for meditation / Buddhist philosophy

#### 2. `Reranker` (`retrieval/reranker.py`)

After initial retrieval, re-scores all candidates using a cross-encoder (`BAAI/bge-reranker-base`, free/self-hosted via `sentence-transformers`). Returns the top-K by reranker score.

- Adds ~50-100ms latency
- +5-10% precision improvement on NDCG@10 (BEIR benchmarks)
- Controlled by `rerank: bool = False` on `search()`
- Abstract `BaseReranker` with `BGEReranker` and `CohereReranker` implementations

#### 3. Score Normalization in Hybrid Search

Before RRF fusion, min-max normalize BM25 and semantic scores independently so neither dominates. More stable scores, especially visible in the RAG Playground.

### Updated `search()` Signature

```python
engine.search(
    query: str,
    strategy: RetrievalStrategy = RetrievalStrategy.HYBRID,
    k: int = 5,
    score_threshold: float = 0.5,
    fetch_k: int = 20,
    rerank: bool = False,        # NEW — run BGE reranker post-retrieval
    expand_query: bool = False,  # NEW — multi-query rewriting before retrieval
    document_ids: list[int] | None = None,  # NEW — pushed-down filter
) -> SearchResponse
```

### File Structure Changes

```
retrieval/
  utils.py            # NEW — shared _extract_header_paths, content hash helpers
  query_transformer.py  # NEW — QueryTransformer with multi-query rewriting
  reranker.py         # NEW — BaseReranker, BGEReranker, CohereReranker
  query.py            # MODIFIED — new search() params, postgres FTS for BM25, score normalization
  answering.py        # MODIFIED — import _extract_header_paths from utils
  llm_client.py       # MODIFIED — rename EvalLLMClient → LLMClient, keep alias
```

---

## Track 2: Instagram Content Pipeline

### Goals

A fully automated 5-step pipeline that picks a meditation theme, retrieves grounded context from the corpus, generates a long-form Instagram caption with citations, generates a matching image, and posts to Instagram.

### Pipeline Overview

```
ThemePicker
    │  Theme(name, description, tags)
    ▼
RetrievalEngine  (existing, improved)
    │  SearchResponse (grounded chunks from ancient texts)
    ▼
CaptionGenerator
    │  Caption(text, citations, hashtags)
    ▼
ImageGenerator  (pluggable)
    │  GeneratedImage(path, prompt_used)
    ▼
InstagramPublisher
    │  PublishResult(post_id, permalink)
    ▼
ContentPipeline (orchestrator)
```

### Components

#### `ThemePicker` (`content/theme_picker.py`)

Two modes, switchable via config:

- **`curated`** — picks from a hand-curated YAML list of themes (`content/themes.yaml`). E.g. "impermanence", "right effort", "the five hindrances", "metta". Can be weighted by season, lunar calendar, or random.
- **`corpus_driven`** — queries DB chunk metadata for high-frequency concept keywords, passes them to `LLMClient` to select a thematically rich candidate for today.

Returns: `Theme(name: str, description: str, tags: list[str], search_query: str)`

#### `RetrievalEngine` (existing — reused directly)

Called with `expand_query=True, rerank=True` for maximum quality. The theme's `search_query` field is the retrieval query.

#### `CaptionGenerator` (`content/caption_generator.py`)

Extends / wraps `GroundedAnswerService` with an Instagram-specific system prompt:

```
You are writing an Instagram caption for a meditation account grounded in ancient Buddhist texts.
Structure:
1. Hook — one powerful opening line
2. Body — 3-4 paragraphs grounded in the retrieved suttas, inline citations like [1]
3. Closing reflection — one introspective question or invitation
4. Hashtags — 10-15 relevant tags

Tone: contemplative, warm, accessible to modern practitioners.
```

Returns: `Caption(text: str, citations: list[AnswerCitation], hashtags: list[str])`

#### `ImageGenerator` (`content/image_generator.py`)

Abstract interface, pluggable:

```python
class BaseImageGenerator(ABC):
    def generate(self, theme: Theme, style_prompt: str = "") -> GeneratedImage: ...

class OpenAIImageGenerator(BaseImageGenerator): ...   # DALL-E 3
class StableDiffusionImageGenerator(BaseImageGenerator): ...  # SD via API
class MockImageGenerator(BaseImageGenerator): ...     # returns placeholder for testing
```

Active implementation selected by `IMAGE_PROVIDER` env var (default: `openai`).

Image prompt is constructed from `Theme.name + Theme.description + style_prompt`. Default style: "minimalist watercolor, peaceful, soft earth tones, no text."

#### `InstagramPublisher` (`content/instagram_publisher.py`)

Uses the **Meta Graph API** (Instagram Content Publishing API):

1. Upload image to Facebook/Instagram container
2. Create media container with caption
3. Publish media container

Returns: `PublishResult(post_id: str, permalink: str, published_at: str)`

Requires env vars: `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_USER_ID`.

#### `ContentPipeline` (`content/pipeline.py`)

Orchestrator with three run modes:

```python
pipeline = ContentPipeline()

# Full automated run
result = pipeline.run()

# Fix the theme (useful for manual curation)
result = pipeline.run(theme_name="impermanence")

# Preview without posting — returns all artifacts for human review
result = pipeline.dry_run()

# Schedule via cron or APScheduler
pipeline.schedule(cron="0 8 * * *")  # post daily at 8am
```

All steps are Langfuse-traced. Failures in step 4 (image gen) or 5 (publish) do not discard the caption — artifacts are saved locally so the run can be resumed.

### File Structure (new `content/` module)

```
content/
  __init__.py
  pipeline.py          # ContentPipeline orchestrator
  theme_picker.py      # ThemePicker (curated + corpus modes)
  caption_generator.py # CaptionGenerator (wraps GroundedAnswerService)
  image_generator.py   # BaseImageGenerator + provider implementations
  instagram_publisher.py  # InstagramPublisher (Meta Graph API)
  themes.yaml          # Curated theme list
  models.py            # Theme, Caption, GeneratedImage, PublishResult dataclasses
```

### Environment Variables (additions to `.env.example`)

```bash
# Instagram Content Pipeline
INSTAGRAM_ACCESS_TOKEN=        # Meta Graph API long-lived token
INSTAGRAM_USER_ID=             # Instagram Business/Creator account ID
IMAGE_PROVIDER=openai          # openai | stable_diffusion | mock
OPENAI_API_KEY=                # for DALL-E 3 image generation
SD_API_URL=                    # for self-hosted Stable Diffusion (optional)
THEME_MODE=curated             # curated | corpus_driven
```

---

## What This Design Deliberately Excludes (YAGNI)

- GraphRAG — not yet, retrieval quality first
- Comment reply automation — out of scope for this phase
- Multi-platform publishing (Twitter, LinkedIn) — pluggable architecture makes this easy to add later, but not now
- A/B testing captions — future phase
- Re-embedding chunks post-retrieval improvements — not needed; existing embeddings are fine

---

## Dependencies to Add

```toml
# pyproject.toml additions
sentence-transformers = ">=2.7"   # BGEReranker
cohere = ">=5.0"                  # CohereReranker (optional)
openai = ">=1.0"                  # DALL-E image generation
requests = ">=2.31"               # Meta Graph API calls
pyyaml = ">=6.0"                  # themes.yaml loading
```
