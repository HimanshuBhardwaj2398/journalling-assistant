#!/usr/bin/env python3
"""
Document Ingestion CLI Tool

Ingest meditation texts (URLs or PDFs) into the database.
Can be used for testing or production ingestion.

Usage:
    python scripts/ingest.py <source> [--title "Custom Title"]
    python scripts/ingest.py https://example.com/article
    python scripts/ingest.py path/to/document.pdf --title "Dhammapada"
    python scripts/ingest.py --resume 123  # Resume failed document
    python scripts/ingest.py --reprocess 123 --reprocess-mode from_chunking

Examples:
    # Ingest a Wikipedia article
    python scripts/ingest.py "https://en.wikipedia.org/wiki/Mindfulness"

    # Ingest a PDF with custom title
    python scripts/ingest.py "Books/sutta.pdf" --title "Sutta Collection"

    # Resume a failed ingestion
    python scripts/ingest.py --resume 5

    # Reprocess existing document from stored markdown
    python scripts/ingest.py --reprocess 5 --reprocess-mode from_chunking

    # Reprocess existing document from parsing and clear old markdown first
    python scripts/ingest.py --reprocess 5 --reprocess-mode full --clear-markdown

    # Batch ingest multiple sources
    python scripts/ingest.py url1 url2 path/to/file.pdf
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from config.logging_config import setup_logging
from db.crud import DocumentCRUD
from db.database import session_scope
from ingestion.embed import VectorStoreConfig
from ingestion.orchestrator import IngestionOrchestrator, ReprocessMode

setup_logging()
logger = logging.getLogger(__name__)


def print_header():
    """Print CLI header."""
    print("\n" + "=" * 70)
    print("MEDITATION DATABASE - DOCUMENT INGESTION")
    print("=" * 70 + "\n")


def print_document_info(doc_id: int, source: str, title: str):
    """Print document information."""
    print(f"Document ID: {doc_id}")
    print(f"Source: {source}")
    print(f"Title: {title}")
    print("-" * 70)


def print_stage_progress(stage_name: str, status: str):
    """Print stage progress."""
    icons = {"completed": "✓", "failed": "✗", "running": "⟳", "skipped": "⊘"}
    icon = icons.get(status, "•")
    print(f"{icon} {stage_name.replace('_', ' ').title()}: {status}")


def print_results(result: dict, verbose: bool = True):
    """Print ingestion results."""
    print("\n" + "=" * 70)
    print("INGESTION RESULTS")
    print("=" * 70)

    # Basic info
    print(f"\nDocument ID: {result['document_id']}")
    print(f"Title: {result['title']}")
    print(f"Chunks: {result['chunk_count']}")
    print(f"Status: {'✓ SUCCESS' if result['success'] else '✗ FAILED'}")

    # Stage results
    if verbose:
        print("\nPipeline Stages:")
        for stage_name, status in result["stage_results"].items():
            print_stage_progress(stage_name, status)

    # Errors
    if result["errors"]:
        print("\n⚠️  Errors:")
        for stage, error in result["errors"].items():
            print(f"  - {stage}: {error}")

    print("=" * 70 + "\n")


async def ingest_document(
    orchestrator: IngestionOrchestrator,
    source: str,
    title: Optional[str] = None,
    verbose: bool = True,
    reprocess_mode: Optional[str] = None,
    clear_markdown: bool = False,
) -> dict:
    """
    Ingest a single document.

    Args:
        orchestrator: Ingestion orchestrator instance
        source: URL, file path, or document ID to resume
        title: Optional custom title
        verbose: Print detailed progress
        reprocess_mode: Optional mode for reprocessing existing docs
        clear_markdown: Clear stored markdown before reprocessing (full mode only)

    Returns:
        Result dictionary with ingestion details
    """
    if verbose:
        print_header()

    # Check if source is a document ID (for resume)
    try:
        doc_id = int(source)
        if verbose:
            print(f"Resuming document ID: {doc_id}\n")
        result = await orchestrator.process(
            source=doc_id,
            title=title,
            reprocess_mode=reprocess_mode,
            clear_markdown=clear_markdown,
        )
    except ValueError:
        # It's a file path or URL
        if reprocess_mode:
            raise ValueError("reprocess_mode can only be used with an existing document ID")

        if verbose:
            # Extract title from filename if not provided
            if not title:
                if source.startswith(("http://", "https://")):
                    title = f"Web: {source[:50]}..."
                else:
                    title = Path(source).stem

            print_document_info(0, source, title)
            print("\nStarting ingestion pipeline...\n")

        result = await orchestrator.process(source=source, title=title)

    if verbose:
        print_results(result, verbose=True)

    return result


async def ingest_batch(
    sources: List[str],
    titles: Optional[List[str]] = None,
    verbose: bool = True,
    collection_name: str = "meditation_chunks",
    reprocess_mode: Optional[str] = None,
    clear_markdown: bool = False,
) -> List[dict]:
    """
    Ingest multiple documents.

    Args:
        sources: List of URLs, file paths, or document IDs
        titles: Optional list of custom titles (must match sources length)
        verbose: Print detailed progress
        collection_name: Name of the collection to store embeddings in
        reprocess_mode: Optional mode for reprocessing existing docs
        clear_markdown: Clear stored markdown before reprocessing (full mode only)

    Returns:
        List of result dictionaries
    """
    db_url = os.getenv("DB_URL") or os.getenv("DATABASE_URL")

    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(
            collection_name=collection_name,
            db_url=db_url,
        )
    )

    results = []
    titles = titles or [None] * len(sources)

    for i, (source, title) in enumerate(zip(sources, titles)):
        if len(sources) > 1:
            print(f"\n📄 Processing document {i + 1}/{len(sources)}")

        try:
            result = await ingest_document(
                orchestrator,
                source,
                title,
                verbose,
                reprocess_mode=reprocess_mode,
                clear_markdown=clear_markdown,
            )
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to process {source}: {e}")
            results.append({"source": source, "success": False, "error": str(e)})

    return results


def print_batch_summary(results: List[dict]):
    """Print summary of batch ingestion."""
    print("\n" + "=" * 70)
    print("BATCH INGESTION SUMMARY")
    print("=" * 70)

    total = len(results)
    successful = sum(1 for r in results if r.get("success", False))
    failed = total - successful

    print(f"\nTotal documents: {total}")
    print(f"✓ Successful: {successful}")
    print(f"✗ Failed: {failed}")

    if failed > 0:
        print("\nFailed documents:")
        for r in results:
            if not r.get("success", False):
                source = r.get("source", "Unknown")
                error = r.get("error", r.get("errors", "Unknown error"))
                print(f"  - {source}: {error}")

    # Show chunk statistics
    total_chunks = sum(r.get("chunk_count", 0) for r in results)
    print(f"\nTotal chunks created: {total_chunks}")

    print("=" * 70 + "\n")


def list_documents():
    """List all documents in the database."""
    print("\n" + "=" * 70)
    print("DOCUMENTS IN DATABASE")
    print("=" * 70 + "\n")

    with session_scope() as session:
        crud = DocumentCRUD(session)
        docs = crud.get_all_documents()

        if not docs:
            print("No documents found.\n")
            return

        print(f"Total documents: {len(docs)}\n")

        for doc in docs:
            status_icon = {
                "COMPLETED": "✓",
                "FAILED": "✗",
                "PENDING": "⏳",
            }.get(doc.status.value.upper(), "•")

            print(f"{status_icon} [{doc.id}] {doc.title}")
            print(f"    Status: {doc.status.value}")
            print(f"    Source: {doc.file_path}")
            print(f"    Chunks: {len(doc.document_chunks)}")
            print()

    print("=" * 70 + "\n")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Ingest meditation texts into the database",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "sources", nargs="*", help="URL(s), PDF path(s), or document ID(s) to ingest"
    )

    parser.add_argument("--title", "-t", help="Custom title for the document")

    parser.add_argument(
        "--resume", "-r", type=int, help="Resume ingestion for a specific document ID"
    )

    parser.add_argument(
        "--reprocess", type=int, help="Reprocess an existing document ID while keeping the same ID"
    )

    parser.add_argument(
        "--reprocess-mode",
        choices=[mode.value for mode in ReprocessMode],
        default=ReprocessMode.FULL.value,
        help=(
            "Reprocess mode for --reprocess: full | from_chunking | from_embedding (default: full)"
        ),
    )

    parser.add_argument(
        "--clear-markdown",
        action="store_true",
        help="Clear existing markdown before reprocessing (only valid with --reprocess-mode full)",
    )

    parser.add_argument(
        "--list", "-l", action="store_true", help="List all documents in the database"
    )

    parser.add_argument("--quiet", "-q", action="store_true", help="Suppress detailed output")

    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    parser.add_argument(
        "--collection",
        "-c",
        default="meditation_chunks",
        help="Collection name for storing embeddings (default: meditation_chunks)",
    )

    args = parser.parse_args()

    if args.resume and args.reprocess:
        parser.error("Use either --resume or --reprocess, not both")
    if args.clear_markdown and not args.reprocess:
        parser.error("--clear-markdown requires --reprocess")
    if args.clear_markdown and args.reprocess_mode != ReprocessMode.FULL.value:
        parser.error("--clear-markdown is only valid with --reprocess-mode full")

    # Setup logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif args.quiet:
        logging.getLogger().setLevel(logging.WARNING)

    # List documents
    if args.list:
        list_documents()
        return

    # Resume document
    if args.resume:
        result = asyncio.run(
            ingest_batch(
                [str(args.resume)],
                titles=[args.title],
                verbose=not args.quiet,
                collection_name=args.collection,
            )
        )
        sys.exit(0 if result[0]["success"] else 1)

    # Reprocess existing document
    if args.reprocess:
        result = asyncio.run(
            ingest_batch(
                [str(args.reprocess)],
                titles=[args.title],
                verbose=not args.quiet,
                collection_name=args.collection,
                reprocess_mode=args.reprocess_mode,
                clear_markdown=args.clear_markdown,
            )
        )
        sys.exit(0 if result[0]["success"] else 1)

    # No sources provided
    if not args.sources:
        parser.print_help()
        print("\nError: Please provide at least one source to ingest")
        sys.exit(1)

    # Ingest documents
    try:
        results = asyncio.run(
            ingest_batch(
                args.sources,
                titles=[args.title] if args.title else None,
                verbose=not args.quiet,
                collection_name=args.collection,
            )
        )

        # Print summary if multiple documents
        if len(results) > 1:
            print_batch_summary(results)

        # Exit with error code if any failed
        success = all(r.get("success", False) for r in results)
        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\nIngestion cancelled by user.")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
