import os

os.chdir("/Users/himanshu/projects/journalling-assitant")
import sys

sys.path.append(os.getcwd())
import logging
from typing import Union, List, Dict, Any, Optional
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine
import re
import asyncio

# Import from your existing files
from db import Document, DocumentStatus, session_scope
from ingestion import html_to_markdown, parse_pdf
from ingestion import MarkdownChunker, Config as ChunkingConfig
from ingestion import VectorStoreManager, VectorStoreConfig

# from database import session_scope

# LangChain's Document class for type hinting
from langchain.schema import Document as LangchainDocument

# --- Logging Configuration ---
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


# --- Helper Functions for Serialization ---
def serialize_docs(docs: List[LangchainDocument]) -> List[Dict[str, Any]]:
    """Converts a list of Langchain Documents to a JSON-serializable format."""
    return [
        {"page_content": doc.page_content, "metadata": doc.metadata} for doc in docs
    ]


def deserialize_docs(serialized_docs: List[Dict[str, Any]]) -> List[LangchainDocument]:
    """Converts a list of serialized documents back into Langchain Document objects."""
    return [
        LangchainDocument(page_content=doc["page_content"], metadata=doc["metadata"])
        for doc in serialized_docs
    ]


class IngestionOrchestrator:
    """
    Orchestrates the document ingestion pipeline: parsing, chunking, and embedding.
    It acts as a state machine, processing documents based on their current status.
    """

    def __init__(
        self,
        vector_store_config: VectorStoreConfig,
        chunking_config: Optional[ChunkingConfig] = None,
    ):
        self.vector_store_manager = VectorStoreManager(config=vector_store_config)
        self.chunking_config = chunking_config
        logging.info("Orchestrator initialized.")

    async def process(self, source: Union[str, int]) -> int:
        """
        Main entry point to process a document.
        Returns the document ID instead of the detached instance.
        """
        with session_scope() as db:
            doc = self._get_or_create_document(source, db)
            doc_id = doc.id  # Get the ID while session is active

            try:
                await self._run_pipeline(doc, db)
                return doc_id
            except Exception as e:
                logging.error(
                    f"Critical error in pipeline for doc {doc.id}: {e}", exc_info=True
                )
                self._update_status(doc, DocumentStatus.FAILED, str(e), db)
                raise

    def _get_or_create_document(self, source: Union[str, int], db: Session) -> Document:
        """
        Retrieves a document from the DB if an ID is provided,
        or creates a new one if a file path is provided.
        """
        if isinstance(source, int):
            logging.info(f"Resuming processing for document ID: {source}")
            doc = db.query(Document).filter(Document.id == source).first()
            if not doc:
                raise ValueError(f"No document found with ID {source}")
            return doc
        elif isinstance(source, str):
            logging.info(f"Starting new ingestion for source: {source}")
            doc = Document(file_path=source, status=DocumentStatus.PENDING)
            db.add(doc)
            db.commit()
            db.refresh(doc)
            return doc
        else:
            raise TypeError(
                "Source must be either a string (file path/URL) or an integer (document ID)"
            )

    async def _run_pipeline(self, doc: Document, db: Session) -> None:
        """
        Executes the ingestion pipeline steps based on the document's current status.
        """
        logging.info(
            f"Running pipeline for doc {doc.id} with status: {doc.status.value}"
        )

        # --- PARSING STAGE ---
        if doc.status in [DocumentStatus.PENDING, DocumentStatus.PARSING]:
            self._parse(doc, db)

        # --- CHUNKING STAGE ---
        if doc.status == DocumentStatus.PARSED:
            await self._chunk(doc, db)

        # --- EMBEDDING STAGE ---
        if doc.status == DocumentStatus.CHUNKED:
            self._embed(doc, db)

        if doc.status == DocumentStatus.COMPLETED:
            logging.info(f"Document {doc.id} has already been processed successfully.")

    def _update_status(
        self,
        doc: Document,
        status: DocumentStatus,
        details: Optional[str] = None,
        db: Session = None,
    ):
        """Safely updates the document's status in the database."""
        doc.status = status
        doc.status_details = details
        if db:
            db.commit()
        logging.info(f"Updated doc {doc.id} status to: {status.value}")

    def _parse(self, doc: Document, db: Session):
        """Step 1: Parse the document from its source file path."""
        self._update_status(doc, DocumentStatus.PARSING, db=db)
        try:
            content = None
            if re.match(r"^https?://", doc.file_path, re.IGNORECASE):
                logging.info(f"Parsing URL: {doc.file_path}")
                content = html_to_markdown(doc.file_path)
            elif doc.file_path.lower().endswith(".pdf"):
                logging.info(f"Parsing PDF: {doc.file_path}")
                content = parse_pdf(doc.file_path)
            else:
                raise ValueError(f"Unsupported file type for: {doc.file_path}")

            if not content:
                raise ValueError("Parsing resulted in empty content.")

            doc.markdown = content
            # Simple title extraction from the first H1 tag
            match = re.search(r"^#\s+(.+)$", content.strip(), re.MULTILINE)
            if match:
                doc.title = match.group(1).strip()

            self._update_status(doc, DocumentStatus.PARSED, db=db)
        except Exception as e:
            logging.error(f"Parsing failed for doc {doc.id}: {e}", exc_info=True)
            self._update_status(
                doc, DocumentStatus.FAILED, f"Parsing failed: {e}", db=db
            )
            raise

    async def _chunk(self, doc: Document, db: Session):
        """Step 2: Chunk the parsed markdown content."""
        if not doc.markdown:
            raise ValueError(f"Cannot chunk doc {doc.id}, markdown content is missing.")

        self._update_status(doc, DocumentStatus.CHUNKING, db=db)
        try:
            chunker = MarkdownChunker(
                text=doc.markdown, config=self.chunking_config, title=doc.title
            )

            chunks, stats = await chunker.chunk()
            logging.info(f"Chunking stats for doc {doc.id}: {stats}")

            doc.chunks = serialize_docs(chunks)
            self._update_status(doc, DocumentStatus.CHUNKED, db=db)
        except Exception as e:
            logging.error(f"Chunking failed for doc {doc.id}: {e}", exc_info=True)
            self._update_status(
                doc, DocumentStatus.FAILED, f"Chunking failed: {e}", db=db
            )
            raise

    def _embed(self, doc: Document, db: Session):
        """Step 3: Embed the chunks and store them in the vector database."""
        if not doc.chunks:
            raise ValueError(f"Cannot embed doc {doc.id}, chunks are missing.")

        self._update_status(doc, DocumentStatus.EMBEDDING, db=db)
        try:
            langchain_docs = deserialize_docs(doc.chunks)

            # Add document ID to each chunk's metadata for traceability
            for chunk in langchain_docs:
                chunk.metadata["original_doc_id"] = doc.id
                chunk.metadata["original_doc_title"] = doc.title

            vector_ids = self.vector_store_manager.embed_documents(langchain_docs)

            if len(vector_ids) != len(langchain_docs):
                logging.warning(
                    f"Mismatch in embedded docs for doc {doc.id}. Expected {len(langchain_docs)}, got {len(vector_ids)}"
                )

            self._update_status(
                doc,
                DocumentStatus.COMPLETED,
                f"Successfully embedded {len(vector_ids)} chunks.",
                db=db,
            )
        except Exception as e:
            logging.error(f"Embedding failed for doc {doc.id}: {e}", exc_info=True)
            self._update_status(
                doc, DocumentStatus.FAILED, f"Embedding failed: {e}", db=db
            )
            raise


if __name__ == "__main__":
    # To run this script, execute `python -m ingestion.orchestrator` from the project root.
    # IMPORTANT:
    # 1. Ensure your .env file is configured with DATABASE_URL and LLAMAPARSE_API.
    # 2. If this is the first time, uncomment the init_db() line to create the tables.

    # --- (Optional) Run this once to initialize the database ---
    print("Initializing database...")
    from db.database import init_db

    init_db()
    print("Database initialized.")

    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(
            collection_name="documents",
            connection_string=os.getenv("DATABASE_URL"),
        )
    )
    # Example usage
    source = 2
    # tags = ["example", "test"]
    asyncio.run(orchestrator.process(source))
