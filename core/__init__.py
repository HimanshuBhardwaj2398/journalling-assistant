"""
Core foundational modules for the meditation database.

This package contains central abstractions, exceptions, and interfaces
used throughout the application.
"""

from .exceptions import (
    ChunkingError,
    ConfigurationError,
    DatabaseError,
    DocumentNotFoundError,
    EmbeddingError,
    MeditationDBError,
    ParsingError,
    PipelineError,
    SchemaValidationError,
)
from .interfaces import (
    Parser,
    ParseResult,
    PipelineContext,
    PipelineStage,
    StageStatus,
)

__all__ = [
    # Exceptions
    "MeditationDBError",
    "ConfigurationError",
    "PipelineError",
    "ParsingError",
    "ChunkingError",
    "EmbeddingError",
    "DatabaseError",
    "DocumentNotFoundError",
    "SchemaValidationError",
    # Interfaces
    "ParseResult",
    "Parser",
    "StageStatus",
    "PipelineContext",
    "PipelineStage",
]
