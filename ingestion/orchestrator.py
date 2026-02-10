"""
DAG-based pipeline orchestrator for document ingestion.

Replaces linear state machine with dependency-aware stage execution.
"""

import logging
import os
from typing import Union, List, Dict, Any, Optional

from core.interfaces import PipelineStage, PipelineContext, StageStatus
from core.exceptions import PipelineError, DatabaseError, DocumentNotFoundError
from ingestion.parsing import ParserFactory
from ingestion.chunking import Config as ChunkingConfig
from ingestion.embed import VectorStoreManager, VectorStoreConfig
from ingestion.stages import ParsingStage, ChunkingStage, EmbeddingStage, DatabasePersistenceStage

# LangChain Document for type hints
from langchain.schema import Document as LangchainDocument

logger = logging.getLogger(__name__)


# ============================================================================
# SERIALIZATION HELPERS (kept for backward compatibility)
# ============================================================================

def serialize_docs(docs: List[LangchainDocument]) -> List[Dict[str, Any]]:
    """Converts Langchain Documents to JSON-serializable format."""
    return [
        {"page_content": doc.page_content, "metadata": doc.metadata}
        for doc in docs
    ]


def deserialize_docs(serialized_docs: List[Dict[str, Any]]) -> List[LangchainDocument]:
    """Converts serialized documents back to Langchain Documents."""
    return [
        LangchainDocument(page_content=doc["page_content"], metadata=doc["metadata"])
        for doc in serialized_docs
    ]


# ============================================================================
# DAG PIPELINE ORCHESTRATOR
# ============================================================================

class PipelineOrchestrator:
    """
    DAG-based pipeline orchestrator with automatic dependency resolution.

    Stages are executed in topological order based on their dependencies.
    Each stage is idempotent and can be resumed from any point.
    """

    def __init__(self, stages: List[PipelineStage]):
        """
        Initialize orchestrator with pipeline stages.

        Args:
            stages: List of pipeline stages to execute

        Raises:
            PipelineError: If stage dependencies form a cycle
        """
        self._stages = stages
        self._stage_map = {stage.name: stage for stage in stages}
        self._validate_dag()
        self._execution_order = self._topological_sort()

        logger.debug(f"Pipeline execution order: {[s.name for s in self._execution_order]}")

    def _validate_dag(self):
        """
        Validate that stage dependencies form a valid DAG (no cycles).

        Raises:
            PipelineError: If circular dependency detected
        """
        visited = set()
        rec_stack = set()

        def has_cycle(stage_name: str) -> bool:
            visited.add(stage_name)
            rec_stack.add(stage_name)

            stage = self._stage_map.get(stage_name)
            if stage:
                for dependency in stage.required_stages:
                    if dependency not in visited:
                        if has_cycle(dependency):
                            return True
                    elif dependency in rec_stack:
                        return True

            rec_stack.remove(stage_name)
            return False

        for stage_name in self._stage_map.keys():
            if stage_name not in visited:
                if has_cycle(stage_name):
                    raise PipelineError(f"Circular dependency detected in pipeline stages")

        logger.debug("DAG validation passed - no cycles detected")

    def _topological_sort(self) -> List[PipelineStage]:
        """
        Sort stages in execution order using topological sort.

        Returns:
            List of stages in dependency order
        """
        # Calculate in-degrees: count how many dependencies each stage has
        in_degree = {stage.name: len(stage.required_stages) for stage in self._stages}

        # Find stages with no dependencies (in_degree = 0)
        queue = [stage for stage in self._stages if in_degree[stage.name] == 0]
        result = []

        while queue:
            # Take stage with no remaining dependencies
            stage = queue.pop(0)
            result.append(stage)

            # Reduce in-degree for stages that depend on this one
            for other_stage in self._stages:
                if stage.name in other_stage.required_stages:
                    in_degree[other_stage.name] -= 1
                    if in_degree[other_stage.name] == 0:
                        queue.append(other_stage)

        if len(result) != len(self._stages):
            raise PipelineError("Unable to determine stage execution order")

        return result

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Execute pipeline stages in dependency order.

        Args:
            context: Initial pipeline context

        Returns:
            Final context after all stages
        """
        current_context = context

        for stage in self._execution_order:
            # Skip if already completed
            if stage.should_skip(current_context):
                logger.info(f"Skipping stage '{stage.name}' (already completed)")
                continue

            # Check if dependencies are met
            if not stage.can_run(current_context):
                missing = [
                    dep for dep in stage.required_stages
                    if current_context.stage_results.get(dep) != StageStatus.COMPLETED
                ]
                logger.warning(
                    f"Stage '{stage.name}' cannot run. Missing dependencies: {missing}"
                )
                continue

            # Execute stage
            logger.info(f"Executing stage: {stage.name}")
            try:
                current_context = await stage.execute(current_context)

                # Check if stage failed
                if current_context.stage_results.get(stage.name) == StageStatus.FAILED:
                    error = current_context.error_messages.get(stage.name, "Unknown error")
                    logger.error(f"Stage '{stage.name}' failed: {error}")
                    # Continue to next stage (allows partial processing)

            except Exception as e:
                logger.error(f"Unexpected error in stage '{stage.name}': {e}", exc_info=True)
                current_context = current_context.mark_stage_failed(stage.name, str(e))

        return current_context


# ============================================================================
# HIGH-LEVEL INGESTION ORCHESTRATOR (backward compatible API)
# ============================================================================

class IngestionOrchestrator:
    """
    High-level orchestrator for document ingestion.

    Provides backward-compatible API while using DAG pipeline internally.
    Includes database persistence for tracking document and chunk metadata.
    """

    def __init__(
        self,
        vector_store_config: VectorStoreConfig,
        chunking_config: Optional[ChunkingConfig] = None,
        enable_database_persistence: bool = True,
    ):
        """
        Initialize ingestion orchestrator.

        Args:
            vector_store_config: Configuration for vector store
            chunking_config: Configuration for chunking (optional)
            enable_database_persistence: Enable database stage (default True)
        """
        self.vector_store_config = vector_store_config
        self.chunking_config = chunking_config or ChunkingConfig()
        self.enable_database_persistence = enable_database_persistence

        # Initialize components
        self.parser_factory = ParserFactory()
        self.vector_store_manager = VectorStoreManager(config=vector_store_config)

        logger.info("IngestionOrchestrator initialized with DAG pipeline")

    async def process(
        self,
        source: Union[str, int],
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Process a document through the ingestion pipeline.

        Args:
            source: File path, URL, or document ID to resume
            title: Optional title (will be extracted if not provided)

        Returns:
            Dictionary with processing results:
                - document_id: Database ID of the document
                - source: Original source
                - title: Extracted title
                - chunk_count: Number of chunks created
                - stage_results: Status of each stage
                - errors: Any error messages
                - success: Whether pipeline completed successfully
        """
        from db.database import session_scope
        from db.crud import DocumentCRUD
        from db.schema import DocumentStatus

        # Create or load document
        document_id = None
        if isinstance(source, int):
            # Resume existing document
            with session_scope() as session:
                doc = DocumentCRUD(session).get_document_by_id(source)
                if not doc:
                    raise DocumentNotFoundError(f"Document {source} not found")
                source = doc.file_path
                title = doc.title
                document_id = doc.id
                logger.info(f"Resuming document {document_id}: {title}")
        else:
            # Create new document
            with session_scope() as session:
                doc = DocumentCRUD(session).create_document(
                    title=title or "Untitled",
                    file_path=source,
                    status=DocumentStatus.PENDING,
                )
                document_id = doc.id
                logger.info(f"Created document {document_id} for source: {source}")

        # Build pipeline stages
        stages = [
            ParsingStage(self.parser_factory),
            ChunkingStage(self.chunking_config),
            EmbeddingStage(self.vector_store_manager),
        ]

        # Add database persistence stage if enabled
        if self.enable_database_persistence:
            stages.append(DatabasePersistenceStage())

        # Create orchestrator
        pipeline = PipelineOrchestrator(stages)

        # Build initial context
        context = PipelineContext(
            document_id=document_id,
            source=source,
            title=title,
        )

        try:
            # Execute pipeline
            logger.info(f"Starting pipeline for document {document_id}")
            final_context = await pipeline.execute(context)

            # Check completion status
            if self.enable_database_persistence:
                success_stage = "database_persistence"
            else:
                success_stage = "embedding"

            status = final_context.stage_results.get(success_stage)
            success = status == StageStatus.COMPLETED

            # Build result
            result = {
                "document_id": document_id,
                "source": source,
                "title": final_context.title,
                "chunk_count": len(final_context.chunks) if final_context.chunks else 0,
                "stage_results": {
                    name: status.value
                    for name, status in final_context.stage_results.items()
                },
                "errors": final_context.error_messages,
                "success": success,
            }

            if success:
                logger.info(f"Pipeline completed successfully for document {document_id}")
            else:
                logger.warning(f"Pipeline partially completed for document {document_id}")
                # Update document status to FAILED
                with session_scope() as session:
                    DocumentCRUD(session).update_status(
                        document_id=document_id,
                        status=DocumentStatus.FAILED,
                        status_details=str(final_context.error_messages),
                    )

            return result

        except Exception as e:
            logger.error(f"Pipeline failed for document {document_id}: {e}", exc_info=True)
            # Update document status to FAILED
            with session_scope() as session:
                DocumentCRUD(session).update_status(
                    document_id=document_id,
                    status=DocumentStatus.FAILED,
                    status_details=str(e),
                )
            raise PipelineError(f"Pipeline execution failed: {e}") from e


# ============================================================================
# MAIN (for testing)
# ============================================================================

if __name__ == "__main__":
    """
    Test orchestrator with sample document.

    To run: python -m ingestion.orchestrator
    """
    import asyncio

    # Create orchestrator
    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(
            collection_name="documents",
            db_url=os.getenv("DATABASE_URL"),
        )
    )

    # Test with a source (update this to a real file path or URL)
    source = "https://example.com"  # or "path/to/file.pdf"

    try:
        result = asyncio.run(orchestrator.process(source))
        print(f"\n=== Pipeline Result ===")
        print(f"Source: {result['source']}")
        print(f"Title: {result['title']}")
        print(f"Chunks: {result['chunk_count']}")
        print(f"Success: {result['success']}")
        print(f"Stage Results: {result['stage_results']}")
        if result['errors']:
            print(f"Errors: {result['errors']}")
    except Exception as e:
        print(f"Pipeline failed: {e}")
