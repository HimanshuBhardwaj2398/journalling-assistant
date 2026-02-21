# Frontend Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Enhance the Streamlit admin frontend with live pipeline feedback, a chunk inspector, and a document detail page with TOC navigation and side-by-side markdown/chunk view.

**Architecture:** Three changes: (1) add a progress callback to the orchestrator's `execute()` loop so the UI can react to stage transitions, (2) replace the ingest page spinner with stage-by-stage progress + live logs, (3) add a chunk inspector to Browse and a new Document Detail page with three tabs (TOC Navigator, Side-by-Side, Chunk List).

**Tech Stack:** Streamlit, SQLAlchemy (existing ORM), existing `PipelineOrchestrator`, `PipelineContext`, `StageStatus`

---

### Task 1: Add Progress Callback to PipelineOrchestrator

**Files:**
- Modify: `core/interfaces.py`
- Modify: `ingestion/orchestrator.py`
- Test: `tests/test_pipeline_callback.py`

**Step 1: Write the failing test**

```python
# tests/test_pipeline_callback.py
"""Tests for pipeline progress callback."""
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from core.interfaces import PipelineContext, PipelineStage, StageStatus


class FakeStage(PipelineStage):
    """Minimal stage for testing."""
    def __init__(self, stage_name: str, deps=None):
        self._name = stage_name
        self._deps = deps or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def required_stages(self):
        return self._deps

    async def execute(self, context: PipelineContext) -> PipelineContext:
        return context.mark_stage_completed(self.name)


class TestPipelineCallback:
    def test_callback_called_for_each_stage(self):
        """Callback receives stage_name and status for each stage transition."""
        from ingestion.orchestrator import PipelineOrchestrator

        callback = MagicMock()
        stages = [FakeStage("stage_a"), FakeStage("stage_b", deps=["stage_a"])]
        pipeline = PipelineOrchestrator(stages)

        context = PipelineContext()
        result = asyncio.run(pipeline.execute(context, on_stage_update=callback))

        # Should be called with running + completed for each stage = 4 calls
        assert callback.call_count == 4
        callback.assert_any_call("stage_a", StageStatus.RUNNING)
        callback.assert_any_call("stage_a", StageStatus.COMPLETED)
        callback.assert_any_call("stage_b", StageStatus.RUNNING)
        callback.assert_any_call("stage_b", StageStatus.COMPLETED)

    def test_callback_receives_failed_status(self):
        """Callback receives FAILED status when a stage fails."""
        from ingestion.orchestrator import PipelineOrchestrator

        class FailingStage(PipelineStage):
            @property
            def name(self):
                return "bad_stage"
            @property
            def required_stages(self):
                return []
            async def execute(self, context):
                raise ValueError("something broke")

        callback = MagicMock()
        pipeline = PipelineOrchestrator([FailingStage()])
        context = PipelineContext()
        result = asyncio.run(pipeline.execute(context, on_stage_update=callback))

        callback.assert_any_call("bad_stage", StageStatus.RUNNING)
        callback.assert_any_call("bad_stage", StageStatus.FAILED)

    def test_no_callback_is_fine(self):
        """Pipeline works without callback (backward compatible)."""
        from ingestion.orchestrator import PipelineOrchestrator

        stages = [FakeStage("stage_a")]
        pipeline = PipelineOrchestrator(stages)
        context = PipelineContext()
        result = asyncio.run(pipeline.execute(context))
        assert result.stage_results["stage_a"] == StageStatus.COMPLETED
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/test_pipeline_callback.py -v`
Expected: FAIL — `execute()` does not accept `on_stage_update` kwarg

**Step 3: Implement the callback in PipelineOrchestrator.execute()**

In `ingestion/orchestrator.py`, modify `PipelineOrchestrator.execute()`:

```python
async def execute(
    self,
    context: PipelineContext,
    on_stage_update: Optional[callable] = None,
) -> PipelineContext:
    """
    Execute pipeline stages in dependency order.

    Args:
        context: Initial pipeline context
        on_stage_update: Optional callback(stage_name, status) called on stage transitions
    """
    current_context = context

    for stage in self._execution_order:
        if stage.should_skip(current_context):
            logger.info(f"Skipping stage '{stage.name}' (already completed)")
            continue

        if not stage.can_run(current_context):
            missing = [
                dep for dep in stage.required_stages
                if current_context.stage_results.get(dep) != StageStatus.COMPLETED
            ]
            logger.warning(f"Stage '{stage.name}' cannot run. Missing: {missing}")
            continue

        # Notify: RUNNING
        logger.info(f"Executing stage: {stage.name}")
        if on_stage_update:
            on_stage_update(stage.name, StageStatus.RUNNING)

        try:
            current_context = await stage.execute(current_context)

            if current_context.stage_results.get(stage.name) == StageStatus.FAILED:
                error = current_context.error_messages.get(stage.name, "Unknown error")
                logger.error(f"Stage '{stage.name}' failed: {error}")
                if on_stage_update:
                    on_stage_update(stage.name, StageStatus.FAILED)
            else:
                if on_stage_update:
                    on_stage_update(stage.name, StageStatus.COMPLETED)

        except Exception as e:
            logger.error(f"Unexpected error in stage '{stage.name}': {e}", exc_info=True)
            current_context = current_context.mark_stage_failed(stage.name, str(e))
            if on_stage_update:
                on_stage_update(stage.name, StageStatus.FAILED)

    return current_context
```

Add the `Optional` import at the top of `orchestrator.py` if not already present (it is — line 9).

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/test_pipeline_callback.py -v`
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add ingestion/orchestrator.py tests/test_pipeline_callback.py
git commit -m "feat: add progress callback to PipelineOrchestrator.execute()"
```

---

### Task 2: Thread Callback Through IngestionOrchestrator and Service Layer

**Files:**
- Modify: `ingestion/orchestrator.py` (IngestionOrchestrator.process)
- Modify: `services/ingestion_service.py`

**Step 1: Add `on_stage_update` param to `IngestionOrchestrator.process()`**

In `ingestion/orchestrator.py`, modify `IngestionOrchestrator.process()` signature:

```python
async def process(
    self,
    source: Union[str, int],
    title: Optional[str] = None,
    on_stage_update: Optional[callable] = None,
) -> Dict[str, Any]:
```

And pass it through to the pipeline:

```python
final_context = await pipeline.execute(context, on_stage_update=on_stage_update)
```

**Step 2: Add `on_stage_update` param to service layer functions**

In `services/ingestion_service.py`, modify both async and sync wrappers:

```python
async def ingest_document_async(
    source: str,
    title: str,
    description: str,
    doc_type: str,
    category: str,
    tags: list,
    collection_name: str = "meditation_chunks",
    on_stage_update: callable = None,
) -> dict:
    # ... existing code ...
    result = await orchestrator.process(source=doc_id, title=title, on_stage_update=on_stage_update)
    return result


def ingest_document(
    source: str,
    title: str,
    description: str,
    doc_type: str,
    category: str,
    tags: list,
    collection_name: str = "meditation_chunks",
    on_stage_update: callable = None,
) -> dict:
    """Synchronous wrapper for async ingestion."""
    return asyncio.run(
        ingest_document_async(
            source, title, description, doc_type, category, tags, collection_name,
            on_stage_update=on_stage_update,
        )
    )
```

Do the same for `process_document_by_id_async` and `process_document_by_id`.

**Step 3: Verify existing tests still pass**

Run: `poetry run pytest tests/ -v`
Expected: All existing tests pass (new param is optional, backward compatible)

**Step 4: Commit**

```bash
git add ingestion/orchestrator.py services/ingestion_service.py
git commit -m "feat: thread progress callback through IngestionOrchestrator and service layer"
```

---

### Task 3: Enhanced Ingest Page with Stage Progress and Live Logs

**Files:**
- Modify: `views/ingest.py`

**Step 1: Rewrite the ingestion execution block**

Replace the current `st.spinner()` block (lines 136-202 in `views/ingest.py`) with stage-by-stage progress using `st.empty()` placeholders:

```python
# Replace the block starting at "if st.button("Start Ingestion"..."
# After validation passes, replace the st.spinner block with:

with st.status("Processing document...", expanded=True) as status_container:
    # Define the 4 pipeline stages
    stage_names = ["parsing", "chunking", "embedding", "database_persistence"]
    stage_labels = {
        "parsing": "Parsing",
        "chunking": "Chunking",
        "embedding": "Embedding",
        "database_persistence": "Persistence",
    }

    # Create placeholder rows for each stage
    stage_placeholders = {}
    for sn in stage_names:
        stage_placeholders[sn] = st.empty()
        stage_placeholders[sn].markdown(f"⏳ **{stage_labels[sn]}** — Pending")

    # Log area
    log_placeholder = st.empty()
    log_lines = []

    import time
    stage_start_times = {}

    def on_stage_update(stage_name, stage_status):
        """Callback to update UI when a stage transitions."""
        from core.interfaces import StageStatus

        label = stage_labels.get(stage_name, stage_name)

        if stage_status == StageStatus.RUNNING:
            stage_start_times[stage_name] = time.time()
            stage_placeholders[stage_name].markdown(
                f"🔄 **{label}** — Running..."
            )
            log_lines.append(f"[{label}] Started")

        elif stage_status == StageStatus.COMPLETED:
            elapsed = time.time() - stage_start_times.get(stage_name, time.time())
            stage_placeholders[stage_name].markdown(
                f"✅ **{label}** — Complete ({elapsed:.1f}s)"
            )
            log_lines.append(f"[{label}] Completed in {elapsed:.1f}s")

        elif stage_status == StageStatus.FAILED:
            elapsed = time.time() - stage_start_times.get(stage_name, time.time())
            stage_placeholders[stage_name].markdown(
                f"❌ **{label}** — Failed ({elapsed:.1f}s)"
            )
            log_lines.append(f"[{label}] FAILED after {elapsed:.1f}s")

        # Update log display
        log_placeholder.code("\n".join(log_lines), language="text")

    try:
        # Handle uploaded file
        if uploaded_file is not None:
            suffix = Path(uploaded_file.name).suffix
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(uploaded_file.getbuffer())
                source = tmp.name

        result = ingest_document(
            source=source,
            title=title,
            description=description,
            doc_type=doc_type,
            category=category,
            tags=tags,
            collection_name=collection_name,
            on_stage_update=on_stage_update,
        )
        st.session_state.ingestion_result = result
        st.session_state.pop("collections_cache", None)

        if result.get("success"):
            status_container.update(label="Processing complete!", state="complete")
        else:
            status_container.update(label="Processing failed", state="error")

    except DuplicateDocumentError as e:
        status_container.update(label="Duplicate document", state="error")
        st.error("Duplicate Document Detected")
        st.warning(str(e))
    except Exception as e:
        status_container.update(label="Processing failed", state="error")
        st.error(f"Ingestion failed: {str(e)}")
```

**Step 2: Manually test**

Run: `streamlit run app.py`
- Navigate to Ingest page
- Submit a document and verify:
  - Each stage row updates from Pending → Running → Complete
  - Timing is shown for each stage
  - Log area accumulates entries
  - Failed stages show red

**Step 3: Commit**

```bash
git add views/ingest.py
git commit -m "feat: enhanced ingest page with stage progress and live logs"
```

---

### Task 4: Chunk Inspector Component

**Files:**
- Create: `views/components/chunk_inspector.py`

This is a reusable component used by both Browse and Document Detail pages.

**Step 1: Create the chunk inspector component**

```python
# views/components/chunk_inspector.py
"""
Reusable chunk inspector component.

Provides paginated chunk browsing with full metadata and content display.
"""

import streamlit as st
from typing import List


def render_chunk_inspector(chunks: List, key_prefix: str = "ci"):
    """
    Render a paginated chunk inspector.

    Args:
        chunks: List of Chunk ORM objects (must have chunk_text, chunk_index,
                chunk_metadata, uuid attributes)
        key_prefix: Unique prefix for Streamlit widget keys (needed when
                    multiple inspectors are on the same page)
    """
    if not chunks:
        st.info("No chunks to display.")
        return

    total = len(chunks)

    # Controls row: pagination + filter
    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 2, 2])

    with ctrl_col1:
        st.markdown(f"**{total} chunks**")

    with ctrl_col2:
        chunk_idx = st.number_input(
            "Go to chunk",
            min_value=0,
            max_value=total - 1,
            value=st.session_state.get(f"{key_prefix}_idx", 0),
            step=1,
            key=f"{key_prefix}_nav",
        )
        st.session_state[f"{key_prefix}_idx"] = chunk_idx

    with ctrl_col3:
        filter_text = st.text_input(
            "Filter chunks",
            placeholder="Search chunk content...",
            key=f"{key_prefix}_filter",
        )

    # Apply filter
    if filter_text:
        filtered = [c for c in chunks if filter_text.lower() in c.chunk_text.lower()]
        if not filtered:
            st.warning(f"No chunks match '{filter_text}'")
            return
        st.caption(f"Showing {len(filtered)} of {total} chunks matching '{filter_text}'")
        display_chunks = filtered
    else:
        display_chunks = [chunks[chunk_idx]]

    # Render each visible chunk
    for chunk in display_chunks:
        _render_single_chunk(chunk, key_prefix)


def _render_single_chunk(chunk, key_prefix: str):
    """Render a single chunk with metadata and content."""
    # Size classification
    size = len(chunk.chunk_text)
    if size < 700:
        size_label = f"🟡 {size} chars (small)"
    elif size > 2000:
        size_label = f"🔴 {size} chars (large)"
    else:
        size_label = f"🟢 {size} chars"

    st.markdown(f"#### Chunk {chunk.chunk_index}")

    # Metadata row
    meta_col1, meta_col2, meta_col3 = st.columns(3)
    with meta_col1:
        st.markdown(f"**Index:** {chunk.chunk_index}")
    with meta_col2:
        st.markdown(f"**Size:** {size_label}")
    with meta_col3:
        st.markdown(f"**UUID:** `{chunk.uuid[:12]}...`")

    # Header path (if present in metadata)
    metadata = chunk.chunk_metadata or {}
    header_path = metadata.get("header_path", "")
    if header_path:
        st.markdown(f"**Header path:** {header_path}")

    all_paths = metadata.get("all_header_paths", [])
    if all_paths:
        with st.expander("All header paths"):
            for p in all_paths:
                st.markdown(f"- `{p}`")

    # Raw metadata
    if metadata:
        with st.expander("Raw metadata"):
            st.json(metadata)

    # Full content
    st.markdown("**Content:**")
    st.text(chunk.chunk_text)

    st.markdown("---")
```

**Step 2: Verify no import errors**

Run: `poetry run python -c "from views.components.chunk_inspector import render_chunk_inspector; print('OK')"`
Expected: OK

**Step 3: Create `views/components/__init__.py`**

```python
# views/components/__init__.py
```

**Step 4: Commit**

```bash
git add views/components/__init__.py views/components/chunk_inspector.py
git commit -m "feat: add reusable chunk inspector component"
```

---

### Task 5: Update Browse Page to Use Chunk Inspector

**Files:**
- Modify: `views/browse.py`

**Step 1: Replace the chunk preview section**

In `views/browse.py`, in `_render_document_card()`, replace the "Preview Chunks" expander (lines 85-92) with:

```python
# Show chunk inspector
if doc.document_chunks:
    sorted_chunks = sorted(doc.document_chunks, key=lambda c: c.chunk_index)
    with st.expander(f"Chunk Inspector ({len(sorted_chunks)} chunks)"):
        from views.components.chunk_inspector import render_chunk_inspector
        render_chunk_inspector(sorted_chunks, key_prefix=f"browse_{doc.id}")
```

**Step 2: Make document titles clickable (link to detail page)**

In `_render_document_card()`, change the expander header to include a "View Details" button:

Replace the expander line:
```python
with st.expander(f"**[{doc.id}] {doc.title}**", expanded=False):
```

With:
```python
with st.expander(f"**[{doc.id}] {doc.title}**", expanded=False):
    # Add detail link at top
    if st.button("Open Document Detail →", key=f"detail_{doc.id}"):
        st.session_state.selected_doc_id = doc.id
        st.rerun()
```

**Step 3: Manually test**

Run: `streamlit run app.py`
- Browse page should show chunk inspector with pagination, filter, full metadata, full content
- "Open Document Detail" button should set session state (detail page built in next task)

**Step 4: Commit**

```bash
git add views/browse.py
git commit -m "feat: replace chunk preview with chunk inspector on Browse page"
```

---

### Task 6: Document Detail Page — Skeleton and Routing

**Files:**
- Create: `views/document_detail.py`
- Modify: `views/browse.py`

**Step 1: Create document_detail.py with basic routing**

```python
# views/document_detail.py
"""
Document Detail page.

Provides deep inspection of a single document: TOC navigation,
side-by-side markdown vs chunks, and full chunk list.
"""

import streamlit as st

from db.database import session_scope
from db.crud import DocumentCRUD


def render(doc_id: int):
    """Render the document detail page."""
    # Back button
    if st.button("← Back to Browse"):
        st.session_state.pop("selected_doc_id", None)
        st.rerun()

    # Load document with chunks
    with session_scope() as session:
        crud = DocumentCRUD(session)
        doc = crud.get_document_by_id(doc_id)

        if not doc:
            st.error(f"Document {doc_id} not found")
            return

        # Header
        st.header(doc.title)
        col1, col2, col3 = st.columns(3)
        col1.metric("Status", doc.status.value)
        col2.metric("Chunks", len(doc.document_chunks))
        col3.metric("ID", doc.id)

        st.markdown("---")

        # Sort chunks for consistent display
        sorted_chunks = sorted(doc.document_chunks, key=lambda c: c.chunk_index)

        # Tabs
        has_markdown = bool(doc.markdown)
        has_toc = bool(doc.doc_metadata and doc.doc_metadata.get("table_of_contents"))

        tab_labels = []
        if has_toc:
            tab_labels.append("TOC Navigator")
        tab_labels.append("Side-by-Side")
        tab_labels.append("Chunk List")

        tabs = st.tabs(tab_labels)

        tab_idx = 0

        if has_toc:
            with tabs[tab_idx]:
                _render_toc_tab(doc, sorted_chunks)
            tab_idx += 1

        with tabs[tab_idx]:
            _render_side_by_side_tab(doc, sorted_chunks)
        tab_idx += 1

        with tabs[tab_idx]:
            _render_chunk_list_tab(sorted_chunks, doc.id)


def _render_toc_tab(doc, sorted_chunks):
    """Render TOC Navigator tab."""
    st.info("TOC Navigator — coming in next task")


def _render_side_by_side_tab(doc, sorted_chunks):
    """Render Side-by-Side tab."""
    st.info("Side-by-Side view — coming in next task")


def _render_chunk_list_tab(sorted_chunks, doc_id):
    """Render Chunk List tab."""
    from views.components.chunk_inspector import render_chunk_inspector
    render_chunk_inspector(sorted_chunks, key_prefix=f"detail_{doc_id}")
```

**Step 2: Wire routing in browse.py**

At the top of `browse.py`'s `render()` function, add a check for `selected_doc_id`:

```python
def render():
    """Render the browse database page."""
    # Check if a document detail view is requested
    if st.session_state.get("selected_doc_id"):
        from views.document_detail import render as render_detail
        render_detail(st.session_state.selected_doc_id)
        return

    # ... rest of existing browse code unchanged ...
```

**Step 3: Manually test**

Run: `streamlit run app.py`
- Browse → click "Open Document Detail" on any doc → should see detail page with header, metrics, tabs
- "Chunk List" tab should work (reuses chunk inspector)
- "Back to Browse" button should return to list

**Step 4: Commit**

```bash
git add views/document_detail.py views/browse.py
git commit -m "feat: add document detail page skeleton with routing and chunk list tab"
```

---

### Task 7: Document Detail — TOC Navigator Tab

**Files:**
- Modify: `views/document_detail.py`

**Step 1: Implement `_render_toc_tab()`**

Replace the placeholder with:

```python
def _render_toc_tab(doc, sorted_chunks):
    """Render TOC Navigator tab.

    Left column: clickable TOC tree from doc_metadata.table_of_contents.
    Right column: chunks whose all_header_paths match the selected header.
    """
    toc = doc.doc_metadata.get("table_of_contents", {})

    left_col, right_col = st.columns([1, 2])

    with left_col:
        st.subheader("Table of Contents")
        # Build flat list of headers from TOC for selection
        headers = _flatten_toc(toc)
        if not headers:
            st.warning("No TOC headers found")
            return

        selected_header = st.radio(
            "Select section",
            headers,
            key="toc_header_select",
            label_visibility="collapsed",
        )

    with right_col:
        st.subheader(f"Chunks: {selected_header}")
        # Filter chunks by selected header
        matching = [
            c for c in sorted_chunks
            if _chunk_matches_header(c, selected_header)
        ]

        if not matching:
            st.info("No chunks found under this header.")
        else:
            st.caption(f"{len(matching)} chunk(s)")
            from views.components.chunk_inspector import render_chunk_inspector
            render_chunk_inspector(matching, key_prefix="toc")


def _flatten_toc(toc: dict, prefix: str = "") -> list:
    """Flatten a nested TOC dict into a list of header strings.

    The TOC structure from rebuild_toc.py is a nested dict like:
    {"1. Sutta Name": {"Introduction": {}, "Main Teaching": {}}}

    Returns flat list like:
    ["1. Sutta Name", "1. Sutta Name > Introduction", ...]
    """
    headers = []
    if isinstance(toc, dict):
        for key, children in toc.items():
            full_path = f"{prefix} > {key}" if prefix else key
            headers.append(full_path)
            headers.extend(_flatten_toc(children, full_path))
    return headers


def _chunk_matches_header(chunk, header_path: str) -> bool:
    """Check if a chunk's metadata matches the selected TOC header."""
    metadata = chunk.chunk_metadata or {}
    all_paths = metadata.get("all_header_paths", [])
    # Match if any of the chunk's header paths starts with or equals the selected path
    for path in all_paths:
        if path == header_path or path.startswith(header_path + " > "):
            return True
    # Also check header_path field directly
    hp = metadata.get("header_path", "")
    if hp == header_path or hp.startswith(header_path + " > "):
        return True
    return False
```

**Step 2: Manually test**

Run: `streamlit run app.py`
- Open a document that has a `table_of_contents` in its metadata
- TOC Navigator tab should show headers on the left
- Clicking a header should filter chunks on the right
- If doc has no TOC, tab should not appear

**Step 3: Commit**

```bash
git add views/document_detail.py
git commit -m "feat: implement TOC Navigator tab in document detail page"
```

---

### Task 8: Document Detail — Side-by-Side Tab

**Files:**
- Modify: `views/document_detail.py`

**Step 1: Implement `_render_side_by_side_tab()`**

Replace the placeholder with:

```python
def _render_side_by_side_tab(doc, sorted_chunks):
    """Render side-by-side original markdown vs chunks.

    Left column: original document markdown.
    Right column: chunks in order with visible boundaries.
    Toggle between rendered and raw markdown display.
    """
    # View mode toggle
    view_mode = st.radio(
        "View mode",
        ["Rendered", "Raw"],
        horizontal=True,
        key="side_by_side_view_mode",
    )

    left_col, right_col = st.columns(2)

    with left_col:
        st.subheader("Original Markdown")
        if doc.markdown:
            if view_mode == "Rendered":
                # Use a container with fixed height for scrolling
                with st.container(height=600):
                    st.markdown(doc.markdown)
            else:
                st.code(doc.markdown, language="markdown")
        else:
            st.warning("No markdown stored for this document.")

    with right_col:
        st.subheader(f"Chunks ({len(sorted_chunks)})")
        with st.container(height=600):
            for chunk in sorted_chunks:
                size = len(chunk.chunk_text)
                st.caption(f"— Chunk {chunk.chunk_index} ({size} chars) —")

                if view_mode == "Rendered":
                    st.markdown(chunk.chunk_text)
                else:
                    st.code(chunk.chunk_text, language="markdown")

                st.markdown("---")
```

**Step 2: Manually test**

Run: `streamlit run app.py`
- Open a completed document in detail view
- Side-by-Side tab: left shows original markdown, right shows chunks
- Toggle "Rendered" / "Raw" — both columns switch between `st.markdown()` and `st.code()`
- Document with no markdown shows warning on left, chunks still visible on right

**Step 3: Commit**

```bash
git add views/document_detail.py
git commit -m "feat: implement Side-by-Side tab with rendered/raw toggle"
```

---

### Task 9: Final Cleanup and Integration Test

**Files:**
- Modify: `app.py` (minor — clean up unused session state)

**Step 1: Remove stale session state init from app.py**

The `delete_confirm` session state in `app.py` line 43-44 is now unused (browse.py uses `pending_action`). Remove it:

```python
# Remove this block:
if "delete_confirm" not in st.session_state:
    st.session_state.delete_confirm = None
```

**Step 2: Full manual integration test**

Run: `streamlit run app.py`

Test checklist:
- [ ] **Ingest page**: Submit a URL or PDF → see 4 stage rows update in real-time (Pending → Running → Complete), log area grows, timing shown
- [ ] **Ingest page**: Failed ingestion shows red stage row + error in logs
- [ ] **Browse page**: Document cards show "Chunk Inspector" expander with pagination, filter, metadata, full text
- [ ] **Browse page**: "Open Document Detail" button navigates to detail page
- [ ] **Document Detail**: Back button returns to Browse
- [ ] **Document Detail — TOC Navigator**: Headers on left, matching chunks on right (only shown when TOC exists)
- [ ] **Document Detail — Side-by-Side**: Original markdown left, chunks right, rendered/raw toggle works
- [ ] **Document Detail — Side-by-Side**: Missing markdown shows warning
- [ ] **Document Detail — Chunk List**: Full chunk inspector at page width
- [ ] **Queue page**: Still works as before (no changes)
- [ ] **Stats page**: Still works as before (no changes)

**Step 3: Run all existing tests**

Run: `poetry run pytest tests/ -v`
Expected: All pass

**Step 4: Commit**

```bash
git add app.py
git commit -m "chore: clean up unused session state in app.py"
```
