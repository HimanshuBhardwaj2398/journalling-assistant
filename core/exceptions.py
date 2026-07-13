"""
Central exception hierarchy for the meditation database project.

This module defines all custom exceptions used throughout the application,
organized in a clear hierarchy for proper error handling and categorization.
"""


class MeditationDBError(Exception):
    """
    Base exception for all meditation database errors.

    All custom exceptions in the application should inherit from this base class
    to allow catching all application-specific errors.
    """

    pass


# ============================================================================
# CONFIGURATION ERRORS
# ============================================================================


class ConfigurationError(MeditationDBError):
    """
    Raised when configuration validation or loading fails.

    Examples:
        - Missing required environment variables
        - Invalid configuration values
        - API keys not set
    """

    pass


# ============================================================================
# PIPELINE ERRORS
# ============================================================================


class PipelineError(MeditationDBError):
    """
    Base class for pipeline-related errors.

    This covers errors occurring during document ingestion pipeline execution.
    """

    pass


class ParsingError(PipelineError):
    """
    Raised when document parsing fails.

    Examples:
        - PDF extraction failure
        - URL fetch timeout
        - Invalid document format
        - Empty parsing result
    """

    pass


class ChunkingError(PipelineError):
    """
    Raised when text chunking fails.

    Examples:
        - Semantic chunking model loading failure
        - Empty text provided for chunking
        - Chunk size validation errors
    """

    pass


class EmbeddingError(PipelineError):
    """
    Raised when document embedding fails.

    Examples:
        - Vector store connection failure
        - Embedding API errors
        - Invalid embedding dimensions
    """

    pass


# ============================================================================
# DATABASE ERRORS
# ============================================================================


class DatabaseError(MeditationDBError):
    """
    Base class for database-related errors.

    This covers errors occurring during database operations.
    """

    pass


class DocumentNotFoundError(DatabaseError):
    """
    Raised when a requested document does not exist in the database.

    Examples:
        - Querying non-existent document ID
        - Attempting to resume processing for missing document
    """

    pass


class DuplicateDocumentError(DatabaseError):
    """
    Raised when attempting to ingest a document that already exists.

    Examples:
        - URL already ingested
        - PDF file path already exists in database
    """

    pass


class SchemaValidationError(DatabaseError):
    """
    Raised when database schema validation fails.

    Examples:
        - Missing required columns
        - Incompatible column types
        - Failed schema migration
    """

    pass


# ============================================================================
# VECTOR STORE ERRORS
# ============================================================================


class VectorStoreError(MeditationDBError):
    """
    Raised when vector store operations fail.

    Examples:
        - Adding or deleting embeddings fails
        - Vector store returns inconsistent IDs
    """

    pass


class DatabaseConnectionError(VectorStoreError):
    """
    Raised when the vector store's database connection fails.

    Examples:
        - Invalid connection string
        - Database unreachable
    """

    pass


# ============================================================================
# COLLECTION ERRORS
# ============================================================================


class CollectionError(MeditationDBError):
    """
    Raised when collection management operations fail.

    Examples:
        - Failed to delete embeddings from vector store
        - Collection not found
        - Operation failed on both databases
    """

    pass


class EmbeddingSyncError(CollectionError):
    """
    Raised when app DB and vector store are out of sync.

    Examples:
        - Orphaned embeddings in vector store
        - Missing embeddings for chunks in app DB
        - UUID mismatch between databases
    """

    pass
