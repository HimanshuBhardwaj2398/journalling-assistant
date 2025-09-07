from sqlalchemy.orm import Session
from . import schema


class DocumentCRUD:
    def __init__(self, db: Session):
        self.db = db

    def create_document(self, title: str, markdown: str, tags: list[str] = None, doc_metadata: dict = None, description: str = None):
        """
        Creates a new document and stores it in the database.
        """
        db_document = schema.Document(
            title=title, markdown=markdown, tags=tags, doc_metadata=doc_metadata, description=description
        )
        self.db.add(db_document)
        self.db.commit()
        self.db.refresh(db_document)
        return db_document

    def get_document(self, document_id: int):
        return (
            self.db.query(schema.Document)
            .filter(schema.Document.id == document_id)
            .first()
        )

    def get_all_documents(self):
        return self.db.query(schema.Document).all()