# Chunk Metadata Restructure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restructure chunk metadata from ~12 cluttered fields to 6 clean fields, replacing Header N keys with `all_header_paths` (delimited strings) and `header_level_map`.

**Architecture:** The internal chunking pipeline (`_split_by_headers` → `_split_oversized_chunks` → `_combine_small_chunks`) continues to use LangChain's `Header N` format. The transformation to the new format happens in `_add_final_metadata` — the last step before chunks leave the chunker. Downstream consumers (EmbeddingStage, DatabasePersistenceStage, rebuild_toc.py) are then updated to read the new format.

**Tech Stack:** Python 3.11+, LangChain, SQLAlchemy, PostgreSQL JSONB, pytest

**Design doc:** [docs/plans/2026-02-16-chunk-metadata-restructure-design.md](docs/plans/2026-02-16-chunk-metadata-restructure-design.md)

---

### Task 1: Set up test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/test_chunking_metadata.py`

**Step 1: Create test directory and init file**

```bash
mkdir -p tests
touch tests/__init__.py
```

**Step 2: Write failing tests for `_build_header_path` helper**

Create `tests/test_chunking_metadata.py`:

```python
"""Tests for chunk metadata restructure."""

import pytest
from langchain.schema import Document
from ingestion.chunking import MarkdownChunker, Config


class TestBuildHeaderPath:
    """Tests for _build_header_path helper."""

    def setup_method(self):
        self.chunker = MarkdownChunker(
            text="# Test\nSome content",
            config=Config(enable_semantic=False),
        )

    def test_single_header(self):
        header_dict = {"Header 1": "Introduction"}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Introduction"
        assert level_map == {"Introduction": 1}

    def test_nested_headers(self):
        header_dict = {"Header 1": "Digha Nikaya", "Header 2": "Brahmajala Sutta", "Header 3": "Chapter 1"}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Digha Nikaya > Brahmajala Sutta > Chapter 1"
        assert level_map == {"Digha Nikaya": 1, "Brahmajala Sutta": 2, "Chapter 1": 3}

    def test_skipped_levels(self):
        header_dict = {"Header 1": "Title", "Header 3": "Deep Section"}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Title > Deep Section"
        assert level_map == {"Title": 1, "Deep Section": 3}

    def test_empty_dict(self):
        path, level_map = self.chunker._build_header_path({})
        assert path == ""
        assert level_map == {}

    def test_non_header_keys_ignored(self):
        header_dict = {"Header 1": "Title", "is_combined": True, "chunk_index": 0}
        path, level_map = self.chunker._build_header_path(header_dict)
        assert path == "Title"
        assert level_map == {"Title": 1}
```

**Step 3: Run tests to verify they fail**

Run: `poetry run pytest tests/test_chunking_metadata.py::TestBuildHeaderPath -v`
Expected: FAIL with `AttributeError: 'MarkdownChunker' object has no attribute '_build_header_path'`

**Step 4: Commit test scaffolding**

```bash
git add tests/__init__.py tests/test_chunking_metadata.py
git commit -m "test: add failing tests for _build_header_path helper"
```

---

### Task 2: Implement `_build_header_path` helper

**Files:**
- Modify: `ingestion/chunking.py:418` (add method after `_extract_header_set`)

**Step 1: Add `_build_header_path` method to MarkdownChunker**

Add after `_extract_header_set` (line 420) in `ingestion/chunking.py`:

```python
def _build_header_path(self, header_dict: Dict[str, str]) -> Tuple[str, Dict[str, int]]:
    """Build a header path string and level map from a Header N dict.

    Args:
        header_dict: Dict like {"Header 1": "Title", "Header 3": "Section"}

    Returns:
        Tuple of (path_string, level_map):
            path_string: "Title > Section"
            level_map: {"Title": 1, "Section": 3}
    """
    levels = {}
    for key, value in header_dict.items():
        if key.startswith("Header "):
            level = int(key.split()[1])
            levels[level] = value

    if not levels:
        return "", {}

    sorted_levels = sorted(levels.keys())
    path_parts = [levels[l] for l in sorted_levels]
    level_map = {levels[l]: l for l in sorted_levels}

    return " > ".join(path_parts), level_map
```

**Step 2: Run tests to verify they pass**

Run: `poetry run pytest tests/test_chunking_metadata.py::TestBuildHeaderPath -v`
Expected: All 5 tests PASS

**Step 3: Commit**

```bash
git add ingestion/chunking.py
git commit -m "feat: add _build_header_path helper for metadata restructure"
```

---

### Task 3: Write tests for new `_add_final_metadata` behavior

**Files:**
- Modify: `tests/test_chunking_metadata.py`

**Step 1: Add test class for `_add_final_metadata`**

Append to `tests/test_chunking_metadata.py`:

```python
class TestAddFinalMetadata:
    """Tests for _add_final_metadata with new metadata format."""

    def setup_method(self):
        self.chunker = MarkdownChunker(
            text="# Test Doc\nSome content",
            config=Config(enable_semantic=False),
            title="Test Doc",
        )

    def test_single_header_chunk(self):
        """Non-combined chunk gets single path in all_header_paths."""
        chunks = [
            Document(
                page_content="Some content about meditation.",
                metadata={"Header 1": "Digha Nikaya", "Header 2": "Sutta 1"},
            )
        ]
        result = self.chunker._add_final_metadata(chunks)
        meta = result[0].metadata

        assert meta["all_header_paths"] == ["Digha Nikaya > Sutta 1"]
        assert meta["header_level_map"] == {"Digha Nikaya": 1, "Sutta 1": 2}
        assert meta["doc_title"] == "Test Doc"
        assert meta["word_count"] == 4
        assert meta["char_count"] == 30
        # Old fields must be gone
        assert "Header 1" not in meta
        assert "Header 2" not in meta
        assert "primary_header" not in meta
        assert "header_level" not in meta
        assert "section_path" not in meta
        assert "chunk_index" not in meta

    def test_combined_chunk_with_all_headers(self):
        """Combined chunk with all_headers gets multiple paths."""
        chunks = [
            Document(
                page_content="Content spanning sections.",
                metadata={
                    "Header 1": "DN",
                    "Header 2": "Sutta 1",
                    "is_combined": True,
                    "all_headers": [
                        {"Header 1": "DN", "Header 2": "Sutta 1"},
                        {"Header 1": "DN", "Header 2": "Sutta 2"},
                    ],
                },
            )
        ]
        result = self.chunker._add_final_metadata(chunks)
        meta = result[0].metadata

        assert meta["all_header_paths"] == ["DN > Sutta 1", "DN > Sutta 2"]
        assert meta["header_level_map"] == {"DN": 1, "Sutta 1": 2, "Sutta 2": 2}
        assert meta["is_combined"] is True
        assert "all_headers" not in meta
        assert "Header 1" not in meta

    def test_chunk_with_no_headers(self):
        """Chunk without headers gets empty paths."""
        chunks = [
            Document(page_content="Standalone content.", metadata={})
        ]
        result = self.chunker._add_final_metadata(chunks)
        meta = result[0].metadata

        assert meta["all_header_paths"] == []
        assert meta["header_level_map"] == {}
        assert meta["doc_title"] == "Test Doc"

    def test_is_semantic_split_preserved(self):
        """is_semantic_split flag survives transformation."""
        chunks = [
            Document(
                page_content="Split content.",
                metadata={"Header 1": "Title", "is_semantic_split": True},
            )
        ]
        result = self.chunker._add_final_metadata(chunks)
        assert result[0].metadata["is_semantic_split"] is True
```

**Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_chunking_metadata.py::TestAddFinalMetadata -v`
Expected: FAIL — old `_add_final_metadata` produces old-format metadata

**Step 3: Commit**

```bash
git add tests/test_chunking_metadata.py
git commit -m "test: add failing tests for new _add_final_metadata format"
```

---

### Task 4: Rewrite `_add_final_metadata` to produce new format

**Files:**
- Modify: `ingestion/chunking.py:459-482`

**Step 1: Replace `_add_final_metadata`**

Replace lines 459-482 in `ingestion/chunking.py` with:

```python
def _add_final_metadata(self, chunks: List[Document]) -> List[Document]:
    """Transform chunk metadata to final format with header paths.

    Converts internal Header N keys and all_headers lists into the
    clean output format: all_header_paths (list of delimited strings)
    and header_level_map (dict of header text to level).

    Removes all intermediate metadata fields (Header N, all_headers,
    chunk_index, primary_header, header_level, section_path).
    """
    for i, chunk in enumerate(chunks):
        # Collect header dicts from all_headers (combined) or Header N keys
        all_headers = chunk.metadata.get("all_headers", [])
        if not all_headers:
            header_set = self._extract_header_set(chunk.metadata)
            if header_set:
                all_headers = [header_set]

        # Build paths and level map
        all_paths = []
        level_map = {}
        for h_dict in all_headers:
            path, lmap = self._build_header_path(h_dict)
            if path and path not in all_paths:
                all_paths.append(path)
            level_map.update(lmap)

        # Remove old keys
        keys_to_remove = [k for k in chunk.metadata if k.startswith("Header ")]
        keys_to_remove.extend([
            "all_headers", "primary_header", "header_level",
            "section_path", "chunk_index",
        ])
        for key in keys_to_remove:
            chunk.metadata.pop(key, None)

        # Set new metadata
        chunk.metadata["all_header_paths"] = all_paths
        chunk.metadata["header_level_map"] = level_map
        chunk.metadata["doc_title"] = self.title
        chunk.metadata["word_count"] = len(chunk.page_content.split())
        chunk.metadata["char_count"] = len(chunk.page_content)

    return chunks
```

**Step 2: Run tests to verify they pass**

Run: `poetry run pytest tests/test_chunking_metadata.py -v`
Expected: All tests PASS (both TestBuildHeaderPath and TestAddFinalMetadata)

**Step 3: Commit**

```bash
git add ingestion/chunking.py
git commit -m "feat: rewrite _add_final_metadata to produce new header path format"
```

---

### Task 5: Update EmbeddingStage to stop adding redundant metadata

**Files:**
- Modify: `ingestion/stages.py:224-233`

**Step 1: Remove redundant metadata additions from EmbeddingStage**

Replace lines 224-233 in `ingestion/stages.py`:

```python
            # Add UUIDs and metadata to each chunk BEFORE embedding
            for idx, chunk in enumerate(context.chunks):
                # Generate UUID for linking with database
                chunk_uuid = str(uuid_lib.uuid4())

                # Add to metadata
                chunk.metadata["uuid"] = chunk_uuid
                chunk.metadata["original_doc_id"] = context.document_id
                chunk.metadata["original_doc_title"] = context.title
                chunk.metadata["chunk_index"] = idx
```

With:

```python
            # Add UUIDs to each chunk BEFORE embedding
            for chunk in context.chunks:
                chunk.metadata["uuid"] = str(uuid_lib.uuid4())
```

**Step 2: Commit**

```bash
git add ingestion/stages.py
git commit -m "refactor: remove redundant metadata from EmbeddingStage"
```

---

### Task 6: Write tests for TOC builder with new format

**Files:**
- Modify: `tests/test_chunking_metadata.py`

**Step 1: Add test class for `_build_table_of_contents`**

Append to `tests/test_chunking_metadata.py`:

```python
from ingestion.stages import DatabasePersistenceStage


class TestBuildTableOfContents:
    """Tests for TOC builder with new metadata format."""

    def setup_method(self):
        self.stage = DatabasePersistenceStage()

    def test_single_path_chunks(self):
        chunks = [
            Document(
                page_content="Content",
                metadata={
                    "all_header_paths": ["DN > Sutta 1"],
                    "header_level_map": {"DN": 1, "Sutta 1": 2},
                },
            ),
            Document(
                page_content="Content",
                metadata={
                    "all_header_paths": ["DN > Sutta 2"],
                    "header_level_map": {"DN": 1, "Sutta 2": 2},
                },
            ),
        ]
        toc = self.stage._build_table_of_contents(chunks)

        assert len(toc["entries"]) == 3  # DN, Sutta 1, Sutta 2
        assert toc["entries"][0]["text"] == "DN"
        assert toc["entries"][0]["level"] == 1
        assert toc["entries"][1]["text"] == "Sutta 1"
        assert toc["entries"][1]["level"] == 2
        assert toc["entries"][1]["parent_id"] == toc["entries"][0]["id"]

    def test_combined_chunk_multiple_paths(self):
        chunks = [
            Document(
                page_content="Content",
                metadata={
                    "all_header_paths": ["DN > Sutta 1", "DN > Sutta 2"],
                    "header_level_map": {"DN": 1, "Sutta 1": 2, "Sutta 2": 2},
                },
            ),
        ]
        toc = self.stage._build_table_of_contents(chunks)

        assert len(toc["entries"]) == 3  # DN, Sutta 1, Sutta 2

    def test_empty_chunks(self):
        toc = self.stage._build_table_of_contents([])
        assert toc["entries"] == []
        assert toc["text"] == ""

    def test_chunks_with_no_headers(self):
        chunks = [
            Document(
                page_content="Content",
                metadata={"all_header_paths": [], "header_level_map": {}},
            ),
        ]
        toc = self.stage._build_table_of_contents(chunks)
        assert toc["entries"] == []
```

**Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/test_chunking_metadata.py::TestBuildTableOfContents -v`
Expected: FAIL — old `_build_table_of_contents` reads `all_headers` / `Header N`, not `all_header_paths`

**Step 3: Commit**

```bash
git add tests/test_chunking_metadata.py
git commit -m "test: add failing tests for TOC builder with new metadata format"
```

---

### Task 7: Rewrite `_build_table_of_contents` and update `DatabasePersistenceStage`

**Files:**
- Modify: `ingestion/stages.py:277-349` (TOC builder)
- Modify: `ingestion/stages.py:394-398` (strip uuid from chunk_metadata)

**Step 1: Replace `_build_table_of_contents`**

Replace lines 277-349 in `ingestion/stages.py` with:

```python
    def _build_table_of_contents(self, chunks: List) -> dict:
        """
        Build table of contents from chunk header paths.

        Reads all_header_paths and header_level_map from chunk metadata
        to construct a hierarchical TOC.

        Args:
            chunks: List of LangChain Documents with header path metadata

        Returns:
            Dict with 'entries' (structured list) and 'text' (indented string)
        """
        entries = []
        header_stack = []  # [(level, text, id), ...]
        seen_headers = set()
        entry_count = 0

        for idx, chunk in enumerate(chunks):
            metadata = chunk.metadata or {}
            paths = metadata.get("all_header_paths", [])
            level_map = metadata.get("header_level_map", {})

            for path in paths:
                segments = path.split(" > ")
                for segment in segments:
                    level = level_map.get(segment, 1)

                    header_key = (level, segment)
                    if header_key in seen_headers:
                        continue
                    seen_headers.add(header_key)

                    while header_stack and header_stack[-1][0] >= level:
                        header_stack.pop()

                    entry_id = f"h{level}_{entry_count}"
                    parent_id = header_stack[-1][2] if header_stack else None

                    entries.append({
                        "id": entry_id,
                        "level": level,
                        "text": segment,
                        "parent_id": parent_id,
                        "chunk_index": idx,
                    })

                    header_stack.append((level, segment, entry_id))
                    entry_count += 1

        text_lines = []
        for entry in entries:
            indent = "  " * (entry["level"] - 1)
            text_lines.append(f"{indent}{entry['text']}")

        logger.debug(f"Built TOC with {len(entries)} entries")
        return {
            "entries": entries,
            "text": "\n".join(text_lines),
        }
```

**Step 2: Strip uuid from chunk_metadata before DB save**

In `ingestion/stages.py`, in the `execute` method of `DatabasePersistenceStage`, replace line 398:

```python
                        "chunk_metadata": chunk.metadata,
```

With:

```python
                        "chunk_metadata": {
                            k: v for k, v in chunk.metadata.items()
                            if k != "uuid"
                        },
```

**Step 3: Run tests to verify they pass**

Run: `poetry run pytest tests/test_chunking_metadata.py -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add ingestion/stages.py
git commit -m "feat: rewrite TOC builder for new metadata format, strip uuid from DB metadata"
```

---

### Task 8: Update `rebuild_toc.py` for new metadata format

**Files:**
- Modify: `scripts/rebuild_toc.py:57-69` (`extract_headers_from_text`)
- Modify: `scripts/rebuild_toc.py:277-383` (`rebuild_document`)

**Step 1: Replace `extract_headers_from_text` to return path-based format**

Replace lines 57-69 in `scripts/rebuild_toc.py` with:

```python
def extract_headers_from_text(text: str) -> Tuple[List[str], Dict[str, int]]:
    """
    Extract markdown headers from text and return as paths and level map.

    Returns:
        Tuple of (all_header_paths, header_level_map)
    """
    current_headers = [None] * 7  # levels 0-6
    paths = []
    level_map = {}

    for match in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE):
        level = len(match.group(1))
        header = match.group(2).strip()
        current_headers[level] = header
        for i in range(level + 1, 7):
            current_headers[i] = None

        # Snapshot current path
        parts = []
        for l in range(1, 7):
            if current_headers[l]:
                parts.append(current_headers[l])
                level_map[current_headers[l]] = l

        path = " > ".join(parts)
        if path and path not in paths:
            paths.append(path)

    return paths, level_map
```

**Step 2: Update `rebuild_document` to write new format**

Replace the chunk backfill loop in `rebuild_document` (lines 322-357) with:

```python
    # --- Step B: Rebuild header paths on chunks ---
    chunks_updated = 0
    new_chunk_headers = set()

    # Maintain running header context across ordered chunks
    running_headers = [None] * 7  # levels 0-6

    for chunk in chunks:
        # Extract headers from chunk text
        chunk_paths = []
        chunk_level_map = {}

        chunk_header_matches = list(
            re.finditer(r"^(#{1,6})\s+(.+)$", chunk.chunk_text, re.MULTILINE)
        )

        if chunk_header_matches:
            for match in chunk_header_matches:
                level = len(match.group(1))
                header = match.group(2).strip()
                running_headers[level] = header
                for i in range(level + 1, 7):
                    running_headers[i] = None

                # Snapshot path
                parts = []
                for l in range(1, 7):
                    if running_headers[l]:
                        parts.append(running_headers[l])
                        chunk_level_map[running_headers[l]] = l

                path = " > ".join(parts)
                if path and path not in chunk_paths:
                    chunk_paths.append(path)

                new_chunk_headers.add((level, header))
        else:
            # No headers in chunk — use running context
            parts = []
            for l in range(1, 7):
                if running_headers[l]:
                    parts.append(running_headers[l])
                    chunk_level_map[running_headers[l]] = l
            path = " > ".join(parts)
            if path:
                chunk_paths = [path]

        if not chunk_paths and not chunk_level_map:
            continue

        metadata_updates = {
            "all_header_paths": chunk_paths,
            "header_level_map": chunk_level_map,
        }

        # Remove old-format keys if present
        old_meta = chunk.chunk_metadata or {}
        keys_to_remove = [k for k in old_meta if k.startswith("Header ")]
        keys_to_remove.extend([
            "all_headers", "primary_header", "header_level",
            "section_path",
        ])
        if keys_to_remove and not dry_run:
            cleaned = {k: v for k, v in old_meta.items() if k not in keys_to_remove}
            cleaned.update(metadata_updates)
            chunk_crud.update_chunk_metadata(
                chunk_id=chunk.id,
                metadata_updates=cleaned,
                merge=False,
            )
        elif not dry_run:
            chunk_crud.update_chunk_metadata(
                chunk_id=chunk.id,
                metadata_updates=metadata_updates,
                merge=True,
            )

        chunks_updated += 1
```

**Step 3: Update the before-stats counting** (lines 309-316)

Replace with:

```python
    old_chunk_headers = set()
    for chunk in chunks:
        meta = chunk.chunk_metadata or {}
        # Check new format
        for path in meta.get("all_header_paths", []):
            for segment in path.split(" > "):
                level = meta.get("header_level_map", {}).get(segment, 0)
                old_chunk_headers.add((level, segment))
        # Check old format as fallback
        for level in range(1, 7):
            h = meta.get(f"Header {level}")
            if h:
                old_chunk_headers.add((level, h))
```

**Step 4: Run rebuild script in dry-run mode to verify**

Run: `poetry run python scripts/rebuild_toc.py --all --dry-run`
Expected: No errors, shows preview of changes

**Step 5: Commit**

```bash
git add scripts/rebuild_toc.py
git commit -m "feat: update rebuild_toc.py for new header path metadata format"
```

---

### Task 9: Run full test suite and integration check

**Step 1: Run all tests**

Run: `poetry run pytest tests/ -v`
Expected: All tests PASS

**Step 2: Quick smoke test of chunking pipeline**

Run:
```bash
poetry run python -c "
import asyncio
from ingestion.chunking import MarkdownChunker, Config

md = '''# Title
## Section A
Content for section A.

## Section B
### Subsection B1
Content for B1.

### Subsection B2
Content for B2.
'''

async def test():
    chunker = MarkdownChunker(text=md, config=Config(enable_semantic=False, min_size=10, max_size=2000))
    chunks, stats = await chunker.chunk()
    for c in chunks:
        print(c.metadata)
        print('---')

asyncio.run(test())
"
```
Expected: Each chunk has `all_header_paths`, `header_level_map`, `doc_title`, `word_count`, `char_count`. No `Header N`, `section_path`, `primary_header`, etc.

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete chunk metadata restructure - all_header_paths format"
```
