"""
Document parsing with Strategy pattern.

Each parser implements the Parser protocol from core.interfaces.
ParserFactory automatically selects the appropriate parser based on source type.
"""

import logging
import os
import re
import warnings
from typing import Optional

import requests
from dotenv import load_dotenv
from markdownify import markdownify as md

from core.exceptions import ConfigurationError, ParsingError
from core.interfaces import Parser, ParseResult
from ingestion.suttacentral import SuttaCentralParser

logger = logging.getLogger(__name__)

# Load environment variables from the project's .env file
dotenv_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=dotenv_path)


# ============================================================================
# CONCRETE PARSER IMPLEMENTATIONS
# ============================================================================


class URLParser:
    """Parser for web URLs using requests + markdownify."""

    URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)

    def can_parse(self, source: str) -> bool:
        """Check if source is a valid HTTP/HTTPS URL."""
        return bool(self.URL_PATTERN.match(source))

    def parse(self, source: str) -> ParseResult:
        """
        Fetch URL and convert HTML to markdown.

        Args:
            source: HTTP or HTTPS URL

        Returns:
            ParseResult with markdown content

        Raises:
            ParsingError: If fetch or conversion fails
        """
        try:
            logger.info(f"Parsing URL: {source}")
            response = requests.get(source, timeout=30)
            response.raise_for_status()

            html_content = response.text
            markdown_text = md(html_content, heading_style="ATX")

            if not markdown_text or not markdown_text.strip():
                raise ParsingError(f"URL parsing resulted in empty content: {source}")

            # Extract title from first H1
            title = self._extract_title(markdown_text)

            logger.info(f"Successfully parsed URL: {source}")
            return ParseResult(
                content=markdown_text,
                title=title,
                metadata={
                    "source_url": source,
                    "content_type": response.headers.get("content-type"),
                    "status_code": response.status_code,
                },
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch URL {source}: {e}")
            raise ParsingError(f"Failed to fetch URL {source}: {e}") from e
        except Exception as e:
            logger.error(f"URL parsing failed for {source}: {e}")
            raise ParsingError(f"URL parsing failed for {source}: {e}") from e

    def _extract_title(self, markdown: str) -> Optional[str]:
        """Extract title from first H1 header."""
        for line in markdown.split("\n")[:20]:
            match = re.match(r"^#\s+(.+)$", line.strip())
            if match:
                return match.group(1).strip()
        return None


class PDFParser:
    """Parser for PDF files using LlamaParse."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize PDF parser with LlamaParse API key.

        Args:
            api_key: LlamaParse API key (defaults to env var LLAMAPARSE_API)

        Raises:
            ConfigurationError: If API key is not provided or found in environment
        """
        self.api_key = api_key or os.environ.get("LLAMAPARSE_API")
        if not self.api_key:
            raise ConfigurationError(
                "LLAMAPARSE_API key required for PDF parsing. "
                "Set LLAMAPARSE_API environment variable or pass api_key parameter."
            )

    def can_parse(self, source: str) -> bool:
        """Check if source is a PDF file."""
        return source.lower().endswith(".pdf")

    def parse(self, source: str) -> ParseResult:
        """
        Parse PDF file using LlamaParse.

        Args:
            source: Path to PDF file

        Returns:
            ParseResult with markdown content

        Raises:
            ParsingError: If PDF parsing fails or file not found
        """
        if not os.path.exists(source):
            raise ParsingError(f"PDF file not found: {source}")

        try:
            # Lazy import: LlamaParse pulls a heavy (and currently fragile) dependency
            # chain, so it must not be imported unless a PDF is actually being parsed.
            from llama_cloud_services import LlamaParse

            logger.info(f"Parsing PDF: {source}")

            parser = LlamaParse(
                api_key=self.api_key,
                parse_mode="parse_page_with_llm",
                high_res_ocr=True,
                adaptive_long_table=True,
                outlined_table_extraction=True,
                output_tables_as_HTML=True,
            )

            result = parser.parse(source)
            markdown_documents = result.get_markdown_documents(split_by_page=True)
            full_markdown = "\n".join(doc.text for doc in markdown_documents)

            if not full_markdown or not full_markdown.strip():
                raise ParsingError(f"PDF parsing resulted in empty content: {source}")

            title = self._extract_title(full_markdown)

            logger.info(f"Successfully parsed PDF: {source} ({len(markdown_documents)} pages)")
            return ParseResult(
                content=full_markdown,
                title=title,
                metadata={"source_file": source, "page_count": len(markdown_documents)},
            )

        except Exception as e:
            logger.error(f"PDF parsing failed for {source}: {e}")
            raise ParsingError(f"PDF parsing failed for {source}: {e}") from e

    def _extract_title(self, markdown: str) -> Optional[str]:
        """Extract title from first H1 header."""
        for line in markdown.split("\n")[:20]:
            match = re.match(r"^#\s+(.+)$", line.strip())
            if match:
                return match.group(1).strip()
        return None


# ============================================================================
# PARSER FACTORY
# ============================================================================


class ParserFactory:
    """
    Factory for creating appropriate parser based on source type.

    Automatically selects parser using can_parse() checks.
    Parsers are tried in order until one matches.
    """

    def __init__(self, llamaparse_api_key: Optional[str] = None):
        """
        Initialize factory with available parsers.

        Args:
            llamaparse_api_key: API key for PDF parsing (optional, uses env var if not provided)
        """
        self._parsers = [
            SuttaCentralParser(),
            URLParser(),
        ]

        # Only add PDF parser if API key is available
        try:
            self._parsers.append(PDFParser(api_key=llamaparse_api_key))
            logger.debug("PDF parser initialized successfully")
        except ConfigurationError as e:
            logger.warning(f"PDF parser not available: {e}")

    def get_parser(self, source: str) -> Parser:
        """
        Get appropriate parser for source.

        Args:
            source: File path or URL

        Returns:
            Parser instance that can handle this source

        Raises:
            ParsingError: If no parser can handle this source
        """
        for parser in self._parsers:
            if parser.can_parse(source):
                logger.debug(f"Selected {parser.__class__.__name__} for source: {source}")
                return parser

        raise ParsingError(
            f"No parser available for source: {source}. "
            f"Supported types: HTTP/HTTPS URLs, PDF files (.pdf)"
        )

    def parse(self, source: str) -> ParseResult:
        """
        Convenience method: automatically select parser and parse source.

        Args:
            source: File path or URL

        Returns:
            ParseResult with content and metadata

        Raises:
            ParsingError: If no parser found or parsing fails
        """
        parser = self.get_parser(source)
        return parser.parse(source)


# ============================================================================
# BACKWARD COMPATIBILITY (DEPRECATED)
# ============================================================================


def html_to_markdown(url: str) -> str | None:
    """
    Convert HTML content from a given URL to Markdown format.

    **DEPRECATED**: Use ParserFactory.parse() instead.

    Args:
        url: HTTP or HTTPS URL

    Returns:
        Markdown string or None if parsing fails

    Example (new API):
        factory = ParserFactory()
        result = factory.parse("https://example.com")
        markdown = result.content
    """
    warnings.warn(
        "html_to_markdown() is deprecated. Use ParserFactory.parse() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        result = URLParser().parse(url)
        return result.content
    except ParsingError as e:
        logger.error(f"html_to_markdown failed: {e}")
        return None


def parse_pdf(file_path: str) -> str | None:
    """
    Parse a PDF file using LlamaParse and return its content as markdown.

    **DEPRECATED**: Use ParserFactory.parse() instead.

    Args:
        file_path: Path to PDF file

    Returns:
        Markdown string or None if parsing fails

    Example (new API):
        factory = ParserFactory()
        result = factory.parse("document.pdf")
        markdown = result.content
    """
    warnings.warn(
        "parse_pdf() is deprecated. Use ParserFactory.parse() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        result = PDFParser().parse(file_path)
        return result.content
    except (ParsingError, ConfigurationError) as e:
        logger.error(f"parse_pdf failed: {e}")
        return None
