"""
Ingestion service - business logic for document processing.

Handles document ingestion, processing, and orchestration.
"""

import asyncio
from typing import Callable, Optional

from core.exceptions import DuplicateDocumentError
from core.interfaces import StageStatus
from db.crud import DocumentCRUD
from db.database import session_scope
from db.schema import DocumentStatus
from ingestion.embed import VectorStoreConfig
from ingestion.orchestrator import IngestionOrchestrator


def get_orchestrator(collection_name: str = "buddhist_texts") -> IngestionOrchestrator:
    """Initialize ingestion orchestrator with vector store config.

    Args:
        collection_name: Name of the collection to store embeddings in

    Returns:
        Configured IngestionOrchestrator instance
    """
    return IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(collection_name=collection_name)
    )


async def ingest_document_async(
    source: str,
    title: str,
    description: str,
    doc_type: str,
    category: str,
    tags: list,
    collection_name: str = "buddhist_texts",
    on_stage_update: Optional[Callable[[str, StageStatus], None]] = None,
) -> dict:
    """
    Ingest document with metadata.

    Args:
        source: URL or file path to the document
        title: Document title
        description: Document description
        doc_type: Type of document (e.g., ancient_text, lecture)
        category: Primary category (e.g., buddhism)
        tags: List of tags for searchability
        collection_name: Name of the vector store collection
        on_stage_update: Optional callback(stage_name, status) for progress updates

    Returns:
        dict: Result from orchestrator with success status and chunk count

    Raises:
        DuplicateDocumentError: If document with same source already exists
    """
    # Check for duplicates first
    with session_scope() as session:
        crud = DocumentCRUD(session)
        existing_doc = crud.check_duplicate(source)
        if existing_doc:
            raise DuplicateDocumentError(
                f"Document with source '{source}' already exists "
                f"(ID: {existing_doc.id}, Title: '{existing_doc.title}', "
                f"Status: {existing_doc.status.value})"
            )

    orchestrator = get_orchestrator(collection_name)

    # Build metadata
    metadata = {}
    if doc_type:
        metadata["type"] = doc_type
    if category:
        metadata["category"] = category

    # Combine tags
    all_tags = tags.copy() if tags else []
    if doc_type:
        all_tags.append(f"type:{doc_type}")
    if category:
        all_tags.append(f"category:{category}")

    # Create document first with metadata
    with session_scope() as session:
        doc = DocumentCRUD(session).create_document(
            title=title,
            file_path=source,
            description=description,
            doc_metadata=metadata,
            tags=all_tags,
            status=DocumentStatus.PENDING,
        )
        doc_id = doc.id

    # Process through pipeline
    result = await orchestrator.process(
        source=doc_id,
        title=title,
        on_stage_update=on_stage_update,
    )
    return result


def ingest_document(
    source: str,
    title: str,
    description: str,
    doc_type: str,
    category: str,
    tags: list,
    collection_name: str = "buddhist_texts",
    on_stage_update: Optional[Callable[[str, StageStatus], None]] = None,
) -> dict:
    """Synchronous wrapper for async ingestion."""
    return asyncio.run(
        ingest_document_async(
            source,
            title,
            description,
            doc_type,
            category,
            tags,
            collection_name,
            on_stage_update=on_stage_update,
        )
    )


async def process_document_by_id_async(
    doc_id: int,
    collection_name: str = "buddhist_texts",
    on_stage_update: Optional[Callable[[str, StageStatus], None]] = None,
    reprocess_mode: Optional[str] = None,
    clear_markdown: bool = False,
) -> dict:
    """
    Process/resume a document by its ID.

    Args:
        doc_id: Database ID of the document to process
        collection_name: Name of the vector store collection
        reprocess_mode: Optional reprocessing mode for existing docs
        clear_markdown: Clear stored markdown before reprocessing (full mode only)

    Returns:
        dict: Result from orchestrator
    """
    orchestrator = get_orchestrator(collection_name)
    result = await orchestrator.process(
        source=doc_id,
        on_stage_update=on_stage_update,
        reprocess_mode=reprocess_mode,
        clear_markdown=clear_markdown,
    )
    return result


def process_document_by_id(
    doc_id: int,
    collection_name: str = "buddhist_texts",
    on_stage_update: Optional[Callable[[str, StageStatus], None]] = None,
    reprocess_mode: Optional[str] = None,
    clear_markdown: bool = False,
) -> dict:
    """Synchronous wrapper for async document processing."""
    return asyncio.run(
        process_document_by_id_async(
            doc_id,
            collection_name,
            on_stage_update=on_stage_update,
            reprocess_mode=reprocess_mode,
            clear_markdown=clear_markdown,
        )
    )
