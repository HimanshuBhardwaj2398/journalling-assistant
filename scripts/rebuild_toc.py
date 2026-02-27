#!/usr/bin/env python3
"""
Rebuild TOC, chunk header metadata, and missing markdown for already-ingested documents.

Re-extracts headers from stored markdown and chunk text to fix:
- Document-level table_of_contents in doc_metadata
- Chunk-level all_header_paths and header_level_map in chunk_metadata

Can also backfill missing markdown content from chunk text or by re-parsing
the original source.

Does NOT modify chunk text or vector embeddings.

Usage:
    python scripts/rebuild_toc.py --all
    python scripts/rebuild_toc.py --ids 16 17 18
    python scripts/rebuild_toc.py --ids 16 --dry-run

    # Rebuild missing markdown from chunks
    python scripts/rebuild_toc.py --rebuild-markdown --all
    python scripts/rebuild_toc.py --rebuild-markdown --ids 16 17 --dry-run

    # Re-parse from original source (URL/PDF) instead of chunks
    python scripts/rebuild_toc.py --rebuild-markdown --reparse --ids 16
"""

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from db.crud import ChunkCRUD, DocumentCRUD
from db.database import session_scope
from db.schema import DocumentStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================================
# HEADER EXTRACTION
# ============================================================================


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
        for level_index in range(1, 7):
            if current_headers[level_index]:
                parts.append(current_headers[level_index])
                level_map[current_headers[level_index]] = level_index

        path = " > ".join(parts)
        if path and path not in paths:
            paths.append(path)

    return paths, level_map


def build_toc_from_markdown(markdown: str) -> dict:
    """
    Build table of contents directly from raw markdown.

    Parses every header line and builds a hierarchical TOC with
    parent-child relationships. 100% header coverage — no dependency
    on chunk metadata.

    Returns:
        Dict with 'entries' (structured list) and 'text' (indented string)
    """
    entries = []
    header_stack = []  # [(level, text, id), ...]
    seen_headers = set()
    entry_count = 0

    for line in markdown.split("\n"):
        match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if not match:
            continue

        level = len(match.group(1))
        text = match.group(2).strip()

        # Deduplicate by (level, text)
        header_key = (level, text)
        if header_key in seen_headers:
            continue
        seen_headers.add(header_key)

        # Pop stack until we find parent level
        while header_stack and header_stack[-1][0] >= level:
            header_stack.pop()

        entry_id = f"h{level}_{entry_count}"
        parent_id = header_stack[-1][2] if header_stack else None

        entries.append(
            {
                "id": entry_id,
                "level": level,
                "text": text,
                "parent_id": parent_id,
            }
        )

        header_stack.append((level, text, entry_id))
        entry_count += 1

    text_lines = []
    for entry in entries:
        indent = "  " * (entry["level"] - 1)
        text_lines.append(f"{indent}{entry['text']}")

    return {
        "entries": entries,
        "text": "\n".join(text_lines),
    }


# ============================================================================
# MARKDOWN REBUILD
# ============================================================================


def rebuild_markdown_from_chunks(
    doc_id: int,
    session,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Reconstruct markdown for a document by joining its chunk texts in order.

    Args:
        doc_id: Document ID
        session: Database session
        dry_run: If True, don't write changes
        force: If True, overwrite existing markdown

    Returns:
        Summary dict with status
    """
    doc_crud = DocumentCRUD(session)
    chunk_crud = ChunkCRUD(session)

    doc = doc_crud.get_document_by_id(doc_id)
    if not doc:
        return {"doc_id": doc_id, "error": "Document not found"}

    if doc.markdown and not force:
        return {
            "doc_id": doc_id,
            "title": doc.title,
            "skipped": True,
            "reason": "Markdown already exists (use --force to overwrite)",
            "markdown_len": len(doc.markdown),
        }

    chunks = chunk_crud.get_chunks_by_document(doc_id)
    if not chunks:
        return {"doc_id": doc_id, "title": doc.title, "error": "No chunks found"}

    # Join chunks with double newline to preserve paragraph boundaries
    reconstructed = "\n\n".join(chunk.chunk_text for chunk in chunks)

    if not dry_run:
        doc_crud.update_markdown(doc_id, reconstructed)

    return {
        "doc_id": doc_id,
        "title": doc.title,
        "method": "chunks",
        "chunk_count": len(chunks),
        "markdown_len": len(reconstructed),
        "dry_run": dry_run,
    }


def rebuild_markdown_from_source(
    doc_id: int,
    session,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """
    Re-parse the original source (URL or PDF) to regenerate markdown.

    Args:
        doc_id: Document ID
        session: Database session
        dry_run: If True, don't write changes
        force: If True, overwrite existing markdown

    Returns:
        Summary dict with status
    """
    from core.exceptions import ParsingError
    from ingestion.parsing import ParserFactory

    doc_crud = DocumentCRUD(session)

    doc = doc_crud.get_document_by_id(doc_id)
    if not doc:
        return {"doc_id": doc_id, "error": "Document not found"}

    if doc.markdown and not force:
        return {
            "doc_id": doc_id,
            "title": doc.title,
            "skipped": True,
            "reason": "Markdown already exists (use --force to overwrite)",
            "markdown_len": len(doc.markdown),
        }

    if not doc.file_path:
        return {"doc_id": doc_id, "title": doc.title, "error": "No file_path to re-parse"}

    try:
        factory = ParserFactory()
        result = factory.parse(doc.file_path)
    except (ParsingError, Exception) as e:
        return {"doc_id": doc_id, "title": doc.title, "error": f"Re-parse failed: {e}"}

    if not dry_run:
        doc_crud.update_markdown(doc_id, result.content)

    return {
        "doc_id": doc_id,
        "title": doc.title,
        "method": "reparse",
        "source": doc.file_path,
        "markdown_len": len(result.content),
        "dry_run": dry_run,
    }


def print_markdown_result(result: dict):
    """Print result for one markdown rebuild."""
    if "error" in result:
        print(f"  SKIP [{result['doc_id']}] {result.get('title', '???')}: {result['error']}")
        return

    if result.get("skipped"):
        print(
            f"  SKIP [{result['doc_id']}] {result['title']}: "
            f"{result['reason']} ({result['markdown_len']} chars)"
        )
        return

    mode = " (DRY RUN)" if result["dry_run"] else ""
    method = result["method"]
    print(f"  [{result['doc_id']}] {result['title']}{mode}")
    if method == "chunks":
        print(f"       Method: reconstructed from {result['chunk_count']} chunks")
    else:
        print(f"       Method: re-parsed from {result['source']}")
    print(f"       Markdown length: {result['markdown_len']} chars")


# ============================================================================
# REBUILD LOGIC
# ============================================================================


def rebuild_document(
    doc_id: int,
    session,
    dry_run: bool = False,
) -> dict:
    """
    Rebuild TOC and chunk metadata for a single document.

    Args:
        doc_id: Document ID
        session: Database session
        dry_run: If True, don't write changes

    Returns:
        Summary dict with before/after stats
    """
    doc_crud = DocumentCRUD(session)
    chunk_crud = ChunkCRUD(session)

    doc = doc_crud.get_document_by_id(doc_id)
    if not doc:
        return {"doc_id": doc_id, "error": "Document not found"}

    if not doc.markdown:
        return {"doc_id": doc_id, "error": "No markdown content", "title": doc.title}

    # --- Before stats ---
    old_toc = (doc.doc_metadata or {}).get("table_of_contents", {})
    old_toc_count = len(old_toc.get("entries", []))

    chunks = chunk_crud.get_chunks_by_document(doc_id)

    # Count unique headers currently in chunk metadata
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

    # --- Step A: Rebuild TOC from raw markdown ---
    new_toc = build_toc_from_markdown(doc.markdown)
    new_toc_count = len(new_toc["entries"])

    # --- Step B: Rebuild header paths on chunks ---
    chunks_updated = 0
    new_chunk_headers = set()

    # Maintain running header context across ordered chunks
    running_headers = [None] * 7  # levels 0-6

    for chunk in chunks:
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
                for level_index in range(1, 7):
                    if running_headers[level_index]:
                        parts.append(running_headers[level_index])
                        chunk_level_map[running_headers[level_index]] = level_index

                path = " > ".join(parts)
                if path and path not in chunk_paths:
                    chunk_paths.append(path)

                new_chunk_headers.add((level, header))
        else:
            # No headers in chunk — use running context
            parts = []
            for level_index in range(1, 7):
                if running_headers[level_index]:
                    parts.append(running_headers[level_index])
                    chunk_level_map[running_headers[level_index]] = level_index
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
        keys_to_remove.extend(
            [
                "all_headers",
                "primary_header",
                "header_level",
                "section_path",
                "original_doc_id",
                "original_doc_title",
                "chunk_index",
            ]
        )
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

    # --- Write TOC to document ---
    if not dry_run:
        doc_crud.update_doc_metadata(
            document_id=doc_id,
            metadata_updates={"table_of_contents": new_toc},
            merge=True,
        )

    # --- Raw markdown header count for reference ---
    raw_headers = set()
    for match in re.finditer(r"^(#{1,6})\s+(.+)$", doc.markdown, re.MULTILINE):
        raw_headers.add((len(match.group(1)), match.group(2).strip()))

    return {
        "doc_id": doc_id,
        "title": doc.title,
        "raw_header_count": len(raw_headers),
        "old_toc_count": old_toc_count,
        "new_toc_count": new_toc_count,
        "old_chunk_header_count": len(old_chunk_headers),
        "new_chunk_header_count": len(new_chunk_headers),
        "total_chunks": len(chunks),
        "chunks_updated": chunks_updated,
        "dry_run": dry_run,
    }


# ============================================================================
# CLI
# ============================================================================


def print_result(result: dict):
    """Print result for one document."""
    if "error" in result:
        print(f"  SKIP [{result['doc_id']}] {result.get('title', '???')}: {result['error']}")
        return

    mode = " (DRY RUN)" if result["dry_run"] else ""
    toc_change = f"{result['old_toc_count']} -> {result['new_toc_count']}"
    chunk_h_change = f"{result['old_chunk_header_count']} -> {result['new_chunk_header_count']}"

    recovered = result["new_toc_count"] - result["old_toc_count"]
    marker = f"+{recovered}" if recovered > 0 else str(recovered)

    print(f"  [{result['doc_id']}] {result['title']}{mode}")
    print(f"       Raw headers: {result['raw_header_count']}")
    print(f"       TOC entries: {toc_change} ({marker})")
    print(f"       Chunk headers: {chunk_h_change}")
    print(f"       Chunks updated: {result['chunks_updated']}/{result['total_chunks']}")


def main():
    parser = argparse.ArgumentParser(
        description="Rebuild TOC and chunk metadata for ingested documents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--all",
        action="store_true",
        help="Process all completed documents",
    )
    group.add_argument(
        "--ids",
        nargs="+",
        type=int,
        help="Specific document IDs to process",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database",
    )

    parser.add_argument(
        "--rebuild-markdown",
        action="store_true",
        help="Backfill missing markdown on documents (from chunks by default)",
    )

    parser.add_argument(
        "--reparse",
        action="store_true",
        help="With --rebuild-markdown: re-parse from original source instead of chunks",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="With --rebuild-markdown: overwrite existing markdown too",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.reparse and not args.rebuild_markdown:
        parser.error("--reparse requires --rebuild-markdown")
    if args.force and not args.rebuild_markdown:
        parser.error("--force requires --rebuild-markdown")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Collect document IDs
    with session_scope() as session:
        doc_crud = DocumentCRUD(session)

        if args.all:
            docs = doc_crud.get_documents_by_status(DocumentStatus.COMPLETED)
            doc_ids = [d.id for d in docs]
        else:
            doc_ids = args.ids

        if not doc_ids:
            print("No documents to process.")
            return

        # ---- MARKDOWN REBUILD MODE ----
        if args.rebuild_markdown:
            method = "reparse" if args.reparse else "chunks"
            mode_label = "DRY RUN" if args.dry_run else "REBUILD"
            print(f"\n{'=' * 70}")
            print(f"MARKDOWN {mode_label} (method: {method})")
            print(f"{'=' * 70}")
            print(f"Documents to process: {len(doc_ids)}\n")

            rebuild_fn = (
                rebuild_markdown_from_source if args.reparse else rebuild_markdown_from_chunks
            )
            results = []
            for doc_id in doc_ids:
                result = rebuild_fn(doc_id, session, dry_run=args.dry_run, force=args.force)
                results.append(result)
                print_markdown_result(result)
                print()

            rebuilt = [r for r in results if "error" not in r and not r.get("skipped")]
            skipped = [r for r in results if r.get("skipped")]
            errored = [r for r in results if "error" in r]

            print(f"{'=' * 70}")
            print("SUMMARY")
            print(f"{'=' * 70}")
            print(f"  Rebuilt:  {len(rebuilt)}")
            print(f"  Skipped:  {len(skipped)}")
            print(f"  Errors:   {len(errored)}")
            if args.dry_run:
                print("\n  This was a dry run. Re-run without --dry-run to apply changes.")
            print()
            return

        # ---- TOC REBUILD MODE (default) ----
        mode_label = "DRY RUN" if args.dry_run else "REBUILD"
        print(f"\n{'=' * 70}")
        print(f"TOC & CHUNK METADATA {mode_label}")
        print(f"{'=' * 70}")
        print(f"Documents to process: {len(doc_ids)}\n")

        results = []
        for doc_id in doc_ids:
            result = rebuild_document(doc_id, session, dry_run=args.dry_run)
            results.append(result)
            print_result(result)
            print()

        # Summary
        processed = [r for r in results if "error" not in r]
        skipped = [r for r in results if "error" in r]
        total_recovered = sum(r["new_toc_count"] - r["old_toc_count"] for r in processed)

        print(f"{'=' * 70}")
        print("SUMMARY")
        print(f"{'=' * 70}")
        print(f"  Processed: {len(processed)}")
        print(f"  Skipped:   {len(skipped)}")
        print(f"  TOC entries recovered: {total_recovered}")
        if args.dry_run:
            print("\n  This was a dry run. Re-run without --dry-run to apply changes.")
        print()


if __name__ == "__main__":
    main()
