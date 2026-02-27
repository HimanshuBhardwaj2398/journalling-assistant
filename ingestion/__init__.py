"""
Ingestion package for document processing pipeline.

Provides both legacy API (deprecated) and new DAG-based pipeline API.
"""

# ============================================================================
# BACKWARD COMPATIBLE EXPORTS (keep for existing code)
# ============================================================================

from .chunking import Config as ChunkingConfig

# Chunking
from .chunking import MarkdownChunker, ThreadSafeEmbeddingsCache
from .embed import VectorStoreConfig, VectorStoreManager

# Orchestration
from .orchestrator import (
    IngestionOrchestrator,
    PipelineOrchestrator,
    deserialize_docs,
    serialize_docs,
)

# ============================================================================
# NEW API EXPORTS (Sprint 2 refactoring)
# ============================================================================
# Parsing
from .parsing import ParserFactory, PDFParser, URLParser, html_to_markdown, parse_pdf  # Deprecated

# Pipeline Stages
from .stages import ChunkingStage, EmbeddingStage, ParsingStage

# ============================================================================
# PUBLIC API
# ============================================================================

__all__ = [
    # ===== BACKWARD COMPATIBLE API =====
    # Chunking
    "MarkdownChunker",
    "ChunkingConfig",
    # Embedding
    "VectorStoreConfig",
    "VectorStoreManager",
    # Orchestration
    "IngestionOrchestrator",
    # Parsing (deprecated - use ParserFactory instead)
    "html_to_markdown",
    "parse_pdf",
    # ===== NEW API (Sprint 2) =====
    # Parsing
    "ParserFactory",
    "URLParser",
    "PDFParser",
    # Chunking
    "ThreadSafeEmbeddingsCache",
    # Orchestration
    "PipelineOrchestrator",
    "serialize_docs",
    "deserialize_docs",
    # Pipeline Stages
    "ParsingStage",
    "ChunkingStage",
    "EmbeddingStage",
]
