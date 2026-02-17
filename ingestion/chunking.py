import asyncio
import logging
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from langchain.schema import Document
from langchain.text_splitter import MarkdownHeaderTextSplitter
from langchain_experimental.text_splitter import SemanticChunker
from langchain_community.embeddings import HuggingFaceEmbeddings

from core.exceptions import ChunkingError

logger = logging.getLogger(__name__)


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


# ============================================================================
# THREAD-SAFE EMBEDDINGS CACHE
# ============================================================================

class ThreadSafeEmbeddingsCache:
    """
    Thread-safe singleton cache for embedding models.

    Uses double-checked locking pattern for thread safety.
    Each model has its own lock to allow concurrent loading of different models.
    """

    _instance: Optional["ThreadSafeEmbeddingsCache"] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        """
        Singleton pattern with thread-safe initialization.

        Uses double-checked locking for performance.
        """
        if cls._instance is None:
            with cls._instance_lock:
                # Double-check inside lock
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._cache: Dict[str, HuggingFaceEmbeddings] = {}
                    instance._model_locks: Dict[str, threading.Lock] = {}
                    instance._locks_lock = threading.Lock()  # Lock for managing locks dict
                    cls._instance = instance
        return cls._instance

    def _get_model_lock(self, model_name: str) -> threading.Lock:
        """Get or create lock for specific model (thread-safe)."""
        with self._locks_lock:
            if model_name not in self._model_locks:
                self._model_locks[model_name] = threading.Lock()
            return self._model_locks[model_name]

    def get_embeddings(self, model_name: str) -> HuggingFaceEmbeddings:
        """
        Get or create embeddings model with thread-safe access.

        Args:
            model_name: HuggingFace model identifier

        Returns:
            Cached or newly created embeddings model

        Raises:
            ChunkingError: If model loading fails
        """
        # Fast path: model already cached (no lock needed for read)
        if model_name in self._cache:
            logger.debug(f"Using cached embeddings model: {model_name}")
            return self._cache[model_name]

        # Slow path: need to load model (acquire model-specific lock)
        model_lock = self._get_model_lock(model_name)
        with model_lock:
            # Double-check inside lock (another thread might have loaded it)
            if model_name in self._cache:
                logger.debug(f"Model loaded by another thread: {model_name}")
                return self._cache[model_name]

            # Load model
            try:
                logger.info(f"Loading embeddings model: {model_name}")
                start_time = time.time()

                embeddings = HuggingFaceEmbeddings(model_name=model_name)

                load_time = time.time() - start_time
                logger.info(f"Loaded {model_name} in {load_time:.2f}s")

                # Cache it
                self._cache[model_name] = embeddings
                return embeddings

            except Exception as e:
                logger.error(f"Failed to load embeddings model {model_name}: {e}")
                raise ChunkingError(f"Failed to load embeddings model: {e}") from e

    def clear_cache(self):
        """Clear all cached models (for testing or memory management)."""
        with self._instance_lock:
            self._cache.clear()
            logger.info("Cleared embeddings cache")

    def get_cache_info(self) -> Dict[str, Any]:
        """Get information about cached models."""
        return {
            "cached_models": list(self._cache.keys()),
            "cache_size": len(self._cache)
        }


# ============================================================================
# MARKDOWN CHUNKER
# ============================================================================

class MarkdownChunker:
    """
    Production Markdown document chunker.

    Uses thread-safe singleton cache for embeddings models.
    """

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
        """Get embeddings model from thread-safe cache."""
        cache = ThreadSafeEmbeddingsCache()
        return cache.get_embeddings(self.config.model)

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

        Merges freely across section boundaries. All unique header sets
        are accumulated in 'all_headers' metadata so the TOC builder
        can recover every section heading.

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

            # If a chunk is tiny, merge with next chunk.
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
                chunk_index += 2
                continue

            # If the current chunk is large enough, add it and move on.
            if current_chunk_size >= self.config.min_size:
                merged_chunks.append(current_chunk)
                chunk_index += 1
                continue

            # Start combining other small chunks.
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

    def _extract_header_set(self, metadata: Dict) -> Dict[str, str]:
        """Extract just the Header N keys from metadata as a dict."""
        return {k: v for k, v in metadata.items() if k.startswith("Header ")}

    def _build_header_path(self, header_dict: Dict[str, str]) -> Tuple[str, Dict[str, int]]:
        """Build a header path string and level map from a Header N dict.

        Args:
            header_dict: Dict like {"Header 1": "Title", "Header 3": "Section"}

        Returns:
            Tuple of (path_string, level_map):
                path_string: "Title > Section"
                level_map: {"Title": 1, "Section": 3}
        """
        levels = {}
        for key, value in header_dict.items():
            if key.startswith("Header "):
                level = int(key.split()[1])
                levels[level] = value

        if not levels:
            return "", {}

        sorted_levels = sorted(levels.keys())
        path_parts = [levels[l] for l in sorted_levels]
        level_map = {levels[l]: l for l in sorted_levels}

        return " > ".join(path_parts), level_map

    def _merge_metadata(self, meta1: Dict, meta2: Dict) -> Dict:
        """
        Merge metadata from two chunks, accumulating all unique header sets.

        Keeps meta1's Header N keys as the primary headers and collects
        every unique header combination into 'all_headers' so the TOC
        builder can recover all section headings even after merging.
        """
        merged = meta1.copy()

        # Collect all unique header sets from both sides
        existing_headers = list(meta1.get("all_headers", []))
        if not existing_headers:
            h1 = self._extract_header_set(meta1)
            if h1:
                existing_headers.append(h1)

        incoming_headers = list(meta2.get("all_headers", []))
        if not incoming_headers:
            h2 = self._extract_header_set(meta2)
            if h2:
                incoming_headers.append(h2)

        for h_set in incoming_headers:
            if h_set not in existing_headers:
                existing_headers.append(h_set)

        if existing_headers:
            merged["all_headers"] = existing_headers

        # Add non-header metadata from meta2 that isn't already present
        for k, v in meta2.items():
            if not k.startswith("Header ") and k != "all_headers" and k not in merged:
                merged[k] = v

        return merged

    def _add_final_metadata(self, chunks: List[Document]) -> List[Document]:
        """Transform chunk metadata to final format with header paths.

        Converts internal Header N keys and all_headers lists into the
        clean output format: all_header_paths (list of delimited strings)
        and header_level_map (dict of header text to level).

        Removes all intermediate metadata fields (Header N, all_headers,
        chunk_index, primary_header, header_level, section_path).
        """
        for chunk in chunks:
            # Collect header dicts from all_headers (combined) or Header N keys
            all_headers = chunk.metadata.get("all_headers", [])
            if not all_headers:
                header_set = self._extract_header_set(chunk.metadata)
                if header_set:
                    all_headers = [header_set]

            # Build paths and level map
            all_paths = []
            level_map = {}
            for h_dict in all_headers:
                path, lmap = self._build_header_path(h_dict)
                if path and path not in all_paths:
                    all_paths.append(path)
                level_map.update(lmap)

            # Remove old keys
            keys_to_remove = [k for k in chunk.metadata if k.startswith("Header ")]
            keys_to_remove.extend([
                "all_headers", "primary_header", "header_level",
                "section_path", "chunk_index",
            ])
            for key in keys_to_remove:
                chunk.metadata.pop(key, None)

            # Set new metadata
            chunk.metadata["all_header_paths"] = all_paths
            chunk.metadata["header_level_map"] = level_map
            chunk.metadata["doc_title"] = self.title
            chunk.metadata["word_count"] = len(chunk.page_content.split())
            chunk.metadata["char_count"] = len(chunk.page_content)

        return chunks
