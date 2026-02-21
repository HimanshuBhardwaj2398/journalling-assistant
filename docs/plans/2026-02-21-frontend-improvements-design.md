# Frontend Improvements Design

**Date**: 2026-02-21
**Status**: Approved
**Audience**: Admin-only pipeline management tool

## Problem

The current Streamlit frontend has two gaps:
1. **Pipeline feedback is poor** — a single spinner during ingestion with no visibility into stage progress or logs
2. **Chunk inspection is weak** — only shows first 3 chunks truncated to 200 chars, no metadata, no way to navigate by document structure

## Approach

Enhance existing pages (Approach A) rather than restructuring into more pages. Three deliverables:

1. Enhanced pipeline feedback on the Ingest page
2. Chunk Inspector panel on the Browse page
3. New Document Detail page (reached from Browse)

## Design

### 1. Enhanced Pipeline Feedback (Ingest Page)

Replace `st.spinner()` with a stage-by-stage progress tracker and live log panel.

**UI structure:**
- `st.status()` container for the overall pipeline
- One row per stage (Parsing, Chunking, Embedding, Persistence) showing state (pending/running/complete/failed) and elapsed time
- Scrollable log area at the bottom using `st.code()` or `st.container()`
- After completion: metrics (doc ID, chunk count, status) plus timing summary

**Implementation:**
- Use `st.empty()` placeholders for each stage row, updated as the orchestrator progresses
- Add an optional progress callback to the orchestrator so stages can push updates to the UI
- Callback writes to placeholders directly (no rerun needed)

### 2. Chunk Inspector (Enhanced Browse Page)

Replace the "Preview Chunks" expander with a full Chunk Inspector panel inside each document card.

**Features:**
- **Pagination** — prev/next buttons + number input to jump to a specific chunk index
- **Filter** — text search across chunk content
- **Full metadata** — `header_path`, `all_header_paths`, `header_level_map`, chunk size, index, UUID. Raw metadata via `st.json()` expandable
- **Full content** — complete chunk text, not truncated
- **Chunk size indicator** — visual hint for small/medium/large relative to 700-2000 char settings

### 3. Document Detail Page (New)

A new `views/document_detail.py` reached by clicking a document title from Browse. Three tabs:

#### Tab 1: TOC Navigator
- Left panel: table of contents tree built from `doc_metadata.table_of_contents`
- Right panel: chunks filtered by selected header (matched via `all_header_paths` in chunk metadata)
- Layout: `st.columns([1, 2])`

#### Tab 2: Side-by-Side
- Left column: original document markdown (from `document.markdown` field)
- Right column: chunks in order with visible boundaries
- **View mode toggle**: Rendered (`st.markdown()`) vs Raw (`st.code(language="markdown")`)
- Toggle applies to both columns
- Degrades to chunk-only view if markdown is missing

#### Tab 3: Chunk List
- Same chunk inspector as Browse (pagination, filter, full metadata, full content) but full page width

### Navigation

```
Sidebar: [Ingest] [Queue] [Browse] [Statistics]
                              |
                              v
                     Browse (doc list)
                         | click title
                         v
                   Document Detail
                   (back button -> Browse)
```

Document Detail is not in the sidebar. Reached via `st.session_state.selected_doc_id`. When set, Browse delegates to `document_detail.render(doc_id)`. Back button clears state and returns to Browse.

## Files Changed

| File | Change |
|------|--------|
| `app.py` | Add document detail page routing via session state |
| `views/ingest.py` | Replace spinner with stage progress + live logs |
| `views/browse.py` | Replace chunk preview with chunk inspector; clickable doc titles |
| `views/document_detail.py` | **New** — TOC Navigator, Side-by-Side, Chunk List tabs |
| `ingestion/orchestrator.py` | Add optional progress callback for stage updates |

## Files NOT Changed

- `views/queue.py` — already has decent progress via `st.status()`
- `views/stats.py` — not in scope
- Database schema, CRUD — all needed data already exists

## Error Handling

- Document Detail: gracefully handles missing markdown ("No markdown stored", TOC tab disabled)
- Chunk Inspector: handles documents with 0 chunks
- Side-by-Side: degrades to chunk-only view if markdown is missing
