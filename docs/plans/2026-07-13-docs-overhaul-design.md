# Documentation Overhaul — Design

**Date**: 2026-07-13
**Goal**: Make the repo's documentation excellent for a hiring-manager audience — specifically reviewers evaluating AI/ML and RAG engineering skills.
**Approach chosen**: Showcase README + curated docs hub (full sweep, curate-and-showcase internal artifacts).

## Problem

The repo's engineering has outrun its documentation:

- `CLAUDE.md` links to `docs/deployment/NEXT_STEPS.md` and `docs/sprints/SPRINT_2_IMPLEMENTATION.md`, which do not exist; it says Sprint 2 is in progress (long complete) and references Supabase (migrated to Neon).
- `README.md` never mentions the SuttaCentral segmented-text parser, the retrieval/query layer (`retrieval/query.py`, `answering.py`, eval notebooks), Langfuse observability, or the Neon migration. It has no screenshot and no architecture diagram, though `docs/images/streamlit-ui.png` exists.
- `docs/` mixes reader-facing guides with 19 internal planning artifacts and a candid learning journal, with no index telling a visitor what anything is.
- `.env.example` is titled "Journalling Assistant" and recommends Supabase.

## Audience decisions (from brainstorming)

1. **Target role**: AI/ML–RAG engineering. Lead with retrieval evaluation, embeddings, chunking design, LLM-as-judge.
2. **Scope**: Full sweep — README, new architecture doc, docs index, CLAUDE.md, ROADMAP, CHANGELOG, .env.example.
3. **Internal artifacts**: Curate and showcase. plans/ and learning/ stay public, framed as design docs and an engineering journal — evidence of designing before coding and reviewing one's own work.
4. **What gets published** (discovered mid-design: `docs/plans/` is gitignored, so most planning docs were never public, though 4 older files slipped in before the ignore rule): publish `*-design.md` files and the framework-research doc; keep `*-plan.md` implementation plans private and untrack the two old plan files that slipped through. Gitignore changes from ignoring all of `docs/plans/` to ignoring everything except `*-design.md` and `*-research.md` (note: `2026-07-08-supabase-to-neon-migration.md` lacks a suffix and stays private as an implementation plan).

## Design

### 1. README.md rewrite — the 60-second pitch (~150 lines)

Structure, top to bottom:

1. Title, one-line value proposition, CI badge (honest badges only — CI exists).
2. Hero paragraph (≤3 sentences): a semantic knowledge base over the Pali Canon powering RAG applications, framed for AI/ML readers.
3. Screenshot: `docs/images/streamlit-ui.png`.
4. One Mermaid architecture diagram covering both paths:
   - Ingestion: sources (SuttaCentral API / PDF / URL) → parser strategy → semantic chunking → Voyage embeddings → dual storage (Neon pgvector + relational metadata, UUID-linked).
   - Query: retrieval strategies → cited answers → Langfuse tracing.
5. Engineering highlights (~7 bullets, each one line + a link into code or a design doc):
   - Retrieval-strategy evaluation harness (Top-K, MMR, threshold, hybrid BM25+semantic) with LLM-as-judge scoring.
   - SuttaCentral bilara-data parser — reconstructs suttas from segmented translation layers.
   - DAG pipeline orchestrator with idempotent, resumable stages.
   - UUID-linked dual-store integrity (chunks ↔ pgvector rows).
   - Thread-safe semantic chunking.
   - Langfuse observability.
   - Design-docs-before-code process (link to docs hub).
6. Quickstart — only commands verified to work (`poetry install` → `.env` → `alembic upgrade head` → UI/CLI).
7. Documentation links (to docs hub), 3-phase roadmap summary, license.

### 2. Depth layer — `docs/ARCHITECTURE.md` (new) + `docs/README.md` hub (new)

**ARCHITECTURE.md** — for the reviewer who clicks past the README:

- Module map: `ingestion/`, `retrieval/`, `db/`, `services/`, `views/`, `observability/`, `core/`, `config/`.
- Ingestion pipeline stage-by-stage; query path.
- Data model: documents/chunks, status flow.
- "Design decisions" section with rationale: dual storage, callers-own-transactions, parser strategy pattern, chunk sizing.
- Content sourced from the accurate parts of the current CLAUDE.md and the plans/ design docs.

**docs/README.md** — the curation layer, three shelves:

- **Guides**: UI guide, Alembic cheatsheet.
- **Design docs**: the published `docs/plans/*-design.md` and research docs, with a one-line description each; framed as "features here are designed before they're built". `ENRICHMENT_LAYER_PLAN.md` moves into `docs/plans/`.
- **Engineering journal**: `docs/learning/`, framed honestly as a working self-review journal (framed, not edited).

Plus links to CHANGELOG and ROADMAP.

### 3. Truth pass — CLAUDE.md + stale docs

- **CLAUDE.md**: 482 → ~120 lines. Remove broken links, Supabase references, stale sprint status. Keep mission, commands, code conventions, pointer to ARCHITECTURE.md.
- **ROADMAP.md**: reflect reality — query layer is partially built, not merely planned.
- **CHANGELOG.md**: cut `0.4.0` covering SuttaCentral ingestion, Neon migration, transaction-ownership refactor.
- **.env.example**: retitle, replace Supabase guidance with Neon + local Docker.

### Verification

- Scripted link-check over all markdown files (no broken relative links).
- Mermaid diagram confirmed to render on GitHub.
- Every command in the README run before it's claimed to work.

### Out of scope (YAGNI)

- No MkDocs/GitHub Pages site.
- No rewriting of the plans/ documents themselves.
- No prose-editing of the learning journal.
