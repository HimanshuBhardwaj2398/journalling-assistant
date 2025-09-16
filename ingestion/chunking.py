import asyncio
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from langchain.schema import Document
from langchain.text_splitter import MarkdownHeaderTextSplitter
from langchain_experimental.text_splitter import SemanticChunker
from langchain_community.embeddings import HuggingFaceEmbeddings

logger = logging.getLogger(__name__)


class ChunkingError(Exception):
    """Chunking operation failed."""

    pass


@dataclass
class Config:
    """Chunker configuration."""

    max_size: int = 2000
    min_size: int = 700
    max_header_level: int = 6
    enable_semantic: bool = True
    enable_parallel: bool = True
    max_workers: int = 4
    tiny_chunk_threshold: int = 50
    # model: str = "sentence-transformers/all-MiniLM-L6-v2"
    model: str = "BAAI/bge-small-en-v1.5"

    def __post_init__(self):
        if self.max_size <= self.min_size:
            raise ValueError("max_size must be greater than min_size")


@dataclass
class ChunkingStats:
    """Processing statistics."""

    total_chunks: int = 0
    processing_time: float = 0.0
    avg_chunk_size: float = 0.0


class MarkdownChunker:
    """Production Markdown document chunker."""

    _embeddings_cache: Dict[str, Any] = {}

    def __init__(
        self,
        text: str,
        config: Optional[Config] = None,
        title: Optional[str] = None,
    ):
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        self.text = text.strip()
        self.config = config or Config()
        self.title = title or self._extract_title()
        self.embeddings = (
            self._get_embeddings() if self.config.enable_semantic else None
        )

    def _get_embeddings(self) -> Any:
        """Get cached embeddings model."""
        model = self.config.model
        if model not in self._embeddings_cache:
            try:
                self._embeddings_cache[model] = HuggingFaceEmbeddings(model_name=model)
            except Exception as e:
                raise ChunkingError(f"Failed to load embeddings: {e}")
        return self._embeddings_cache[model]

    def _extract_title(self) -> str:
        """Extract title from first H1 header."""
        for line in self.text.split("\n")[:10]:
            match = re.match(r"^#\s+(.+)$", line.strip())
            if match:
                return match.group(1).strip()
        return "Untitled"

    def _extract_headers(self, text: str) -> Dict[str, str]:
        """Extract current header context from text."""
        headers = {}
        current_headers = [None] * 7  # levels 0-6

        for match in re.finditer(r"^(#{1,6})\s+(.+)$", text, re.MULTILINE):
            level = len(match.group(1))
            header = match.group(2).strip()
            current_headers[level] = header
            # Clear deeper levels
            for i in range(level + 1, 7):
                current_headers[i] = None

        for level in range(1, 7):
            if current_headers[level]:
                headers[f"Header {level}"] = current_headers[level]

        return headers

    async def chunk(self) -> Tuple[List[Document], ChunkingStats]:
        """Execute chunking pipeline."""
        start_time = time.time()

        try:
            # Step 1: Split by headers
            chunks = await self._split_by_headers()

            logger.info(f"Initial split by headers: {len(chunks)} chunks created.")

            # Step 2: Split oversized chunks semantically (if enabled)
            if self.config.enable_semantic:
                chunks = await self._split_oversized_chunks(chunks)

            logger.info(f"After semantic splitting: {len(chunks)} chunks created.")

            # Step 3: Combine small adjacent chunks
            chunks = self._combine_small_chunks(chunks)

            logger.info(f"After combining small chunks: {len(chunks)} chunks created.")

            # Step 4: Finalize metadata
            chunks = self._add_final_metadata(chunks)

            # Calculate stats
            processing_time = time.time() - start_time
            total_words = sum(len(c.page_content.split()) for c in chunks)
            stats = ChunkingStats(
                total_chunks=len(chunks),
                processing_time=processing_time,
                avg_chunk_size=total_words / len(chunks) if chunks else 0,
            )

            logger.info(
                f"Chunking completed: {len(chunks)} chunks in {processing_time:.2f}s"
            )
            return chunks, stats

        except Exception as e:
            logger.error(f"Chunking failed: {e}")
            raise ChunkingError(f"Pipeline failed: {e}")

    async def _split_by_headers(self) -> List[Document]:
        """Split text by markdown headers."""
        headers_to_split = [
            (f"{'#' * i}", f"Header {i}")
            for i in range(1, self.config.max_header_level + 1)
        ]

        try:
            splitter = MarkdownHeaderTextSplitter(
                headers_to_split_on=headers_to_split, strip_headers=False
            )
            docs = splitter.split_text(self.text)

            # Ensure all docs have metadata (don't filter here, let combine step handle tiny chunks)
            for doc in docs:
                if not doc.metadata:
                    doc.metadata = self._extract_headers(doc.page_content)

            return docs

        except Exception as e:
            logger.warning(f"Header splitting failed: {e}")
            # Fallback to single document
            return [
                Document(
                    page_content=self.text, metadata=self._extract_headers(self.text)
                )
            ]

    async def _split_oversized_chunks(self, chunks: List[Document]) -> List[Document]:
        """Split chunks that exceed max_size using semantic splitting."""
        oversized = [c for c in chunks if len(c.page_content) > self.config.max_size]
        normal = [c for c in chunks if len(c.page_content) <= self.config.max_size]

        if not oversized:
            return chunks

        if self.config.enable_parallel and len(oversized) > 1:
            # Process oversized chunks in parallel
            loop = asyncio.get_event_loop()
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                tasks = [
                    loop.run_in_executor(executor, self._semantic_split, chunk)
                    for chunk in oversized
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            # Collect results
            processed = normal.copy()
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Semantic split failed for chunk {i}: {result}")
                    processed.append(oversized[i])
                else:
                    processed.extend(result)
            return processed
        else:
            # Process sequentially
            result = normal.copy()
            for chunk in oversized:
                result.extend(self._semantic_split(chunk))
            return result

    def _semantic_split(self, chunk: Document) -> List[Document]:
        """Split a single chunk using semantic chunking."""
        try:
            if not self.embeddings:
                return [chunk]

            splitter = SemanticChunker(
                self.embeddings, breakpoint_threshold_type="percentile"
            )
            docs = splitter.create_documents([chunk.page_content])

            # Preserve original metadata
            for doc in docs:
                doc.metadata.update(chunk.metadata)
                doc.metadata["is_semantic_split"] = True

            return docs if len(docs) > 1 else [chunk]

        except Exception as e:
            logger.warning(f"Semantic split failed: {e}")
            return [chunk]

    def _combine_small_chunks(self, chunks: List[Document]) -> List[Document]:
        """
        Combines adjacent small text chunks into larger ones.

        This method has a special rule for "tiny" chunks (less than 20
        characters): they are unconditionally merged with the following chunk,
        ignoring other size constraints for that single merge.

        For other chunks smaller than `self.config.min_size`, it merges them
        with subsequent neighbors until the combined chunk's size is at least
        `self.config.min_size` or until adding the next chunk would exceed
        `self.config.max_size`.

        Args:
            chunks: A list of Document objects to process.

        Returns:
            A new list of Document objects with small chunks merged.
        """
        if not chunks:
            return []

        merged_chunks: List[Document] = []
        chunk_index = 0
        TINY_CHUNK_THRESHOLD = self.config.tiny_chunk_threshold

        while chunk_index < len(chunks):
            current_chunk = chunks[chunk_index]
            current_chunk_size = len(current_chunk.page_content.split())

            # If a chunk is tiny, unconditionally merge it with the next one.
            if current_chunk_size < TINY_CHUNK_THRESHOLD and (chunk_index + 1) < len(
                chunks
            ):
                next_chunk = chunks[chunk_index + 1]

                merged_content = "\n\n".join(
                    [current_chunk.page_content, next_chunk.page_content]
                )
                merged_metadata = self._merge_metadata(
                    current_chunk.metadata.copy(), next_chunk.metadata
                )
                merged_metadata["is_combined"] = True

                new_chunk = Document(
                    page_content=merged_content, metadata=merged_metadata
                )
                merged_chunks.append(new_chunk)

                # Advance index past the two chunks we just merged
                chunk_index += 2
                continue

            # If the current chunk is large enough, add it and move on.
            if current_chunk_size >= self.config.min_size:
                merged_chunks.append(current_chunk)
                chunk_index += 1
                continue

            # Start combining other small chunks that are not "tiny".
            content_parts = [current_chunk.page_content]
            combined_metadata = current_chunk.metadata.copy()
            combined_size = current_chunk_size

            next_chunk_index = chunk_index + 1

            while next_chunk_index < len(chunks):
                next_chunk = chunks[next_chunk_index]

                if combined_size + len(next_chunk.page_content) > self.config.max_size:
                    break

                content_parts.append(next_chunk.page_content)
                combined_metadata = self._merge_metadata(
                    combined_metadata, next_chunk.metadata
                )
                combined_size += len(next_chunk.page_content)
                next_chunk_index += 1

                if combined_size >= self.config.min_size:
                    break

            merged_content = "\n\n".join(content_parts)
            new_chunk = Document(
                page_content=merged_content, metadata=combined_metadata
            )

            if next_chunk_index > chunk_index + 1:
                new_chunk.metadata["is_combined"] = True

            merged_chunks.append(new_chunk)
            chunk_index = next_chunk_index

        return merged_chunks

    def _merge_metadata(self, meta1: Dict, meta2: Dict) -> Dict:
        """Merge metadata from two chunks, keeping common headers."""
        merged = {k: v for k, v in meta1.items() if not k.startswith("Header ")}

        # Keep only headers that are the same in both chunks
        for key, value in meta1.items():
            if key.startswith("Header ") and meta2.get(key) == value:
                merged[key] = value

        return merged

    def _add_final_metadata(self, chunks: List[Document]) -> List[Document]:
        """Add final metadata to all chunks."""
        for i, chunk in enumerate(chunks):
            # Get header hierarchy
            header_keys = sorted(
                [k for k in chunk.metadata.keys() if k.startswith("Header ")],
                key=lambda k: int(k.split()[1]),
            )
            header_trail = [chunk.metadata[k] for k in header_keys]

            # Update metadata
            chunk.metadata.update(
                {
                    "chunk_index": i,
                    "doc_title": self.title,
                    "word_count": len(chunk.page_content.split()),
                    "char_count": len(chunk.page_content),
                    "primary_header": header_trail[-1] if header_trail else None,
                    "header_level": len(header_trail),
                    "section_path": " > ".join([self.title] + header_trail),
                }
            )

        return chunks
