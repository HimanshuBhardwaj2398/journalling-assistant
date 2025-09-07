import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from langchain.schema import Document
from langchain.text_splitter import MarkdownHeaderTextSplitter, MarkdownTextSplitter
from semantic_chunkers import StatisticalChunker
from semantic_router.encoders import HuggingFaceEncoder


# --- Configuration ---


@dataclass
class MarkdownChunkerConfig:
    """Configuration for the MarkdownHeaderChunker."""

    max_chunk_size: int = 2000
    min_chunk_size: int = 500
    max_header_level: int = 6


# --- Main Chunking Logic ---


class MarkdownHeaderChunker:
    """
    Chunks Markdown text using a multi-stage process to preserve semantic structure.

    The chunking process is as follows:
    1.  Recursively split the document by Markdown headers.
    2.  Split any resulting chunks that are still too large using a semantic chunker.
    3.  Combine any chunks that are too small with their neighbors.
    4.  Process and finalize the header metadata for each chunk.
    """

    def __init__(
        self,
        text: str,
        config: Optional[MarkdownChunkerConfig] = None,
        encoder: Optional[Any] = None,
    ):
        self.text = text
        self.config = config or MarkdownChunkerConfig()
        self.encoder = encoder or HuggingFaceEncoder(
            name="sentence-transformers/all-MiniLM-L6-v2"
        )

    async def chunk(self) -> List[Document]:
        """
        Executes the full chunking pipeline.

        Returns:
            A list of processed Document chunks.
        """
        # Stage 1: Split by headers
        header_split_chunks = await self._split_by_headers(self.text)

        # Stage 2: Split oversized chunks semantically
        semantically_split_chunks = await self._split_oversized_chunks(
            header_split_chunks
        )

        # Stage 3: Combine undersized chunks
        combined_chunks = self._combine_undersized_chunks(semantically_split_chunks)

        # Stage 4: Finalize metadata
        final_chunks = self._finalize_chunk_metadata(combined_chunks)

        return final_chunks

    async def _split_by_headers(self, text: str, level: int = 1) -> List[Document]:
        """Recursively splits text based on Markdown header levels."""
        if level > self.config.max_header_level:
            return [Document(page_content=text, metadata={})]

        headers_to_split_on = [
            (f"{{'#' * i}}", f"Header {i}") for i in range(1, level + 1)
        ]
        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on, strip_headers=False
        )

        documents = []
        for doc in splitter.split_text(text):
            if len(doc.page_content) > self.config.max_chunk_size:
                # If chunk is too big, go one level deeper
                sub_chunks = await self._split_by_headers(doc.page_content, level + 1)
                # Propagate parent metadata to children
                for sub_chunk in sub_chunks:
                    sub_chunk.metadata = {**doc.metadata, **sub_chunk.metadata}
                    documents.append(sub_chunk)
            else:
                documents.append(doc)
        return documents

    async def _split_oversized_chunks(self, chunks: List[Document]) -> List[Document]:
        """Identifies and splits chunks that exceed the maximum size."""
        processed_chunks = []
        for chunk in chunks:
            if len(chunk.page_content) > self.config.max_chunk_size:
                split_chunks = await self._split_semantically(chunk)
                processed_chunks.extend(split_chunks)
            else:
                processed_chunks.append(chunk)
        return processed_chunks

    # @observe(name="semantic_chunking")
    async def _split_semantically(self, chunk: Document) -> List[Document]:
        """Performs semantic splitting on a single chunk."""
        try:
            chunker = StatisticalChunker(
                encoder=self.encoder,
                min_split_tokens=self.config.min_chunk_size,
                max_split_tokens=self.config.max_chunk_size,
            )
            semantic_splits = await chunker.acall(docs=[chunk.page_content])

            new_docs = []
            if semantic_splits and semantic_splits[0]:
                for split_group in semantic_splits[0]:
                    content = "".join(split_group.splits).replace("\x00", "").strip()
                    if content:
                        new_docs.append(
                            Document(page_content=content, metadata=chunk.metadata)
                        )
            logging.info("Semantically split one chunk into %d.", len(new_docs))
            return new_docs if new_docs else [chunk]
        except Exception as e:
            logging.error("Semantic splitting failed: %s. Returning original chunk.", e)
            return [chunk]

    def _combine_undersized_chunks(self, chunks: List[Document]) -> List[Document]:
        """Merges adjacent chunks that are smaller than the minimum size."""
        if not chunks:
            return []

        combined = []
        buffer = chunks[0]

        for next_chunk in chunks[1:]:
            if (len(buffer.page_content) < self.config.min_chunk_size) and (
                len(buffer.page_content) + len(next_chunk.page_content)
                <= self.config.max_chunk_size
            ):
                # Merge content and find common metadata
                buffer.page_content += "\n\n" + next_chunk.page_content
                buffer.metadata = self._get_common_metadata(
                    buffer.metadata, next_chunk.metadata
                )
            else:
                combined.append(buffer)
                buffer = next_chunk
        combined.append(buffer)
        return combined

    def _get_common_metadata(self, meta1: Dict, meta2: Dict) -> Dict:
        """Finds the common header hierarchy between two chunks."""
        common_meta = {}
        for key, value in meta1.items():
            if key.startswith("Header ") and meta2.get(key) == value:
                common_meta[key] = value
        return common_meta

    def _finalize_chunk_metadata(self, chunks: List[Document]) -> List[Document]:
        """Processes and sets the final metadata for each chunk."""
        final_chunks = []
        for chunk in chunks:
            parent_headers = self._parse_headers_from_metadata(chunk.metadata)
            header_info = process_markdown_headers(chunk.page_content, parent_headers)
            chunk.metadata = {"chunk_headers": header_info.get("ltree_format", {})}
            final_chunks.append(chunk)
        return final_chunks

    def _parse_headers_from_metadata(
        self,
        metadata: Dict[str, Any],
    ) -> List[Tuple[int, str]]:
        """Extracts header information from a metadata dictionary."""
        headers = []
        for key, value in metadata.items():
            if key.startswith("Header "):
                try:
                    level = int(key.split(" ")[1])
                    headers.append((level, value))
                except (IndexError, ValueError):
                    pass
        return sorted(headers)


# --- End of Chunking Logic ---
