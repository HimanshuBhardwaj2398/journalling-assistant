from sqlalchemy.orm import Session
from . import schema

## import context manager for session handling
from contextlib import contextmanager


class DocumentCRUD:
    def __init__(self, db: Session):
        self.db = db

    def create_document(
        self,
        title: str,
        markdown: str,
        tags: list[str] = None,
        doc_metadata: dict = None,
        description: str = None,
    ):
        """
        Creates a new document and stores it in the database.
        """
        db_document = schema.Document(
            title=title,
            markdown=markdown,
            tags=tags,
            doc_metadata=doc_metadata,
            description=description,
        )
        self.db.add(db_document)
        self.db.commit()
        self.db.refresh(db_document)
        return db_document

    def get_document_by_id(self, document_id: int):
        return (
            self.db.query(schema.Document)
            .filter(schema.Document.id == document_id)
            .first()
        )

    def get_all_documents(self):
        return self.db.query(schema.Document).all()


class EmbeddingCRUD:
    def __init__(self, db: Session):
        self.db = db

    def create_embedding(self, document_id: int, chunk_text: str, vector: list[float]):
        """
        Creates a new embedding and stores it in the database.
        """
        db_embedding = schema.Embedding(
            document_id=document_id, chunk_text=chunk_text, vector=vector
        )
        self.db.add(db_embedding)
        self.db.commit()
        self.db.refresh(db_embedding)
        return db_embedding

    def get_embeddings_by_document_id(self, document_id: int):
        return (
            self.db.query(schema.Embedding)
            .filter(schema.Embedding.document_id == document_id)
            .all()
        )
