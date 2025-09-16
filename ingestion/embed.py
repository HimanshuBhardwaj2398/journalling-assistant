# import os
# import getpass
# from psycopg2 import errors
# from typing import List, Optional

# from langchain_community.vectorstores.pgvector import PGVector
# from langchain_voyageai import VoyageAIEmbeddings
# from langchain_core.documents import Document
# from langchain_core.embeddings import Embeddings
# from langchain_core.vectorstores import VectorStore
# import logging


# def get_embeddings(model_name: str = "voyage-3") -> Embeddings:
#     """
#     Initializes and returns a VoyageAIEmbeddings instance.

#     Args:
#         model_name (str): The name of the Voyage AI model to use.

#     Returns:
#         VoyageAIEmbeddings: An instance of the Voyage AI embeddings client.
#     """

#     return VoyageAIEmbeddings(model=model_name)


# def get_or_create_vector_store(
#     collection_name: str, embeddings: Embeddings
# ) -> PGVector:
#     """
#     Get or create a vector store for storing embeddings.

#     Returns:
#         PGVector: An instance of the PGVector vector store.
#     """
#     try:
#         return PGVector(
#             embeddings=embeddings,
#             collection_name=collection_name,
#             connection=os.environ.get("DB_URL"),
#             use_jsonb=True,
#         )
#     except Exception as e:
#         if isinstance(e, errors.InvalidCatalogName):
#             logging.info(
#                 f"Database not found. Please check your connection string: {e}"
#             )
#         else:
#             logging.info(f"An error occurred while connecting to the database: {e}")
#         raise


# def embed_and_store(docs: List[Document], vector_store: VectorStore) -> List[str]:
#     """
#     Embed documents and store them in the vector store.

#     Args:
#         docs (List[Document]): A list of documents to embed and store.
#         vector_store (VectorStore): The vector store to use for storing embeddings.

#     Returns:
#         List[str]: A list of IDs of the stored documents.
#     """
#     if not docs:
#         logging.warning("No documents provided for embedding. Returning empty list.")
#         return []

#     logging.info(f"Embedding {len(docs)} documents...")
#     embedded_texts_ids = vector_store.add_documents(docs)
#     logging.info(
#         f"Successfully embedded and stored {len(embedded_texts_ids)} documents."
#     )
#     return embedded_texts_ids
"""
Vector store operations for document embedding and retrieval.

This module provides utilities for creating vector stores, embedding documents,
and managing the connection to PostgreSQL with pgvector extension.
"""

import os
import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from contextlib import contextmanager

from psycopg2 import errors as pg_errors
from langchain_community.vectorstores.pgvector import PGVector
from langchain_voyageai import VoyageAIEmbeddings
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore


# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class VectorStoreConfig:
    """Configuration for vector store operations."""

    model_name: str = "voyage-3.5"
    collection_name: str = "documents"
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
                logger.info(
                    f"Initialized embeddings with model: {self.config.model_name}"
                )
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
            vector_store = PGVector(
                embeddings=self.embeddings,
                collection_name=self.config.collection_name,
                connection=self.config.db_url,
                use_jsonb=self.config.use_jsonb,
            )

            logger.info(
                f"Connected to vector store collection: {self.config.collection_name}"
            )
            return vector_store

        except pg_errors.InvalidCatalogName as e:
            error_msg = f"Database '{self.config.collection_name}' not found. Check connection string."
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

        logger.info(
            f"Processing {total_docs} documents in batches of {self.config.batch_size}"
        )

        for i in range(0, total_docs, self.config.batch_size):
            batch = documents[i : i + self.config.batch_size]
            batch_num = (i // self.config.batch_size) + 1
            total_batches = (
                total_docs + self.config.batch_size - 1
            ) // self.config.batch_size

            logger.info(
                f"Processing batch {batch_num}/{total_batches} ({len(batch)} documents)"
            )

            try:
                batch_ids = self.vector_store.add_documents(batch)
                all_ids.extend(batch_ids)
                logger.info(
                    f"Successfully processed batch {batch_num} - {len(batch_ids)} documents stored"
                )

            except Exception as e:
                logger.error(f"Failed to process batch {batch_num}: {e}")
                # Continue with next batch rather than failing completely
                continue

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
