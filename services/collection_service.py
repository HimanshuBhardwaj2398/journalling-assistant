"""
Collection management service - coordinates app DB and vector store operations.

Ensures atomic consistency between document/chunk tables and vector embeddings.
This service should be used for all delete operations to prevent orphaned embeddings.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.exceptions import CollectionError, DocumentNotFoundError
from db.crud import ChunkCRUD, DocumentCRUD, get_all_collections
from db.database import session_scope
from db.schema import DocumentStatus
from ingestion.embed import VectorStoreConfig, VectorStoreError, VectorStoreManager
from ingestion.orchestrator import IngestionOrchestrator

logger = logging.getLogger(__name__)


@dataclass
class DeleteResult:
    """Result of a document delete operation."""

    document_id: int
    title: str
    chunks_deleted: int
    embeddings_deleted: int
    success: bool
    error: Optional[str] = None


@dataclass
class ReprocessResult:
    """Result of a document reprocess operation."""

    document_id: int
    title: str
    old_chunks_deleted: int
    old_embeddings_deleted: int
    new_chunks_created: int
    success: bool
    error: Optional[str] = None


class CollectionService:
    """
    Service for managing document collections across app DB and vector store.

    This service ensures atomic operations between:
    - Application database (documents, chunks tables)
    - Vector database (langchain_pg_embedding table)

    Always use this service for delete operations to maintain consistency.
    """

    def __init__(
        self,
        collection_name: str = "buddhist_texts",
        db_url: Optional[str] = None,
    ):
        """
        Initialize collection service.

        Args:
            collection_name: Name of the vector store collection
            db_url: Database URL (defaults to DB_URL or DATABASE_URL env var)
        """
        self.collection_name = collection_name
        self.db_url = db_url or os.getenv("DB_URL") or os.getenv("DATABASE_URL")

        if not self.db_url:
            raise CollectionError(
                "Database URL required. Set DB_URL or DATABASE_URL environment variable."
            )

        self._vector_store_manager: Optional[VectorStoreManager] = None

    @property
    def vector_store_manager(self) -> VectorStoreManager:
        """Lazy-load vector store manager."""
        if self._vector_store_manager is None:
            config = VectorStoreConfig(
                collection_name=self.collection_name,
                db_url=self.db_url,
            )
            self._vector_store_manager = VectorStoreManager(config)
        return self._vector_store_manager

    # =========================================================================
    # DELETE OPERATIONS
    # =========================================================================

    async def delete_document_complete(
        self,
        document_id: int,
    ) -> DeleteResult:
        """
        Delete document with all associated data (atomic operation).

        Order of operations (critical for data integrity):
        1. Get chunk UUIDs from app database
        2. Delete embeddings from vector store FIRST
        3. Delete document from app database (chunks cascade via FK)

        This order ensures:
        - If vector delete fails, app DB is unchanged (safe rollback)
        - If app DB delete fails after vector delete, we can retry

        Args:
            document_id: ID of document to delete

        Returns:
            DeleteResult with operation details

        Raises:
            DocumentNotFoundError: If document doesn't exist
            CollectionError: If deletion fails
        """
        # Step 1: Get document and chunk UUIDs from app DB
        with session_scope() as session:
            doc_crud = DocumentCRUD(session)
            chunk_crud = ChunkCRUD(session)

            doc = doc_crud.get_document_by_id(document_id)
            if not doc:
                raise DocumentNotFoundError(f"Document {document_id} not found")

            chunks = chunk_crud.get_chunks_by_document(document_id)
            chunk_uuids = [c.uuid for c in chunks]
            doc_title = doc.title
            chunk_count = len(chunks)

        logger.info(f"Deleting document {document_id} '{doc_title}' with {chunk_count} chunks")

        # Step 2: Delete from vector store FIRST
        embeddings_deleted = 0
        if chunk_uuids:
            try:
                embeddings_deleted = self.vector_store_manager.delete_by_ids(chunk_uuids)
                logger.info(f"Deleted {embeddings_deleted} embeddings from vector store")
            except VectorStoreError as e:
                logger.error(f"Vector store delete failed: {e}")
                return DeleteResult(
                    document_id=document_id,
                    title=doc_title,
                    chunks_deleted=0,
                    embeddings_deleted=0,
                    success=False,
                    error=f"Vector store delete failed: {e}",
                )

        # Step 3: Delete from app database
        with session_scope() as session:
            doc_crud = DocumentCRUD(session)

            if not doc_crud.delete_document(document_id):
                # This shouldn't happen since we verified doc exists above
                logger.error(
                    f"App DB delete failed for document {document_id} (embeddings already deleted)"
                )
                return DeleteResult(
                    document_id=document_id,
                    title=doc_title,
                    chunks_deleted=0,
                    embeddings_deleted=embeddings_deleted,
                    success=False,
                    error="App DB delete failed (embeddings already deleted - manual cleanup may be needed)",
                )

        logger.info(
            f"Successfully deleted document {document_id}: "
            f"{chunk_count} chunks, {embeddings_deleted} embeddings"
        )

        return DeleteResult(
            document_id=document_id,
            title=doc_title,
            chunks_deleted=chunk_count,
            embeddings_deleted=embeddings_deleted,
            success=True,
        )

    def delete_document_complete_sync(self, document_id: int) -> DeleteResult:
        """
        Synchronous wrapper for delete_document_complete.

        Args:
            document_id: ID of document to delete

        Returns:
            DeleteResult with operation details
        """
        return asyncio.run(self.delete_document_complete(document_id))

    async def delete_documents_batch(
        self,
        document_ids: List[int],
    ) -> List[DeleteResult]:
        """
        Delete multiple documents atomically.

        Processes each document independently, collecting results.
        Partial failures don't affect other deletions.

        Args:
            document_ids: List of document IDs to delete

        Returns:
            List of DeleteResult for each document
        """
        results = []

        for doc_id in document_ids:
            try:
                result = await self.delete_document_complete(doc_id)
                results.append(result)
            except DocumentNotFoundError:
                results.append(
                    DeleteResult(
                        document_id=doc_id,
                        title="Unknown",
                        chunks_deleted=0,
                        embeddings_deleted=0,
                        success=False,
                        error=f"Document {doc_id} not found",
                    )
                )
            except Exception as e:
                logger.error(f"Unexpected error deleting document {doc_id}: {e}")
                results.append(
                    DeleteResult(
                        document_id=doc_id,
                        title="Unknown",
                        chunks_deleted=0,
                        embeddings_deleted=0,
                        success=False,
                        error=str(e),
                    )
                )

        return results

    def delete_documents_batch_sync(
        self,
        document_ids: List[int],
    ) -> List[DeleteResult]:
        """Synchronous wrapper for delete_documents_batch."""
        return asyncio.run(self.delete_documents_batch(document_ids))

    # =========================================================================
    # REPROCESS OPERATIONS
    # =========================================================================

    async def reprocess_document(
        self,
        document_id: int,
    ) -> ReprocessResult:
        """
        Reprocess a document: delete existing chunks/embeddings and re-ingest.

        Useful when:
        - Chunking strategy has changed
        - Embedding model has been updated
        - Document processing failed partway through

        Order of operations:
        1. Get document info and existing chunk UUIDs
        2. Delete embeddings from vector store
        3. Delete chunks from app DB
        4. Reset document status to PARSED (keeps markdown)
        5. Run orchestrator to re-chunk and re-embed

        Args:
            document_id: ID of document to reprocess

        Returns:
            ReprocessResult with operation details

        Raises:
            DocumentNotFoundError: If document doesn't exist
            CollectionError: If reprocessing fails
        """
        # Step 1: Get document and chunk UUIDs
        with session_scope() as session:
            doc_crud = DocumentCRUD(session)
            chunk_crud = ChunkCRUD(session)

            doc = doc_crud.get_document_by_id(document_id)
            if not doc:
                raise DocumentNotFoundError(f"Document {document_id} not found")

            chunks = chunk_crud.get_chunks_by_document(document_id)
            chunk_uuids = [c.uuid for c in chunks]
            doc_title = doc.title
            old_chunk_count = len(chunks)

        logger.info(
            f"Reprocessing document {document_id} '{doc_title}' "
            f"with {old_chunk_count} existing chunks"
        )

        # Step 2: Delete embeddings from vector store
        embeddings_deleted = 0
        if chunk_uuids:
            try:
                embeddings_deleted = self.vector_store_manager.delete_by_ids(chunk_uuids)
                logger.info(f"Deleted {embeddings_deleted} old embeddings")
            except VectorStoreError as e:
                logger.error(f"Vector store delete failed: {e}")
                return ReprocessResult(
                    document_id=document_id,
                    title=doc_title,
                    old_chunks_deleted=0,
                    old_embeddings_deleted=0,
                    new_chunks_created=0,
                    success=False,
                    error=f"Failed to delete old embeddings: {e}",
                )

        # Step 3: Delete chunks from app DB and reset status
        with session_scope() as session:
            chunk_crud = ChunkCRUD(session)
            doc_crud = DocumentCRUD(session)

            chunks_deleted = chunk_crud.delete_chunks_by_document(document_id)
            logger.info(f"Deleted {chunks_deleted} chunks from app DB")

            # Reset status to PARSED so orchestrator will re-chunk and re-embed
            doc_crud.update_status(
                document_id,
                DocumentStatus.PARSED,
                status_details="Reprocessing: chunks cleared, ready for re-chunking",
            )

        # Step 4: Run orchestrator to re-process
        try:
            orchestrator = IngestionOrchestrator(
                vector_store_config=VectorStoreConfig(
                    collection_name=self.collection_name,
                    db_url=self.db_url,
                )
            )
            result = await orchestrator.process(
                source=document_id,
                reprocess_mode="from_chunking",
            )

            new_chunk_count = result.get("chunk_count", 0)
            logger.info(
                f"Reprocessing complete for document {document_id}: "
                f"{new_chunk_count} new chunks created"
            )

            return ReprocessResult(
                document_id=document_id,
                title=doc_title,
                old_chunks_deleted=old_chunk_count,
                old_embeddings_deleted=embeddings_deleted,
                new_chunks_created=new_chunk_count,
                success=True,
            )

        except Exception as e:
            logger.error(f"Reprocessing failed for document {document_id}: {e}")
            return ReprocessResult(
                document_id=document_id,
                title=doc_title,
                old_chunks_deleted=old_chunk_count,
                old_embeddings_deleted=embeddings_deleted,
                new_chunks_created=0,
                success=False,
                error=f"Reprocessing failed: {e}",
            )

    def reprocess_document_sync(self, document_id: int) -> ReprocessResult:
        """
        Synchronous wrapper for reprocess_document.

        Args:
            document_id: ID of document to reprocess

        Returns:
            ReprocessResult with operation details
        """
        return asyncio.run(self.reprocess_document(document_id))

    # =========================================================================
    # COLLECTION OPERATIONS
    # =========================================================================

    def list_collections(self) -> List[str]:
        """
        List all available vector store collections.

        Returns:
            List of collection names sorted alphabetically
        """
        with session_scope() as session:
            return get_all_collections(session)

    def get_collection_stats(
        self,
        collection_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Get statistics for a collection.

        Args:
            collection_name: Collection name (defaults to current)

        Returns:
            Dict with document_count, chunk_count, and collection metadata
        """
        target_collection = collection_name or self.collection_name

        with session_scope() as session:
            doc_crud = DocumentCRUD(session)
            chunk_crud = ChunkCRUD(session)

            all_docs = doc_crud.get_all_documents()
            total_chunks = sum(len(chunk_crud.get_chunks_by_document(doc.id)) for doc in all_docs)

        return {
            "collection_name": target_collection,
            "document_count": len(all_docs),
            "chunk_count": total_chunks,
            "vector_store_info": self.vector_store_manager.get_collection_info(),
        }
