# Chunk + TOC Integrity Audit Report

- Generated: 2026-02-27 05:04:41 UTC
- Sample size requested: 5
- Chunk samples per document: 2
- Embedding consistency check: enabled
- Seed: 42

## Global Summary

- Documents analyzed: 1
- Document verdicts: PASS=1, WARN=0, FAIL=0
- Total checks: 20
- Check outcomes: PASS=20, WARN=0, FAIL=0

## Document [17] Meditation experience is associated with differences in default mode network activity and connectivity

- Status: `completed`
- Final verdict: **PASS**
- Chunk stats: count=17, chars(min/avg/max)=665/2256.5/6773, words(min/avg/max)=91/319.5/894
- Reconstruction: similarity=1.000000 (PASS)
- Headers: markdown_paths=19, toc_paths=19, toc_entries=19
- Check outcomes: PASS=20, WARN=0, FAIL=0

### Missing Markdown Headers In TOC

- None

### Extra TOC Paths Not In Markdown

- None

### Chunk Paths Unmatched To Markdown

- None

### Check Results

| Check | Status | Message |
|---|---|---|
| chunk_indices_unique | PASS | All 17 chunk_index values are unique |
| chunk_indices_contiguous | PASS | Indices are contiguous from 0..16 |
| chunk_indices_ordered | PASS | Rows are in ascending chunk_index order |
| reconstruction_similarity | PASS | Similarity=1.000000 (markdown=38295 chars, reconstructed=38295 chars) |
| markdown_headers_extracted | PASS | Extracted 20 headers (19 unique paths) |
| toc_required_fields | PASS | All TOC entries contain id/text/level |
| toc_unique_ids | PASS | TOC entry IDs are unique |
| toc_text_values | PASS | All TOC entries have non-empty text |
| toc_level_range | PASS | All TOC levels are in range 1..6 |
| toc_parent_type | PASS | All parent_id values are null or strings |
| toc_parent_references | PASS | All parent references resolve |
| toc_cycles | PASS | No cycles in TOC parent links |
| toc_covers_markdown_headers | PASS | TOC covers all markdown header paths |
| toc_extra_paths | PASS | No extra TOC paths |
| chunk_metadata_schema | PASS | Chunk metadata schema is valid |
| chunk_metadata_empty_paths | PASS | All chunks have non-empty all_header_paths |
| chunk_paths_match_markdown | PASS | All chunk header paths match markdown paths/prefixes |
| chunk_legacy_metadata_keys | PASS | No legacy metadata keys found in chunk metadata |
| document_temp_chunks_cleared | PASS | documents.chunks is NULL for this document |
| embedding_ids_exist | PASS | All 17 chunk UUIDs found in langchain_pg_embedding.custom_id |

### Random Chunk Inspection

| Chunk Index | Verdict | Chars | Words | Header Paths | Preview | Notes |
|---:|---|---:|---:|---|---|---|
| 7 | PASS | 2504 | 373 | Fig. 3. | PNAS \| December 13, 2011 \| vol. 108 \| no. 50 \| 20257 Downloaded from https://www.pnas.org by 122.161.48.20 on February 13, 2026 from IP address 122.161.48.20. emerge to “interfere” with a task, control regions may coactivate to monitor and dampen this process. This coactivation of monitoring/control | No metadata issues for this chunk sample |
| 11 | PASS | 1878 | 263 | Imaging Data Processing, GLM Data Analysis | # Imaging Data Processing Functional images were subjected to standard preprocessing using SPM5 (Wellcome Department of Cognitive Neurology) following our prior published methods (e.g., ref. 38), which included the following steps: slice scan-time correction to the middle slice of each volume; a two | No metadata issues for this chunk sample |

## Appendix

- Seed: `42`
- Sampled document IDs: `17`

### Validation Rules

- Reconstruction similarity: PASS `>= 0.995`, WARN `0.98-0.995`, FAIL `< 0.98`.
- Unmatched chunk paths: FAIL if count `>= 3`; otherwise WARN.
- TOC missing markdown paths: FAIL.
- Extra TOC paths not in markdown: WARN.
