"""
Core interfaces and protocols for the meditation database.

This module defines abstract interfaces using Protocol (structural typing)
and ABC (abstract base classes) for key components of the ingestion pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from langchain.schema import Document as LangchainDocument

# ============================================================================
# PARSING INTERFACES
# ============================================================================


@dataclass
class ParseResult:
    """
    Result of a parsing operation.

    Attributes:
        content: Parsed markdown content
        title: Extracted document title (optional)
        metadata: Additional metadata extracted during parsing
    """

    content: str
    title: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class Parser(Protocol):
    """
    Protocol for document parsers.

    Parsers must implement can_parse() and parse() methods.
    Uses Protocol for structural typing (duck typing with type hints).
    """

    def can_parse(self, source: str) -> bool:
        """
        Check if this parser can handle the given source.

        Args:
            source: File path or URL

        Returns:
            True if parser can handle this source type
        """
        ...

    def parse(self, source: str) -> ParseResult:
        """
        Parse the source into markdown content.

        Args:
            source: File path or URL

        Returns:
            ParseResult with content and metadata

        Raises:
            ParsingError: If parsing fails
        """
        ...


# ============================================================================
# PIPELINE INTERFACES
# ============================================================================


class StageStatus(Enum):
    """Status of a pipeline stage execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineContext:
    """
    Immutable context passed through pipeline stages.

    Each stage creates a new context with updated fields using the
    immutable update pattern (via with_update method).

    Attributes:
        document_id: Database ID of the document being processed
        source: Original source path or URL
        parsed_content: Markdown content from parsing stage
        title: Document title
        chunks: List of chunked documents with metadata
        stage_results: Execution status of each stage
        error_messages: Error messages from failed stages
    """

    # Source information
    document_id: Optional[int] = None
    source: Optional[str] = None

    # Parsed content
    parsed_content: Optional[str] = None
    title: Optional[str] = None

    # Chunking results
    chunks: List[LangchainDocument] = field(default_factory=list)

    # Pipeline execution state
    stage_results: Dict[str, StageStatus] = field(default_factory=dict)
    error_messages: Dict[str, str] = field(default_factory=dict)

    def with_update(self, **kwargs) -> "PipelineContext":
        """
        Create new context with updated fields (immutable pattern).

        This ensures pipeline stages don't mutate the context, making
        the pipeline easier to reason about and test.

        Args:
            **kwargs: Fields to update

        Returns:
            New PipelineContext instance with updated fields

        Example:
            new_ctx = ctx.with_update(title="New Title", parsed_content="...")
        """
        from dataclasses import replace

        return replace(self, **kwargs)

    def mark_stage_completed(self, stage_name: str) -> "PipelineContext":
        """
        Mark a stage as successfully completed.

        Args:
            stage_name: Name of the completed stage

        Returns:
            New context with updated stage status
        """
        new_results = self.stage_results.copy()
        new_results[stage_name] = StageStatus.COMPLETED
        return self.with_update(stage_results=new_results)

    def mark_stage_failed(self, stage_name: str, error: str) -> "PipelineContext":
        """
        Mark a stage as failed with error message.

        Args:
            stage_name: Name of the failed stage
            error: Error message describing the failure

        Returns:
            New context with updated stage status and error message
        """
        new_results = self.stage_results.copy()
        new_results[stage_name] = StageStatus.FAILED

        new_errors = self.error_messages.copy()
        new_errors[stage_name] = error

        return self.with_update(stage_results=new_results, error_messages=new_errors)

    def mark_stage_running(self, stage_name: str) -> "PipelineContext":
        """
        Mark a stage as currently running.

        Args:
            stage_name: Name of the running stage

        Returns:
            New context with updated stage status
        """
        new_results = self.stage_results.copy()
        new_results[stage_name] = StageStatus.RUNNING
        return self.with_update(stage_results=new_results)


class PipelineStage(ABC):
    """
    Abstract base class for pipeline stages.

    Stages are idempotent and can declare dependencies on other stages.
    They receive a PipelineContext and return an updated context.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        Unique name for this stage.

        Returns:
            Stage identifier (e.g., "parsing", "chunking", "embedding")
        """
        pass

    @property
    def required_stages(self) -> List[str]:
        """
        List of stage names that must complete before this stage.

        Override this property if the stage has dependencies.

        Returns:
            List of required stage names (empty if no dependencies)

        Example:
            For a chunking stage that requires parsing:
            return ["parsing"]
        """
        return []

    @abstractmethod
    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Execute this stage and return updated context.

        Implementations should:
        1. Validate that required data is in the context
        2. Perform the stage's operation
        3. Return a new context with updated fields
        4. Raise appropriate exceptions on failure

        Args:
            context: Current pipeline context

        Returns:
            Updated context with stage results

        Raises:
            PipelineError: If stage execution fails
        """
        pass

    def can_run(self, context: PipelineContext) -> bool:
        """
        Check if this stage can run based on context state.

        Verifies that all required stages have completed successfully.

        Args:
            context: Current pipeline context

        Returns:
            True if all required stages are completed
        """
        for required in self.required_stages:
            status = context.stage_results.get(required)
            if status != StageStatus.COMPLETED:
                return False
        return True

    def should_skip(self, context: PipelineContext) -> bool:
        """
        Check if this stage should be skipped.

        Override for conditional execution logic (e.g., skip if already
        completed or if certain conditions are met).

        Args:
            context: Current pipeline context

        Returns:
            True if stage should be skipped
        """
        # Skip if already completed
        if context.stage_results.get(self.name) == StageStatus.COMPLETED:
            return True
        return False
