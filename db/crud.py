from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from . import schema


class DocumentCRUD:
    """CRUD operations for Document model."""

    def __init__(self, db: Session):
        self.db = db

    def create_document(
        self,
        title: str,
        file_path: str,
        markdown: Optional[str] = None,
        tags: Optional[List[str]] = None,
        doc_metadata: Optional[Dict] = None,
        description: Optional[str] = None,
        status: schema.DocumentStatus = schema.DocumentStatus.PENDING,
    ) -> schema.Document:
        """
        Creates a new document with source tracking.

        Args:
            title: Document title
            file_path: Source file path or URL (required for pipeline resume)
            markdown: Parsed content (optional during creation)
            tags: List of tags
            doc_metadata: Additional metadata
            description: Document description
            status: Initial status (defaults to PENDING)

        Returns:
            Created document instance
        """
        db_document = schema.Document(
            title=title,
            file_path=file_path,
            markdown=markdown,
            tags=tags or [],
            doc_metadata=doc_metadata or {},
            description=description,
            status=status,
        )
        self.db.add(db_document)
        self.db.commit()
        self.db.refresh(db_document)
        return db_document

    def get_document_by_id(self, document_id: int) -> Optional[schema.Document]:
        """
        Get a document by its ID.

        Args:
            document_id: ID of the document

        Returns:
            Document instance or None if not found
        """
        return (
            self.db.query(schema.Document)
            .filter(schema.Document.id == document_id)
            .first()
        )

    def get_all_documents(self) -> List[schema.Document]:
        """
        Get all documents.

        Returns:
            List of all documents
        """
        return self.db.query(schema.Document).all()

    def update_status(
        self,
        document_id: int,
        status: schema.DocumentStatus,
        status_details: Optional[str] = None,
    ) -> Optional[schema.Document]:
        """
        Update document status with optional details.

        Args:
            document_id: ID of document to update
            status: New status value
            status_details: Optional error message or status info

        Returns:
            Updated document or None if not found
        """
        doc = self.get_document_by_id(document_id)
        if doc:
            doc.status = status
            doc.status_details = status_details
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def update_markdown(
        self,
        document_id: int,
        markdown: str,
    ) -> Optional[schema.Document]:
        """
        Update document markdown content after parsing.

        Args:
            document_id: ID of document
            markdown: Parsed markdown content

        Returns:
            Updated document or None if not found
        """
        doc = self.get_document_by_id(document_id)
        if doc:
            doc.markdown = markdown
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def store_chunks(
        self,
        document_id: int,
        chunks: List[Dict[str, Any]],
    ) -> Optional[schema.Document]:
        """
        Store serialized chunks temporarily in document.

        This is temporary storage before embedding. After successful
        embedding, call clear_chunks() to free up space.

        Args:
            document_id: ID of document
            chunks: List of serialized LangChain Documents

        Returns:
            Updated document or None if not found
        """
        doc = self.get_document_by_id(document_id)
        if doc:
            doc.chunks = chunks
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def clear_chunks(
        self,
        document_id: int,
    ) -> Optional[schema.Document]:
        """
        Clear temporary chunk storage after successful embedding.

        Args:
            document_id: ID of document

        Returns:
            Updated document or None if not found
        """
        doc = self.get_document_by_id(document_id)
        if doc:
            doc.chunks = None
            self.db.commit()
            self.db.refresh(doc)
        return doc

    def get_documents_by_status(
        self,
        status: schema.DocumentStatus,
    ) -> List[schema.Document]:
        """
        Get all documents with specific status.

        Args:
            status: Status to filter by

        Returns:
            List of matching documents
        """
        return (
            self.db.query(schema.Document)
            .filter(schema.Document.status == status)
            .order_by(schema.Document.created_at.desc())
            .all()
        )

    def get_failed_documents(self) -> List[schema.Document]:
        """
        Get all documents with FAILED status.

        Returns:
            List of failed documents with status_details
        """
        return self.get_documents_by_status(schema.DocumentStatus.FAILED)

    def get_document_by_file_path(self, file_path: str) -> Optional[schema.Document]:
        """
        Get a document by its file path or URL.

        Args:
            file_path: Source file path or URL

        Returns:
            Document instance or None if not found
        """
        return (
            self.db.query(schema.Document)
            .filter(schema.Document.file_path == file_path)
            .first()
        )

    def check_duplicate(self, file_path: str) -> Optional[schema.Document]:
        """
        Check if a document with the same source already exists.

        Args:
            file_path: Source file path or URL to check

        Returns:
            Existing document if found, None otherwise
        """
        return self.get_document_by_file_path(file_path)

    def delete_document(self, document_id: int) -> bool:
        """
        Delete a document and all its associated chunks.

        Args:
            document_id: ID of document to delete

        Returns:
            True if deleted, False if not found
        """
        doc = self.get_document_by_id(document_id)
        if doc:
            self.db.delete(doc)
            self.db.commit()
            return True
        return False


class ChunkCRUD:
    """CRUD operations for Chunk model."""

    def __init__(self, db: Session):
        self.db = db

    def create_chunks_batch(
        self,
        document_id: int,
        chunks_data: List[Dict[str, Any]],
    ) -> List[schema.Chunk]:
        """
        Create multiple chunks for a document.

        Args:
            document_id: Parent document ID
            chunks_data: List of dicts with chunk information:
                - uuid: UUID from LangChain embedding
                - chunk_text: Text content
                - chunk_index: Position in document
                - chunk_metadata: Optional metadata dict

        Returns:
            List of created Chunk instances
        """
        chunks = []
        for data in chunks_data:
            chunk = schema.Chunk(
                uuid=data["uuid"],
                document_id=document_id,
                chunk_text=data["chunk_text"],
                chunk_index=data["chunk_index"],
                chunk_metadata=data.get("chunk_metadata", {}),
            )
            chunks.append(chunk)

        self.db.add_all(chunks)
        self.db.commit()

        for chunk in chunks:
            self.db.refresh(chunk)

        return chunks

    def get_chunks_by_document(
        self,
        document_id: int,
    ) -> List[schema.Chunk]:
        """
        Get all chunks for a document, ordered by index.

        Args:
            document_id: Parent document ID

        Returns:
            List of chunks ordered by chunk_index
        """
        return (
            self.db.query(schema.Chunk)
            .filter(schema.Chunk.document_id == document_id)
            .order_by(schema.Chunk.chunk_index)
            .all()
        )

    def get_chunk_by_uuid(
        self,
        uuid: str,
    ) -> Optional[schema.Chunk]:
        """
        Get chunk by UUID (for linking with vector search results).

        Args:
            uuid: Chunk UUID

        Returns:
            Chunk instance or None
        """
        return (
            self.db.query(schema.Chunk)
            .filter(schema.Chunk.uuid == uuid)
            .first()
        )

    def delete_chunks_by_document(self, document_id: int) -> int:
        """
        Delete all chunks for a document.

        Args:
            document_id: Parent document ID

        Returns:
            Number of chunks deleted
        """
        deleted = (
            self.db.query(schema.Chunk)
            .filter(schema.Chunk.document_id == document_id)
            .delete()
        )
        self.db.commit()
        return deleted
