# Chunk Metadata Restructure Design

**Date**: 2026-02-16
**Status**: Approved
**Goal**: Clean up chunk metadata — remove redundancy, add proper header paths with levels

## Problem

Current chunk metadata has ~12 fields with significant redundancy and clutter:
- `uuid`, `chunk_index` duplicate DB columns
- `doc_title` and `original_doc_title` duplicate each other
- `Header 1`, `Header 2`, etc. as flat top-level keys
- `all_headers` as a list of dicts (verbose)
- `primary_header`, `header_level`, `section_path` are all derivable
- No proper root-to-current header path

## New Metadata Shape

### Standard chunk (single header path)

```json
{
  "all_header_paths": [
    "PSYCHOLOGICAL AND COGNITIVE SCIENCES > Methods > Participants"
  ],
  "header_level_map": {
    "PSYCHOLOGICAL AND COGNITIVE SCIENCES": 1,
    "Methods": 3,
    "Participants": 4
  },
  "doc_title": "Meditation experience is associated with...",
  "char_count": 1250,
  "word_count": 172
}
```

### Combined chunk (branching header paths)

```json
{
  "all_header_paths": [
    "Digha Nikaya > Brahmajala Sutta > Chapter 1",
    "Digha Nikaya > Brahmajala Sutta > Chapter 2"
  ],
  "header_level_map": {
    "Digha Nikaya": 1,
    "Brahmajala Sutta": 2,
    "Chapter 1": 3,
    "Chapter 2": 3
  },
  "doc_title": "Digha Nikaya",
  "char_count": 1803,
  "word_count": 291,
  "is_combined": true
}
```

## Fields (6 total, down from ~12)

| Field | Type | Purpose |
|---|---|---|
| `all_header_paths` | `list[str]` | Every header path in the chunk, delimited by ` > `. Always present, always a list. |
| `header_level_map` | `dict[str, int]` | Maps header text to its original markdown heading level (1-6). Shared across paths. |
| `doc_title` | `str` | Source document title. Kept because it travels with the chunk into the vector store. |
| `char_count` | `int` | Character count of chunk text. |
| `word_count` | `int` | Word count of chunk text. |
| `is_combined` | `bool` | Present only when `true`. Flags chunks created by merging smaller chunks. |

## Removed Fields

| Field | Reason |
|---|---|
| `uuid` | Already a DB column on `chunks` table |
| `chunk_index` | Already a DB column on `chunks` table |
| `original_doc_id` | Use `document_id` FK on the DB row |
| `original_doc_title` | Redundant with `doc_title` |
| `Header 1`, `Header 2`, etc. | Replaced by `all_header_paths` |
| `all_headers` (list of dicts) | Replaced by `all_header_paths` (list of strings) |
| `primary_header` | Derivable: last segment of `all_header_paths[0]` |
| `header_level` | Derivable: count segments of `all_header_paths[0]` |
| `section_path` | Replaced by `all_header_paths[0]` |

## Derived Values

These no longer need storage — compute on read:

```python
# Primary header (deepest in first path)
primary_header = all_header_paths[0].split(" > ")[-1]

# Header depth
header_level = len(all_header_paths[0].split(" > "))

# Display breadcrumb
breadcrumb = all_header_paths[0]
```

## TOC Reconstruction

Document-level table of contents is built by collecting `all_header_paths` across all chunks:

```python
all_paths = set()
for chunk in document.chunks:
    for path in chunk.chunk_metadata["all_header_paths"]:
        all_paths.add(path)

# Each path encodes hierarchy; header_level_map provides original md levels
for path in sorted(all_paths):
    segments = path.split(" > ")
    for segment in segments:
        level = chunk.chunk_metadata["header_level_map"].get(segment)
```

No separate TOC-building logic needed — falls out naturally from chunk metadata.

## Affected Code

1. **`ingestion/chunking.py`** — `_extract_headers`, `_merge_metadata`, `_add_final_metadata` — build new structure
2. **`ingestion/stages.py`** — `EmbeddingStage` (stop adding `uuid`, `original_doc_id`, etc. to metadata), `DatabasePersistenceStage._build_table_of_contents` (read from new format)
3. **`scripts/rebuild_toc.py`** — Update to read/write new metadata format
4. **`db/crud.py`** — No schema changes needed (metadata is JSONB), but update any code that reads old field names
