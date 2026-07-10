"""
Vector store operations for document embedding and retrieval.

This module provides utilities for creating vector stores, embedding documents,
and managing the connection to PostgreSQL with pgvector extension.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from langchain_community.vectorstores.pgvector import PGVector
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_voyageai import VoyageAIEmbeddings
from psycopg2 import errors as pg_errors

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class VectorStoreConfig:
    """Configuration for vector store operations."""

    model_name: str = "voyage-3.5"
    collection_name: str = "buddhist_texts"
    db_url: Optional[str] = None
    use_jsonb: bool = True
    batch_size: int = 100

    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.db_url:
            self.db_url = os.getenv("DB_URL")

        if not self.db_url:
            raise ValueError(
                "Database URL must be provided either via db_url parameter "
                "or DB_URL environment variable"
            )


class VectorStoreError(Exception):
    """Base exception for vector store operations."""

    pass


class DatabaseConnectionError(VectorStoreError):
    """Raised when database connection fails."""

    pass


class EmbeddingError(VectorStoreError):
    """Raised when document embedding fails."""

    pass


class VectorStoreManager:
    """
    Manages vector store operations including embedding and document storage.

    This class provides a high-level interface for working with vector stores,
    handling connection management, error handling, and batch processing.
    """

    def __init__(self, config: VectorStoreConfig):
        """
        Initialize the vector store manager.

        Args:
            config: Configuration object containing vector store settings.
        """
        self.config = config
        self._embeddings: Optional[Embeddings] = None
        self._vector_store: Optional[PGVector] = None

    @property
    def embeddings(self) -> Embeddings:
        """Lazy-load embeddings client."""
        if self._embeddings is None:
            try:
                self._embeddings = VoyageAIEmbeddings(model=self.config.model_name)
                logger.info(f"Initialized embeddings with model: {self.config.model_name}")
            except Exception as e:
                raise EmbeddingError(f"Failed to initialize embeddings: {e}") from e

        return self._embeddings

    @property
    def vector_store(self) -> PGVector:
        """Lazy-load vector store connection."""
        if self._vector_store is None:
            self._vector_store = self._create_vector_store()

        return self._vector_store

    def _create_vector_store(self) -> PGVector:
        """
        Create and configure the vector store connection.

        Returns:
            Configured PGVector instance.

        Raises:
            DatabaseConnectionError: If connection to database fails.
        """
        try:
            # Use correct API for langchain_community.vectorstores.pgvector.PGVector
            # Note: First two args are positional: connection_string, embedding_function
            vector_store = PGVector(
                connection_string=self.config.db_url,
                embedding_function=self.embeddings,
                collection_name=self.config.collection_name,
                use_jsonb=self.config.use_jsonb,
            )

            logger.info(f"Connected to vector store collection: {self.config.collection_name}")
            return vector_store

        except pg_errors.InvalidCatalogName as e:
            error_msg = (
                f"Database '{self.config.collection_name}' not found. Check connection string."
            )
            logger.error(error_msg)
            raise DatabaseConnectionError(error_msg) from e

        except Exception as e:
            error_msg = f"Failed to connect to database: {e}"
            logger.error(error_msg)
            raise DatabaseConnectionError(error_msg) from e

    def embed_documents(self, documents: List[Document]) -> List[str]:
        """
        Embed and store documents in the vector store.

        Args:
            documents: List of documents to embed and store.

        Returns:
            List of document IDs that were successfully stored.

        Raises:
            EmbeddingError: If document embedding or storage fails.
        """
        if not documents:
            logger.warning("No documents provided for embedding")
            return []

        try:
            return self._embed_documents_batch(documents)
        except EmbeddingError:
            raise
        except Exception as e:
            raise EmbeddingError(f"Failed to embed documents: {e}") from e

    def _embed_documents_batch(self, documents: List[Document]) -> List[str]:
        """
        Embed documents in batches for better performance and error handling.

        Args:
            documents: List of documents to process.

        Returns:
            List of all document IDs that were successfully stored.
        """
        all_ids = []
        total_docs = len(documents)

        logger.info(f"Processing {total_docs} documents in batches of {self.config.batch_size}")

        for i in range(0, total_docs, self.config.batch_size):
            batch = documents[i : i + self.config.batch_size]
            batch_num = (i // self.config.batch_size) + 1
            total_batches = (total_docs + self.config.batch_size - 1) // self.config.batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} documents)")

            try:
                batch_ids = self.vector_store.add_documents(batch)
                if len(batch_ids) != len(batch):
                    raise EmbeddingError(
                        f"Batch {batch_num}/{total_batches} returned {len(batch_ids)} "
                        f"IDs for {len(batch)} documents"
                    )
                all_ids.extend(batch_ids)
                logger.info(
                    f"Successfully processed batch {batch_num} - {len(batch_ids)} documents stored"
                )

            except Exception as e:
                logger.error(f"Failed to process batch {batch_num}: {e}")
                raise EmbeddingError(f"Batch {batch_num}/{total_batches} failed: {e}") from e

        logger.info(
            f"Completed processing: {len(all_ids)}/{total_docs} documents successfully stored"
        )
        return all_ids

    def get_collection_info(self) -> Dict[str, Any]:
        """
        Get information about the current collection.

        Returns:
            Dictionary containing collection metadata.
        """
        return {
            "collection_name": self.config.collection_name,
            "model_name": self.config.model_name,
            "batch_size": self.config.batch_size,
            "use_jsonb": self.config.use_jsonb,
        }

    def delete_by_ids(self, ids: List[str]) -> int:
        """
        Delete embeddings by their UUIDs.

        Args:
            ids: List of embedding UUIDs to delete.

        Returns:
            Number of embeddings deleted (based on input count).

        Raises:
            VectorStoreError: If deletion fails.
        """
        if not ids:
            logger.warning("No IDs provided for deletion")
            return 0

        try:
            logger.info(f"Deleting {len(ids)} embeddings from vector store")
            self.vector_store.delete(ids=ids)
            logger.info(f"Successfully deleted {len(ids)} embeddings")
            return len(ids)

        except Exception as e:
            error_msg = f"Failed to delete embeddings: {e}"
            logger.error(error_msg)
            raise VectorStoreError(error_msg) from e

    def delete_by_metadata_filter(self, filter: Dict[str, Any]) -> bool:
        """
        Delete embeddings matching a metadata filter.

        Uses LangChain PGVector's filter support for metadata-based deletion.
        Useful for deleting all embeddings for a specific document.

        Args:
            filter: Metadata filter dict (e.g., {"original_doc_id": 123})

        Returns:
            True if deletion completed successfully.

        Raises:
            VectorStoreError: If deletion fails.
        """
        if not filter:
            logger.warning("No filter provided for deletion")
            return False

        try:
            logger.info(f"Deleting embeddings with filter: {filter}")
            self.vector_store.delete(filter=filter)
            logger.info("Successfully deleted embeddings by filter")
            return True

        except Exception as e:
            error_msg = f"Failed to delete embeddings by filter: {e}"
            logger.error(error_msg)
            raise VectorStoreError(error_msg) from e
