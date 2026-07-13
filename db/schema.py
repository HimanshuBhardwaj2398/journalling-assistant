"""ORM models for documents and chunks (see db/crud.py for operations)."""

import enum

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class DocumentStatus(enum.Enum):
    """Enumeration for document status."""

    PENDING = "pending"
    PARSING = "parsing"
    PARSED = "parsed"
    CHUNKING = "chunking"
    CHUNKED = "chunked"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class Document(Base):
    __tablename__ = "documents"

    # Primary Key
    id = Column(BigInteger, primary_key=True)

    # Source Information
    title = Column(Text, nullable=False)
    file_path = Column(Text, nullable=True, comment="Original source: URL or file path")
    description = Column(Text, nullable=True)

    # Content
    markdown = Column(Text, nullable=True)

    # Metadata
    doc_metadata = Column(JSONB, nullable=True, default=dict)
    tags = Column(ARRAY(Text), nullable=True, default=list)

    # Pipeline Status
    status = Column(
        Enum(DocumentStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=DocumentStatus.PENDING,
        nullable=False,
        index=True,  # Add index for filtering by status
    )
    status_details = Column(
        Text,
        nullable=True,
        comment="Error messages or status information from pipeline stages",
    )

    # Temporary Chunk Storage (cleared after successful embedding)
    chunks = Column(
        JSONB,
        nullable=True,
        comment="Serialized chunks before embedding (temporary storage)",
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    document_chunks = relationship(
        "Chunk",
        back_populates="parent_document",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        """Provides a developer-friendly representation of the object."""
        return f"<Document(id={self.id}, title='{self.title}', status={self.status.value})>"


class Chunk(Base):
    """
    Chunk model for storing chunk-level metadata.

    This table stores metadata about individual chunks and maintains relationships
    with parent documents. The actual vector embeddings are stored separately by
    LangChain in the langchain_pg_embedding table, linked via UUID.
    """

    __tablename__ = "chunks"

    # Primary Key
    id = Column(BigInteger, primary_key=True, autoincrement=True)

    # UUID for linking with LangChain embeddings table
    uuid = Column(
        Text,
        unique=True,
        nullable=False,
        comment="UUID linking to langchain_pg_embedding table",
    )

    # Parent Relationship
    document_id = Column(
        BigInteger,
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Chunk Content
    chunk_text = Column(Text, nullable=False)
    chunk_index = Column(
        Integer,
        nullable=False,
        comment="Position in parent document (0-indexed)",
    )

    # Metadata
    chunk_metadata = Column(
        JSONB,
        nullable=True,
        default=dict,
        comment="Header hierarchy, semantic boundaries, etc.",
    )

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    parent_document = relationship("Document", back_populates="document_chunks")

    def __repr__(self):
        """Provides a developer-friendly representation of the object."""
        return f"<Chunk(id={self.id}, doc_id={self.document_id}, index={self.chunk_index})>"
