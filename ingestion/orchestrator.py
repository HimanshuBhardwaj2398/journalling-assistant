import os
import sys
import datetime

# Add the project root to the Python path to allow importing from the 'db' package
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db import get_db, DocumentCRUD, init_db
from ingestion.parsing import html_to_markdown, parse_pdf


class IngestionOrchestrator:
    def __init__(self):
        self.db_session = next(get_db())
        self.crud_handler = DocumentCRUD(self.db_session)

    def _extract_title_from_markdown(self, markdown: str) -> str:
        """(Private) Extracts the first H1 header to use as a title."""
        lines = markdown.strip().split("\n")
        for line in lines:
            if line.startswith("# "):
                return line[2:].strip()
        # Fallback to the first non-empty line
        for line in lines:
            if line.strip():
                return (
                    (line.strip()[:75] + "...")
                    if len(line.strip()) > 75
                    else line.strip()
                )
        return "Untitled Document"

    def _generate_metadata(self, markdown: str, source: str) -> dict:
        """(Private) Generates metadata for a document."""
        return {
            "created_at": datetime.datetime.now().isoformat(),
            "word_count": len(markdown.split()),
            "source": source.strip(),  ## Ensure source is stripped of whitespace
        }

    def ingest_source(
        self, source: str, tags: list[str], title: str = None, description: str = None
    ):
        """
        Ingests a source (URL or PDF file path), parses it, and stores it in the database.

        Args:
            source (str): The URL or the absolute file path to the PDF.
            tags (list[str]): A list of tags for the document.
        """
        print(f"--- Starting ingestion for: {source} ---")
        markdown_content = None
        self.source = source

        # 1. Determine source type and parse the content to Markdown
        if source.startswith("http://") or source.startswith("https://"):
            print("Source identified as URL. Parsing HTML...")
            markdown_content = html_to_markdown(source)
        elif source.endswith(".pdf") and os.path.exists(source):
            print("Source identified as PDF. Parsing PDF...")
            markdown_content = parse_pdf(source)
        else:
            print(f"Error: Source type not supported or file not found for '{source}'")
            return

        if not markdown_content:
            print("Parsing failed or returned no content. Aborting ingestion.")
            return

        print(
            f"Parsing successful. Markdown content length: {len(markdown_content)} characters."
        )

        # 2. Get a database session and store the content
        try:
            print("Storing content in the database...")
            title = (
                self._extract_title_from_markdown(markdown_content)
                if not title
                else title
            )
            description = description if description else ""
            doc_metadata = self._generate_metadata(markdown_content, source)
            new_doc = self.crud_handler.create_document(
                title=title,
                markdown=markdown_content,
                tags=tags,
                doc_metadata=doc_metadata,
                description=description,
            )
            print("--- Ingestion successful! ---")
            print(f"  - Document ID: {new_doc.id}")
            print(f"  - Title: {new_doc.title}")
            print(f"  - Tags: {new_doc.tags}")
        except Exception as e:
            print(f"An error occurred during the database operation: {e}")
        finally:
            self.db_session.close()
            print("Database session closed.\n")


if __name__ == "__main__":
    # To run this script, execute `python -m ingestion.orchestrator` from the project root.
    # IMPORTANT:
    # 1. Ensure your .env file is configured with DATABASE_URL and LLAMAPARSE_API.
    # 2. If this is the first time, uncomment the init_db() line to create the tables.

    # --- (Optional) Run this once to initialize the database ---
    print("Initializing database...")
    init_db()
    print("Database initialized.")

    orchestrator = IngestionOrchestrator()

    # --- Example 1: Ingesting an HTML page ---
    html_source = "/Users/himanshu/projects/journalling-assitant/Books/Sutta_In_the_Buddhas_Words_-_An_Anthology_of_Discourses_from_the_Pali_Canon_pdf.pdf"
    html_tags = [
        "buddha's words",
        "buddhism",
        "buddhist texts",
    ]
    description = """
    This document is an anthology of discourses from the Pali Canon, providing insights into the teachings of the Buddha.
    """
    orchestrator.ingest_source(
        html_source,
        html_tags,
        # description=description,
    )

    # # --- Example 2: Ingesting a PDF document ---
    # # PLEASE VERIFY this path is correct for your system.
    # pdf_source = "/Users/himanshu/projects/journalling-assitant/Books/Sutta_In_the_Buddhas_Words_-_An_Anthology_of_Discourses_from_the_Pali_Canon_pdf.pdf"
    # pdf_tags = ["sutta", "buddhism", "pdf", "anthology"]
    # orchestrator.ingest_source(pdf_source, pdf_tags)
