#!/usr/bin/env python3
"""
Read-only validation for document chunk integrity and TOC consistency.

This script samples completed documents and checks:
- Chunk index/order integrity
- Reconstructed content similarity vs stored markdown
- Markdown headers vs document-level table_of_contents
- Chunk metadata quality (all_header_paths/header_level_map)
- Optional embedding consistency (chunks.uuid in langchain_pg_embedding.id)

Usage:
    poetry run python scripts/validate_chunk_toc_integrity.py \
      --sample-size 5 \
      --seed 42 \
      --chunk-sample-per-doc 3 \
      --check-embeddings \
      --output reports/chunk_toc_validation.md

Unit tests:
    poetry run pytest tests/test_chunk_toc_validation.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import random
import re
import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text

# Add repo root to sys.path when running as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))


PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


@dataclass(frozen=True)
class CheckResult:
    """Single validation check outcome."""

    name: str
    status: str
    message: str


def normalize_whitespace(value: str) -> str:
    """Collapse whitespace for robust text similarity comparison."""
    return re.sub(r"\s+", " ", (value or "").strip())


def normalize_header_path(path: str) -> str:
    """Normalize path separators/spaces to canonical ' > '."""
    parts = [part.strip() for part in str(path).split(">") if part.strip()]
    return " > ".join(parts)


def clean_header_text(raw: str) -> str:
    """Clean markdown header text (e.g., remove trailing #'s)."""
    text_value = (raw or "").strip()
    text_value = re.sub(r"\s+#+\s*$", "", text_value)
    return text_value.strip()


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    """Return unique values preserving insertion order."""
    seen = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def extract_markdown_headers(markdown: str) -> list[dict[str, Any]]:
    """
    Extract ordered markdown headers and path_from_root.

    Returns list of dicts:
      {line, level, text, path_from_root}
    """
    headers: list[dict[str, Any]] = []
    running_headers: list[str | None] = [None] * 7  # levels 0..6

    for lineno, line in enumerate((markdown or "").splitlines(), start=1):
        match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if not match:
            continue

        level = len(match.group(1))
        text_value = clean_header_text(match.group(2))
        if not text_value:
            continue

        running_headers[level] = text_value
        for deeper in range(level + 1, 7):
            running_headers[deeper] = None

        path_from_root = " > ".join(
            header for header in running_headers[1:] if header
        )
        headers.append(
            {
                "line": lineno,
                "level": level,
                "text": text_value,
                "path_from_root": path_from_root,
            }
        )

    return headers


def sample_documents(
    documents: Sequence[Mapping[str, Any]],
    sample_size: int,
    seed: int,
) -> list[Mapping[str, Any]]:
    """Deterministically sample documents using seed."""
    docs = list(documents)
    if sample_size <= 0:
        return []
    if len(docs) <= sample_size:
        return docs
    rng = random.Random(seed)
    sampled = rng.sample(docs, sample_size)
    return sorted(sampled, key=lambda doc: doc["id"])


def validate_chunk_index_integrity(chunks: Sequence[Mapping[str, Any]]) -> list[CheckResult]:
    """Validate uniqueness/contiguity/order of chunk_index values."""
    checks: list[CheckResult] = []
    indices = [chunk.get("chunk_index") for chunk in chunks]

    if not indices:
        checks.append(CheckResult("chunk_indices_present", FAIL, "No chunks found"))
        return checks

    if any(not isinstance(idx, int) for idx in indices):
        checks.append(
            CheckResult(
                "chunk_indices_type",
                FAIL,
                "One or more chunk_index values are missing or non-integer",
            )
        )
        return checks

    unique_count = len(set(indices))
    if unique_count != len(indices):
        checks.append(
            CheckResult(
                "chunk_indices_unique",
                FAIL,
                f"Duplicate chunk_index values found ({len(indices) - unique_count} duplicates)",
            )
        )
    else:
        checks.append(
            CheckResult(
                "chunk_indices_unique",
                PASS,
                f"All {len(indices)} chunk_index values are unique",
            )
        )

    expected = list(range(len(indices)))
    sorted_indices = sorted(indices)
    if sorted_indices != expected:
        checks.append(
            CheckResult(
                "chunk_indices_contiguous",
                FAIL,
                f"Indices are not contiguous from 0..{len(indices) - 1}",
            )
        )
    else:
        checks.append(
            CheckResult(
                "chunk_indices_contiguous",
                PASS,
                f"Indices are contiguous from 0..{len(indices) - 1}",
            )
        )

    in_order = all(index == expected_index for expected_index, index in enumerate(indices))
    if not in_order:
        checks.append(
            CheckResult(
                "chunk_indices_ordered",
                FAIL,
                "Rows are not in ascending chunk_index order",
            )
        )
    else:
        checks.append(
            CheckResult(
                "chunk_indices_ordered",
                PASS,
                "Rows are in ascending chunk_index order",
            )
        )

    return checks


def classify_similarity(score: float) -> str:
    """Classify reconstruction similarity score."""
    if score >= 0.995:
        return PASS
    if score >= 0.98:
        return WARN
    return FAIL


def evaluate_reconstruction(markdown: str, chunks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare normalized markdown with reconstructed chunk text."""
    reconstructed = "\n\n".join((chunk.get("chunk_text") or "") for chunk in chunks)
    normalized_markdown = normalize_whitespace(markdown or "")
    normalized_reconstructed = normalize_whitespace(reconstructed)
    similarity = difflib.SequenceMatcher(
        None,
        normalized_markdown,
        normalized_reconstructed,
    ).ratio()

    status = classify_similarity(similarity)
    message = (
        f"Similarity={similarity:.6f} "
        f"(markdown={len(normalized_markdown)} chars, "
        f"reconstructed={len(normalized_reconstructed)} chars)"
    )
    return {
        "status": status,
        "message": message,
        "similarity": similarity,
        "normalized_markdown_len": len(normalized_markdown),
        "normalized_reconstructed_len": len(normalized_reconstructed),
    }


def _path_matches_markdown(path: str, markdown_paths: set[str]) -> bool:
    """Allow exact match or ancestor/descendant path relation."""
    if path in markdown_paths:
        return True
    for md_path in markdown_paths:
        if md_path.startswith(path + " > ") or path.startswith(md_path + " > "):
            return True
    return False


def validate_toc_entries(
    toc: Any,
    markdown_paths: Sequence[str],
) -> dict[str, Any]:
    """Validate TOC structure and compare TOC paths with markdown paths."""
    checks: list[CheckResult] = []
    markdown_path_set = set(markdown_paths)
    toc_paths: list[str] = []
    missing_paths: list[str] = []
    extra_paths: list[str] = []

    if not isinstance(toc, dict):
        if markdown_path_set:
            checks.append(
                CheckResult(
                    "toc_entries_exists",
                    FAIL,
                    "table_of_contents is missing while markdown headers exist",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "toc_entries_exists",
                    PASS,
                    "No markdown headers and no table_of_contents",
                )
            )
        return {
            "checks": checks,
            "toc_paths": toc_paths,
            "missing_paths": missing_paths,
            "extra_paths": extra_paths,
            "entry_count": 0,
        }

    entries = toc.get("entries")
    if not isinstance(entries, list):
        if markdown_path_set:
            checks.append(
                CheckResult(
                    "toc_entries_list",
                    FAIL,
                    "table_of_contents.entries is missing or not a list",
                )
            )
        else:
            checks.append(
                CheckResult(
                    "toc_entries_list",
                    PASS,
                    "No markdown headers; TOC entries missing is acceptable",
                )
            )
        return {
            "checks": checks,
            "toc_paths": toc_paths,
            "missing_paths": missing_paths,
            "extra_paths": extra_paths,
            "entry_count": 0,
        }

    if not entries and markdown_path_set:
        checks.append(
            CheckResult(
                "toc_entries_non_empty",
                FAIL,
                "TOC entries are empty while markdown headers exist",
            )
        )

    id_map: dict[str, dict[str, Any]] = {}
    duplicate_ids: set[str] = set()
    missing_required_count = 0
    invalid_level_count = 0
    invalid_parent_type_count = 0
    invalid_text_count = 0

    for entry in entries:
        if not isinstance(entry, dict):
            missing_required_count += 1
            continue

        required_keys = {"id", "text", "level"}
        if not required_keys.issubset(set(entry.keys())):
            missing_required_count += 1
            continue

        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id.strip():
            missing_required_count += 1
            continue
        if entry_id in id_map:
            duplicate_ids.add(entry_id)
        id_map[entry_id] = entry

        text_value = entry.get("text")
        if not isinstance(text_value, str) or not text_value.strip():
            invalid_text_count += 1

        level = entry.get("level")
        if not isinstance(level, int) or not (1 <= level <= 6):
            invalid_level_count += 1

        parent_id = entry.get("parent_id")
        if parent_id is not None and not isinstance(parent_id, str):
            invalid_parent_type_count += 1

    if missing_required_count:
        checks.append(
            CheckResult(
                "toc_required_fields",
                FAIL,
                f"{missing_required_count} TOC entries missing required fields",
            )
        )
    else:
        checks.append(
            CheckResult(
                "toc_required_fields",
                PASS,
                "All TOC entries contain id/text/level",
            )
        )

    if duplicate_ids:
        checks.append(
            CheckResult(
                "toc_unique_ids",
                FAIL,
                f"Duplicate TOC entry IDs found: {sorted(duplicate_ids)[:5]}",
            )
        )
    else:
        checks.append(CheckResult("toc_unique_ids", PASS, "TOC entry IDs are unique"))

    if invalid_text_count:
        checks.append(
            CheckResult(
                "toc_text_values",
                FAIL,
                f"{invalid_text_count} TOC entries have invalid text values",
            )
        )
    else:
        checks.append(
            CheckResult(
                "toc_text_values",
                PASS,
                "All TOC entries have non-empty text",
            )
        )

    if invalid_level_count:
        checks.append(
            CheckResult(
                "toc_level_range",
                FAIL,
                f"{invalid_level_count} TOC entries have levels outside 1..6",
            )
        )
    else:
        checks.append(
            CheckResult(
                "toc_level_range",
                PASS,
                "All TOC levels are in range 1..6",
            )
        )

    if invalid_parent_type_count:
        checks.append(
            CheckResult(
                "toc_parent_type",
                FAIL,
                f"{invalid_parent_type_count} TOC entries have non-string parent_id",
            )
        )
    else:
        checks.append(
            CheckResult(
                "toc_parent_type",
                PASS,
                "All parent_id values are null or strings",
            )
        )

    orphan_parent_count = 0
    for entry in id_map.values():
        parent_id = entry.get("parent_id")
        if parent_id and parent_id not in id_map:
            orphan_parent_count += 1

    if orphan_parent_count:
        checks.append(
            CheckResult(
                "toc_parent_references",
                FAIL,
                f"{orphan_parent_count} TOC entries have missing parent references",
            )
        )
    else:
        checks.append(
            CheckResult(
                "toc_parent_references",
                PASS,
                "All parent references resolve",
            )
        )

    cycle_count = 0
    state: dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=visited

    def visit(node_id: str) -> bool:
        nonlocal cycle_count
        node_state = state.get(node_id, 0)
        if node_state == 1:
            cycle_count += 1
            return True
        if node_state == 2:
            return False
        state[node_id] = 1
        parent_id = id_map[node_id].get("parent_id")
        if parent_id in id_map and visit(parent_id):
            state[node_id] = 2
            return True
        state[node_id] = 2
        return False

    for entry_id in id_map:
        if state.get(entry_id, 0) == 0:
            visit(entry_id)

    if cycle_count:
        checks.append(
            CheckResult(
                "toc_cycles",
                FAIL,
                "Cycle detected in TOC parent links",
            )
        )
    else:
        checks.append(
            CheckResult(
                "toc_cycles",
                PASS,
                "No cycles in TOC parent links",
            )
        )

    path_cache: dict[str, str] = {}

    def build_path(entry_id: str, active: set[str] | None = None) -> str:
        if entry_id in path_cache:
            return path_cache[entry_id]

        active = active or set()
        if entry_id in active:
            # Break recursive loop in malformed cyclic TOC structures.
            return clean_header_text(str(id_map[entry_id].get("text", "")))
        active.add(entry_id)

        entry = id_map[entry_id]
        explicit_path = entry.get("path_from_root")
        if isinstance(explicit_path, str) and explicit_path.strip():
            normalized = normalize_header_path(explicit_path)
            path_cache[entry_id] = normalized
            active.remove(entry_id)
            return normalized

        text_value = clean_header_text(str(entry.get("text", "")))
        parent_id = entry.get("parent_id")
        if isinstance(parent_id, str) and parent_id in id_map:
            parent_path = build_path(parent_id, active)
            full_path = f"{parent_path} > {text_value}" if parent_path else text_value
        else:
            full_path = text_value

        normalized = normalize_header_path(full_path)
        path_cache[entry_id] = normalized
        active.remove(entry_id)
        return normalized

    for entry_id in id_map:
        path = build_path(entry_id)
        if path:
            toc_paths.append(path)

    toc_paths = unique_preserve_order(toc_paths)
    toc_path_set = set(toc_paths)

    missing_paths = sorted(markdown_path_set - toc_path_set)
    extra_paths = sorted(toc_path_set - markdown_path_set)

    if missing_paths:
        checks.append(
            CheckResult(
                "toc_covers_markdown_headers",
                FAIL,
                f"{len(missing_paths)} markdown header paths missing from TOC",
            )
        )
    else:
        checks.append(
            CheckResult(
                "toc_covers_markdown_headers",
                PASS,
                "TOC covers all markdown header paths",
            )
        )

    if extra_paths:
        checks.append(
            CheckResult(
                "toc_extra_paths",
                WARN,
                f"{len(extra_paths)} TOC paths are not present in markdown headers",
            )
        )
    else:
        checks.append(CheckResult("toc_extra_paths", PASS, "No extra TOC paths"))

    return {
        "checks": checks,
        "toc_paths": toc_paths,
        "missing_paths": missing_paths,
        "extra_paths": extra_paths,
        "entry_count": len(entries),
    }


def validate_chunk_metadata(
    chunks: Sequence[Mapping[str, Any]],
    markdown_paths: Sequence[str],
) -> dict[str, Any]:
    """Validate chunk metadata shape and compatibility with markdown headers."""
    checks: list[CheckResult] = []
    markdown_path_set = set(markdown_paths)
    chunk_issue_map: dict[int, list[CheckResult]] = {}
    unmatched_paths: list[tuple[int, str]] = []
    legacy_key_hits = 0
    empty_path_chunks = 0
    invalid_metadata_count = 0
    total_paths = 0

    def add_chunk_issue(chunk_index: int, result: CheckResult) -> None:
        chunk_issue_map.setdefault(chunk_index, []).append(result)

    for chunk in chunks:
        chunk_index = int(chunk.get("chunk_index", -1))
        metadata = chunk.get("chunk_metadata")
        if not isinstance(metadata, dict):
            invalid_metadata_count += 1
            add_chunk_issue(
                chunk_index,
                CheckResult(
                    "chunk_metadata_dict",
                    FAIL,
                    "chunk_metadata is missing or not a dictionary",
                ),
            )
            continue

        all_header_paths = metadata.get("all_header_paths")
        header_level_map = metadata.get("header_level_map")

        if not isinstance(all_header_paths, list):
            invalid_metadata_count += 1
            add_chunk_issue(
                chunk_index,
                CheckResult(
                    "all_header_paths_type",
                    FAIL,
                    "all_header_paths missing or not a list",
                ),
            )
            all_header_paths = []

        if not isinstance(header_level_map, dict):
            invalid_metadata_count += 1
            add_chunk_issue(
                chunk_index,
                CheckResult(
                    "header_level_map_type",
                    FAIL,
                    "header_level_map missing or not a dict",
                ),
            )
            header_level_map = {}

        if isinstance(all_header_paths, list) and len(all_header_paths) == 0:
            empty_path_chunks += 1
            add_chunk_issue(
                chunk_index,
                CheckResult(
                    "all_header_paths_empty",
                    WARN,
                    "Chunk has empty all_header_paths (possible body-only chunk)",
                ),
            )

        for path in all_header_paths:
            if not isinstance(path, str) or not path.strip():
                invalid_metadata_count += 1
                add_chunk_issue(
                    chunk_index,
                    CheckResult(
                        "all_header_paths_values",
                        FAIL,
                        "all_header_paths contains non-string or empty path",
                    ),
                )
                continue

            normalized_path = normalize_header_path(path)
            segments = [segment.strip() for segment in normalized_path.split(" > ")]
            total_paths += 1
            for segment in segments:
                level = header_level_map.get(segment)
                if not isinstance(level, int) or not (1 <= level <= 6):
                    invalid_metadata_count += 1
                    add_chunk_issue(
                        chunk_index,
                        CheckResult(
                            "header_level_map_values",
                            FAIL,
                            f"Missing/invalid level for segment '{segment}'",
                        ),
                    )

            if markdown_path_set and not _path_matches_markdown(
                normalized_path, markdown_path_set
            ):
                unmatched_paths.append((chunk_index, normalized_path))
                add_chunk_issue(
                    chunk_index,
                    CheckResult(
                        "chunk_path_vs_markdown",
                        WARN,
                        f"Path '{normalized_path}' not matched in markdown headers",
                    ),
                )

        legacy_keys = []
        for key in metadata:
            if re.match(r"^Header [1-6]$", str(key)):
                legacy_keys.append(key)
            if key in {"all_headers", "section_path"}:
                legacy_keys.append(key)
        if legacy_keys:
            legacy_key_hits += len(set(legacy_keys))
            add_chunk_issue(
                chunk_index,
                CheckResult(
                    "legacy_metadata_keys",
                    WARN,
                    f"Legacy keys present: {sorted(set(legacy_keys))}",
                ),
            )

    if invalid_metadata_count:
        checks.append(
            CheckResult(
                "chunk_metadata_schema",
                FAIL,
                f"{invalid_metadata_count} chunk metadata schema issues found",
            )
        )
    else:
        checks.append(
            CheckResult(
                "chunk_metadata_schema",
                PASS,
                "Chunk metadata schema is valid",
            )
        )

    if empty_path_chunks:
        checks.append(
            CheckResult(
                "chunk_metadata_empty_paths",
                WARN,
                f"{empty_path_chunks} chunks have empty all_header_paths",
            )
        )
    else:
        checks.append(
            CheckResult(
                "chunk_metadata_empty_paths",
                PASS,
                "All chunks have non-empty all_header_paths",
            )
        )

    if unmatched_paths:
        unmatched_count = len(unmatched_paths)
        ratio = unmatched_count / max(total_paths, 1)
        status = FAIL if unmatched_count >= 3 else WARN
        checks.append(
            CheckResult(
                "chunk_paths_match_markdown",
                status,
                (
                    f"{unmatched_count}/{max(total_paths, 1)} chunk paths do not "
                    f"match markdown header paths ({ratio:.1%})"
                ),
            )
        )
    else:
        checks.append(
            CheckResult(
                "chunk_paths_match_markdown",
                PASS,
                "All chunk header paths match markdown paths/prefixes",
            )
        )

    if legacy_key_hits:
        checks.append(
            CheckResult(
                "chunk_legacy_metadata_keys",
                WARN,
                f"Found {legacy_key_hits} legacy metadata key occurrences",
            )
        )
    else:
        checks.append(
            CheckResult(
                "chunk_legacy_metadata_keys",
                PASS,
                "No legacy metadata keys found in chunk metadata",
            )
        )

    return {
        "checks": checks,
        "chunk_issue_map": chunk_issue_map,
        "unmatched_paths": unmatched_paths,
        "legacy_key_hits": legacy_key_hits,
    }


def select_chunk_samples(
    chunks: Sequence[Mapping[str, Any]],
    sample_size: int,
    seed: int,
    doc_id: int,
) -> list[Mapping[str, Any]]:
    """Select deterministic random chunk samples per document."""
    chunk_list = list(chunks)
    if sample_size <= 0:
        return []
    if len(chunk_list) <= sample_size:
        return chunk_list

    rng = random.Random(seed + (doc_id * 7919))
    sampled = rng.sample(chunk_list, sample_size)
    return sorted(sampled, key=lambda chunk: chunk.get("chunk_index", -1))


def determine_verdict(checks: Sequence[CheckResult]) -> str:
    """Aggregate check statuses into document verdict."""
    statuses = [check.status for check in checks]
    if FAIL in statuses:
        return FAIL
    if WARN in statuses:
        return WARN
    return PASS


def escape_markdown_cell(value: Any) -> str:
    """Escape markdown table cell content."""
    text_value = str(value if value is not None else "")
    text_value = text_value.replace("\n", " ")
    text_value = text_value.replace("|", r"\|")
    return text_value


def build_chunk_inspections(
    sampled_chunks: Sequence[Mapping[str, Any]],
    chunk_issue_map: Mapping[int, Sequence[CheckResult]],
) -> list[dict[str, Any]]:
    """Build per-chunk inspection payload for report rendering."""
    inspections: list[dict[str, Any]] = []
    for chunk in sampled_chunks:
        chunk_index = int(chunk.get("chunk_index", -1))
        chunk_text = chunk.get("chunk_text") or ""
        metadata = chunk.get("chunk_metadata") if isinstance(chunk.get("chunk_metadata"), dict) else {}
        all_paths = metadata.get("all_header_paths")
        if not isinstance(all_paths, list):
            all_paths = []

        issues = list(chunk_issue_map.get(chunk_index, []))
        verdict = determine_verdict(issues) if issues else PASS
        notes = "; ".join(issue.message for issue in issues[:3])
        preview = normalize_whitespace(chunk_text)[:300]

        inspections.append(
            {
                "chunk_index": chunk_index,
                "char_count": len(chunk_text),
                "word_count": len(chunk_text.split()),
                "header_paths": all_paths,
                "verdict": verdict,
                "notes": notes or "No metadata issues for this chunk sample",
                "preview": preview,
            }
        )
    return inspections


def fetch_documents_for_validation(
    session: Any,
    doc_ids: Sequence[int] | None,
) -> list[Mapping[str, Any]]:
    """Fetch documents eligible for validation."""
    base_select = """
        SELECT
            d.id,
            d.title,
            d.status::text AS status,
            d.markdown,
            d.doc_metadata,
            d.chunks
        FROM documents d
    """

    if doc_ids:
        stmt = text(
            base_select + " WHERE d.id IN :doc_ids ORDER BY d.id"
        ).bindparams(bindparam("doc_ids", expanding=True))
        rows = session.execute(stmt, {"doc_ids": list(doc_ids)}).mappings().all()
        return list(rows)

    stmt = text(
        base_select
        + """
        WHERE d.status::text = 'completed'
          AND d.markdown IS NOT NULL
          AND btrim(d.markdown) <> ''
          AND EXISTS (
              SELECT 1
              FROM chunks c
              WHERE c.document_id = d.id
          )
        ORDER BY d.id
        """
    )
    rows = session.execute(stmt).mappings().all()
    return list(rows)


def fetch_chunks_for_document(session: Any, doc_id: int) -> list[Mapping[str, Any]]:
    """Fetch chunks for one document in chunk_index order."""
    stmt = text(
        """
        SELECT
            c.id,
            c.uuid,
            c.chunk_index,
            c.chunk_text,
            c.chunk_metadata
        FROM chunks c
        WHERE c.document_id = :doc_id
        ORDER BY c.chunk_index, c.id
        """
    )
    rows = session.execute(stmt, {"doc_id": doc_id}).mappings().all()
    return list(rows)


def _get_embedding_columns(session: Any) -> set[str]:
    """Return available columns on langchain_pg_embedding."""
    stmt = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'langchain_pg_embedding'
        """
    )
    return {row[0] for row in session.execute(stmt).fetchall()}


def _resolve_embedding_lookup_column(session: Any, uuids: Sequence[str]) -> str | None:
    """
    Resolve which embedding column maps to chunk UUIDs.

    Prefers the candidate column with the highest overlap against provided UUIDs.
    """
    cache_key = "_embedding_lookup_column"
    if cache_key in session.info:
        return session.info[cache_key]

    columns = _get_embedding_columns(session)
    candidates = [c for c in ("id", "custom_id", "uuid") if c in columns]
    if not candidates:
        session.info[cache_key] = None
        return None

    if not uuids:
        session.info[cache_key] = candidates[0]
        return candidates[0]

    best_column: str | None = None
    best_match_count = -1

    for column in candidates:
        stmt = text(
            f"""
            SELECT COUNT(*) AS match_count
            FROM langchain_pg_embedding
            WHERE {column}::text IN :uuids
            """
        ).bindparams(bindparam("uuids", expanding=True))
        match_count = int(session.execute(stmt, {"uuids": list(uuids)}).scalar() or 0)
        if match_count > best_match_count:
            best_match_count = match_count
            best_column = column

    session.info[cache_key] = best_column
    return best_column


def fetch_existing_embedding_ids(session: Any, uuids: Sequence[str]) -> tuple[set[str], str]:
    """Return existing embedding IDs for provided UUIDs and lookup column used."""
    if not uuids:
        return set(), ""

    column = _resolve_embedding_lookup_column(session, uuids)
    if column is None:
        raise RuntimeError(
            "Cannot run embedding consistency check: "
            "langchain_pg_embedding has none of [id, uuid, custom_id] columns."
        )

    # Column name is selected from a fixed whitelist above.
    stmt = text(
        f"""
        SELECT {column}::text AS embedding_id
        FROM langchain_pg_embedding
        WHERE {column}::text IN :uuids
        """
    ).bindparams(bindparam("uuids", expanding=True))
    rows = session.execute(stmt, {"uuids": list(uuids)}).mappings().all()
    return {row["embedding_id"] for row in rows}, column


def audit_document(
    document: Mapping[str, Any],
    chunks: Sequence[Mapping[str, Any]],
    chunk_sample_per_doc: int,
    seed: int,
    check_embeddings: bool,
    session: Any,
) -> dict[str, Any]:
    """Run all validations for one document and return report payload."""
    checks: list[CheckResult] = []
    doc_id = int(document["id"])

    checks.extend(validate_chunk_index_integrity(chunks))

    reconstruction = evaluate_reconstruction(document.get("markdown") or "", chunks)
    checks.append(
        CheckResult(
            "reconstruction_similarity",
            reconstruction["status"],
            reconstruction["message"],
        )
    )

    markdown_headers = extract_markdown_headers(document.get("markdown") or "")
    markdown_paths = unique_preserve_order(
        header["path_from_root"] for header in markdown_headers if header["path_from_root"]
    )
    checks.append(
        CheckResult(
            "markdown_headers_extracted",
            PASS,
            f"Extracted {len(markdown_headers)} headers ({len(markdown_paths)} unique paths)",
        )
    )

    doc_metadata = document.get("doc_metadata")
    table_of_contents = None
    if isinstance(doc_metadata, dict):
        table_of_contents = doc_metadata.get("table_of_contents")

    toc_validation = validate_toc_entries(table_of_contents, markdown_paths)
    checks.extend(toc_validation["checks"])

    chunk_metadata_validation = validate_chunk_metadata(chunks, markdown_paths)
    checks.extend(chunk_metadata_validation["checks"])

    temp_chunks = document.get("chunks")
    if temp_chunks is None:
        checks.append(
            CheckResult(
                "document_temp_chunks_cleared",
                PASS,
                "documents.chunks is NULL for this document",
            )
        )
    else:
        checks.append(
            CheckResult(
                "document_temp_chunks_cleared",
                WARN,
                "documents.chunks is not NULL on a completed document",
            )
        )

    if check_embeddings:
        uuids = [chunk.get("uuid") for chunk in chunks if isinstance(chunk.get("uuid"), str)]
        try:
            existing_ids, embedding_column = fetch_existing_embedding_ids(session, uuids)
            missing_ids = sorted(set(uuids) - existing_ids)
            if missing_ids:
                checks.append(
                    CheckResult(
                        "embedding_ids_exist",
                        FAIL,
                        (
                            f"{len(missing_ids)} chunk UUIDs missing in "
                            f"langchain_pg_embedding.{embedding_column}"
                        ),
                    )
                )
            else:
                checks.append(
                    CheckResult(
                        "embedding_ids_exist",
                        PASS,
                        (
                            f"All {len(uuids)} chunk UUIDs found in "
                            f"langchain_pg_embedding.{embedding_column}"
                        ),
                    )
                )
        except Exception as exc:
            checks.append(
                CheckResult(
                    "embedding_ids_exist",
                    WARN,
                    f"Embedding consistency check skipped: {exc}",
                )
            )

    sampled_chunks = select_chunk_samples(
        chunks=chunks,
        sample_size=chunk_sample_per_doc,
        seed=seed,
        doc_id=doc_id,
    )
    chunk_inspections = build_chunk_inspections(
        sampled_chunks,
        chunk_metadata_validation["chunk_issue_map"],
    )

    chunk_char_lengths = [len(chunk.get("chunk_text") or "") for chunk in chunks]
    chunk_word_lengths = [len((chunk.get("chunk_text") or "").split()) for chunk in chunks]
    chunk_stats = {
        "count": len(chunks),
        "char_min": min(chunk_char_lengths) if chunk_char_lengths else 0,
        "char_max": max(chunk_char_lengths) if chunk_char_lengths else 0,
        "char_avg": statistics.mean(chunk_char_lengths) if chunk_char_lengths else 0.0,
        "word_min": min(chunk_word_lengths) if chunk_word_lengths else 0,
        "word_max": max(chunk_word_lengths) if chunk_word_lengths else 0,
        "word_avg": statistics.mean(chunk_word_lengths) if chunk_word_lengths else 0.0,
    }

    verdict = determine_verdict(checks)
    return {
        "doc_id": doc_id,
        "title": document.get("title") or "Untitled",
        "status": document.get("status") or "unknown",
        "verdict": verdict,
        "checks": checks,
        "chunk_stats": chunk_stats,
        "reconstruction": reconstruction,
        "markdown_header_count": len(markdown_headers),
        "markdown_paths": markdown_paths,
        "toc_entry_count": toc_validation["entry_count"],
        "toc_paths": toc_validation["toc_paths"],
        "missing_toc_paths": toc_validation["missing_paths"],
        "extra_toc_paths": toc_validation["extra_paths"],
        "unmatched_chunk_paths": chunk_metadata_validation["unmatched_paths"],
        "chunk_inspections": chunk_inspections,
    }


def summarize_document_checks(checks: Sequence[CheckResult]) -> dict[str, int]:
    """Count PASS/WARN/FAIL checks."""
    return {
        PASS: sum(1 for check in checks if check.status == PASS),
        WARN: sum(1 for check in checks if check.status == WARN),
        FAIL: sum(1 for check in checks if check.status == FAIL),
    }


def summarize_run(documents: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Build global run summary for CLI and UI consumers."""
    global_checks = [check for doc in documents for check in doc["checks"]]
    global_check_counts = summarize_document_checks(global_checks)
    doc_verdict_counts = {
        PASS: sum(1 for doc in documents if doc["verdict"] == PASS),
        WARN: sum(1 for doc in documents if doc["verdict"] == WARN),
        FAIL: sum(1 for doc in documents if doc["verdict"] == FAIL),
    }
    has_fail = doc_verdict_counts[FAIL] > 0
    return {
        "documents_analyzed": len(documents),
        "global_check_count": len(global_checks),
        "global_check_counts": global_check_counts,
        "doc_verdict_counts": doc_verdict_counts,
        "has_fail": has_fail,
    }


def render_markdown_report(
    documents: Sequence[dict[str, Any]],
    sampled_doc_ids: Sequence[int],
    seed: int,
    sample_size: int,
    chunk_sample_per_doc: int,
    check_embeddings: bool,
) -> str:
    """Render markdown validation report."""
    generated_at = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M:%S %Z")
    global_checks = [check for doc in documents for check in doc["checks"]]
    global_counts = summarize_document_checks(global_checks)

    verdict_counts = {
        PASS: sum(1 for doc in documents if doc["verdict"] == PASS),
        WARN: sum(1 for doc in documents if doc["verdict"] == WARN),
        FAIL: sum(1 for doc in documents if doc["verdict"] == FAIL),
    }

    lines: list[str] = []
    lines.append("# Chunk + TOC Integrity Audit Report")
    lines.append("")
    lines.append(f"- Generated: {generated_at}")
    lines.append(f"- Sample size requested: {sample_size}")
    lines.append(f"- Chunk samples per document: {chunk_sample_per_doc}")
    lines.append(f"- Embedding consistency check: {'enabled' if check_embeddings else 'disabled'}")
    lines.append(f"- Seed: {seed}")
    lines.append("")

    lines.append("## Global Summary")
    lines.append("")
    lines.append(f"- Documents analyzed: {len(documents)}")
    lines.append(f"- Document verdicts: PASS={verdict_counts[PASS]}, WARN={verdict_counts[WARN]}, FAIL={verdict_counts[FAIL]}")
    lines.append(f"- Total checks: {len(global_checks)}")
    lines.append(f"- Check outcomes: PASS={global_counts[PASS]}, WARN={global_counts[WARN]}, FAIL={global_counts[FAIL]}")
    lines.append("")

    for doc in documents:
        check_counts = summarize_document_checks(doc["checks"])
        chunk_stats = doc["chunk_stats"]

        lines.append(f"## Document [{doc['doc_id']}] {doc['title']}")
        lines.append("")
        lines.append(f"- Status: `{doc['status']}`")
        lines.append(f"- Final verdict: **{doc['verdict']}**")
        lines.append(
            "- Chunk stats: "
            f"count={chunk_stats['count']}, "
            f"chars(min/avg/max)={chunk_stats['char_min']}/{chunk_stats['char_avg']:.1f}/{chunk_stats['char_max']}, "
            f"words(min/avg/max)={chunk_stats['word_min']}/{chunk_stats['word_avg']:.1f}/{chunk_stats['word_max']}"
        )
        lines.append(
            "- Reconstruction: "
            f"similarity={doc['reconstruction']['similarity']:.6f} "
            f"({doc['reconstruction']['status']})"
        )
        lines.append(
            "- Headers: "
            f"markdown_paths={len(doc['markdown_paths'])}, "
            f"toc_paths={len(doc['toc_paths'])}, "
            f"toc_entries={doc['toc_entry_count']}"
        )
        lines.append(
            "- Check outcomes: "
            f"PASS={check_counts[PASS]}, WARN={check_counts[WARN]}, FAIL={check_counts[FAIL]}"
        )
        lines.append("")

        lines.append("### Missing Markdown Headers In TOC")
        lines.append("")
        if doc["missing_toc_paths"]:
            for path in doc["missing_toc_paths"]:
                lines.append(f"- `{path}`")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Extra TOC Paths Not In Markdown")
        lines.append("")
        if doc["extra_toc_paths"]:
            for path in doc["extra_toc_paths"]:
                lines.append(f"- `{path}`")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Chunk Paths Unmatched To Markdown")
        lines.append("")
        if doc["unmatched_chunk_paths"]:
            for chunk_index, path in doc["unmatched_chunk_paths"][:20]:
                lines.append(f"- chunk `{chunk_index}`: `{path}`")
            if len(doc["unmatched_chunk_paths"]) > 20:
                lines.append(
                    f"- ... plus {len(doc['unmatched_chunk_paths']) - 20} more"
                )
        else:
            lines.append("- None")
        lines.append("")

        lines.append("### Check Results")
        lines.append("")
        lines.append("| Check | Status | Message |")
        lines.append("|---|---|---|")
        for check in doc["checks"]:
            lines.append(
                f"| {escape_markdown_cell(check.name)} "
                f"| {escape_markdown_cell(check.status)} "
                f"| {escape_markdown_cell(check.message)} |"
            )
        lines.append("")

        lines.append("### Random Chunk Inspection")
        lines.append("")
        lines.append("| Chunk Index | Verdict | Chars | Words | Header Paths | Preview | Notes |")
        lines.append("|---:|---|---:|---:|---|---|---|")
        for chunk in doc["chunk_inspections"]:
            header_paths = ", ".join(chunk["header_paths"]) if chunk["header_paths"] else "(none)"
            lines.append(
                f"| {escape_markdown_cell(chunk['chunk_index'])} "
                f"| {escape_markdown_cell(chunk['verdict'])} "
                f"| {escape_markdown_cell(chunk['char_count'])} "
                f"| {escape_markdown_cell(chunk['word_count'])} "
                f"| {escape_markdown_cell(header_paths)} "
                f"| {escape_markdown_cell(chunk['preview'])} "
                f"| {escape_markdown_cell(chunk['notes'])} |"
            )
        lines.append("")

    lines.append("## Appendix")
    lines.append("")
    lines.append(f"- Seed: `{seed}`")
    lines.append(
        f"- Sampled document IDs: `{', '.join(str(doc_id) for doc_id in sampled_doc_ids)}`"
    )
    lines.append("")
    lines.append("### Validation Rules")
    lines.append("")
    lines.append("- Reconstruction similarity: PASS `>= 0.995`, WARN `0.98-0.995`, FAIL `< 0.98`.")
    lines.append("- Unmatched chunk paths: FAIL if count `>= 3`; otherwise WARN.")
    lines.append("- TOC missing markdown paths: FAIL.")
    lines.append("- Extra TOC paths not in markdown: WARN.")

    return "\n".join(lines) + "\n"


def execute_validation(
    *,
    doc_ids: Sequence[int] | None,
    sample_size: int,
    seed: int,
    chunk_sample_per_doc: int,
    check_embeddings: bool,
) -> dict[str, Any]:
    """
    Execute validation and return structured payload for CLI/UI.

    Returns:
        {
            "documents": [...],
            "sampled_doc_ids": [...],
            "summary": {...},
            "config": {...}
        }
    """
    from db.database import session_scope

    with session_scope() as session:
        documents = fetch_documents_for_validation(session, doc_ids)

        if not documents:
            raise RuntimeError("No documents found for validation with current filters")

        if doc_ids:
            requested_ids = sorted(set(doc_ids))
            found_ids = sorted(int(doc["id"]) for doc in documents)
            missing_ids = sorted(set(requested_ids) - set(found_ids))
            if missing_ids:
                raise RuntimeError(f"Requested document IDs not found: {missing_ids}")
            selected_docs = documents
        else:
            selected_docs = sample_documents(documents, sample_size, seed)

        report_docs: list[dict[str, Any]] = []
        sampled_doc_ids = [int(doc["id"]) for doc in selected_docs]

        for document in selected_docs:
            doc_id = int(document["id"])
            chunks = fetch_chunks_for_document(session, doc_id)
            if not chunks:
                # Keep document in report with a hard failure check.
                report_docs.append(
                    {
                        "doc_id": doc_id,
                        "title": document.get("title") or "Untitled",
                        "status": document.get("status") or "unknown",
                        "verdict": FAIL,
                        "checks": [CheckResult("chunks_exist", FAIL, "No chunks found for document")],
                        "chunk_stats": {
                            "count": 0,
                            "char_min": 0,
                            "char_max": 0,
                            "char_avg": 0.0,
                            "word_min": 0,
                            "word_max": 0,
                            "word_avg": 0.0,
                        },
                        "reconstruction": {
                            "similarity": 0.0,
                            "status": FAIL,
                            "message": "No chunks available for reconstruction",
                        },
                        "markdown_header_count": 0,
                        "markdown_paths": [],
                        "toc_entry_count": 0,
                        "toc_paths": [],
                        "missing_toc_paths": [],
                        "extra_toc_paths": [],
                        "unmatched_chunk_paths": [],
                        "chunk_inspections": [],
                    }
                )
                continue

            doc_report = audit_document(
                document=document,
                chunks=chunks,
                chunk_sample_per_doc=chunk_sample_per_doc,
                seed=seed,
                check_embeddings=check_embeddings,
                session=session,
            )
            report_docs.append(doc_report)

    return {
        "documents": report_docs,
        "sampled_doc_ids": sampled_doc_ids,
        "summary": summarize_run(report_docs),
        "config": {
            "seed": seed,
            "sample_size": sample_size,
            "chunk_sample_per_doc": chunk_sample_per_doc,
            "check_embeddings": check_embeddings,
            "doc_ids": list(doc_ids) if doc_ids else None,
            "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        },
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI args."""
    parser = argparse.ArgumentParser(
        description="Validate chunk integrity and TOC consistency for sampled documents.",
    )
    parser.add_argument(
        "--doc-ids",
        nargs="+",
        type=int,
        help="Explicit document IDs to validate (overrides random sampling)",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Number of random documents to validate (default: 5)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic sampling (default: 42)",
    )
    parser.add_argument(
        "--chunk-sample-per-doc",
        type=int,
        default=3,
        help="Random chunks per document to inspect in detail (default: 3)",
    )
    parser.add_argument(
        "--check-embeddings",
        action="store_true",
        help="Check each chunk UUID exists in langchain_pg_embedding table",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="reports/chunk_toc_validation.md",
        help="Output markdown report path",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> tuple[int, str]:
    """Execute audit and return (exit_code, report_path)."""
    result = execute_validation(
        doc_ids=args.doc_ids,
        sample_size=args.sample_size,
        seed=args.seed,
        chunk_sample_per_doc=args.chunk_sample_per_doc,
        check_embeddings=args.check_embeddings,
    )

    markdown_report = render_markdown_report(
        documents=result["documents"],
        sampled_doc_ids=result["sampled_doc_ids"],
        seed=args.seed,
        sample_size=args.sample_size,
        chunk_sample_per_doc=args.chunk_sample_per_doc,
        check_embeddings=args.check_embeddings,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown_report, encoding="utf-8")

    return (1 if result["summary"]["has_fail"] else 0), str(output_path)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    try:
        exit_code, report_path = run(args)
        print(f"Validation report written to: {report_path}")
        print(f"Exit code: {exit_code} ({'FAIL findings present' if exit_code == 1 else 'no FAIL findings'})")
        return exit_code
    except Exception as exc:
        print(f"Validation failed due to runtime/query error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
