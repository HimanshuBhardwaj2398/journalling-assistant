# Documentation

## Guides

| Doc | Description |
|-----|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, module map, and the reasoning behind key decisions |
| [UI_GUIDE.md](UI_GUIDE.md) | CLI and Streamlit web UI walkthrough for ingesting and managing texts |
| [ALEMBIC_CHEATSHEET.md](ALEMBIC_CHEATSHEET.md) | Alembic migration command reference |
| [CHANGELOG.md](CHANGELOG.md) | Release history |
| [ROADMAP.md](ROADMAP.md) | Current and planned work |

## Design docs

Features in this repo are designed in writing before they're built. These are
the real working documents, published as-is:

| Design | What it decided |
|--------|-----------------|
| [Embedding atlas](plans/2026-08-16-embedding-atlas-design.md) | Mapping the chunk embedding distribution — anisotropy, pericope structure, and whether the corpus clusters at all — as insight only, with any retrieval consequence deferred to the eval gate |
| [Retrieval evaluation strategy](plans/2026-07-13-retrieval-eval-strategy-design.md) | An eval-gated capability ladder: every retrieval upgrade — hybrid tuning, enrichment, agentic — is an adapter that must beat a fixed IR-metric harness before it ships |
| [SuttaCentral ingestion](plans/2026-07-10-suttacentral-ingestion-design.md) | Cataloging every early Buddhist text on SuttaCentral, then ingesting suttas as reconstructed HTML from bilara layers via the official API |
| [Architecture hardening](plans/2026-07-10-architecture-hardening-retrieval-foundations-design.md) | Injectable database, Unit-of-Work transaction ownership, and retrieval as ports and adapters |
| [Supabase → Neon migration](plans/2026-07-08-supabase-to-neon-migration-design.md) | Rescuing the only copy of the data from a paused Supabase project into Neon, preserving the chunk UUIDs the eval dataset depends on |
| [RAG framework research](plans/2026-03-22-rag-query-layer-framework-research.md) | Keep pgvector and LangChain-style retrieval, add a Streamlit playground and Langfuse tracing — no framework migration |
| [Query layer improvements + Instagram pipeline](plans/2026-03-22-query-layer-instagram-pipeline-design.md) | Postgres FTS hybrid search, RRF dedup fix, query expansion, and reranking — plus an Instagram content pipeline that reuses the improved retrieval |
| [Multi-provider LLM abstraction](plans/2026-03-04-multi-provider-llm-abstraction-design.md) | One config-driven client over Groq/Ollama/OpenAI via LiteLLM, so eval runs aren't blocked by one provider's rate limits |
| [Eval dataset](plans/2026-02-28-eval-dataset-design.md) | ~100 synthetic question-chunk pairs with three-agent quality filtering, to compare 4 retrieval strategies on IR metrics |
| [Enrichment layer](plans/enrichment-layer-design.md) | Draft plan for a concept graph and RAPTOR-style summary tree, built as rebuildable derived data |
| [Docs overhaul](plans/2026-07-13-docs-overhaul-design.md) | The audience decisions behind this documentation structure |

## Engineering journal

[learning/LEARNINGS_BLOG.md](learning/LEARNINGS_BLOG.md) — a running,
candid self-review of the codebase's architecture, folder by folder: what
each abstraction is for, whether it's earning its keep, and the Python
patterns worth stopping on. Raw notes live in
[learning/ARCHITECTURE_REVIEW_TRACKER.md](learning/ARCHITECTURE_REVIEW_TRACKER.md).
