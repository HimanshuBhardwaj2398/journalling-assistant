"""
DAG-based pipeline orchestrator for document ingestion.

Replaces linear state machine with dependency-aware stage execution.
"""

import logging
import os
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

# LangChain Document for type hints
from langchain.schema import Document as LangchainDocument

from core.exceptions import DocumentNotFoundError, PipelineError
from core.interfaces import PipelineContext, PipelineStage, StageStatus
from ingestion.chunking import Config as ChunkingConfig
from ingestion.embed import VectorStoreConfig, VectorStoreManager
from ingestion.parsing import ParserFactory
from ingestion.stages import ChunkingStage, DatabasePersistenceStage, EmbeddingStage, ParsingStage

logger = logging.getLogger(__name__)


# ============================================================================
# SERIALIZATION HELPERS (kept for backward compatibility)
# ============================================================================


def serialize_docs(docs: List[LangchainDocument]) -> List[Dict[str, Any]]:
    """Converts Langchain Documents to JSON-serializable format."""
    return [{"page_content": doc.page_content, "metadata": doc.metadata} for doc in docs]


def deserialize_docs(serialized_docs: List[Dict[str, Any]]) -> List[LangchainDocument]:
    """Converts serialized documents back to Langchain Documents."""
    return [
        LangchainDocument(page_content=doc["page_content"], metadata=doc["metadata"])
        for doc in serialized_docs
    ]


# ============================================================================
# REPROCESS MODES
# ============================================================================


class ReprocessMode(str, Enum):
    """Supported reprocessing entry points for existing documents."""

    FULL = "full"
    FROM_CHUNKING = "from_chunking"
    FROM_EMBEDDING = "from_embedding"


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
                    raise PipelineError("Circular dependency detected in pipeline stages")

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

    async def execute(
        self,
        context: PipelineContext,
        on_stage_update: Optional[callable] = None,
    ) -> PipelineContext:
        """
        Execute pipeline stages in dependency order.

        Args:
            context: Initial pipeline context
            on_stage_update: Optional callback invoked with (stage_name, StageStatus)
                for each stage transition (RUNNING, COMPLETED, FAILED).

        Returns:
            Final context after all stages
        """
        current_context = context

        def _notify(stage_name: str, status: StageStatus):
            if on_stage_update is not None:
                on_stage_update(stage_name, status)

        for stage in self._execution_order:
            # Skip if already completed
            if stage.should_skip(current_context):
                logger.info(f"Skipping stage '{stage.name}' (already completed)")
                continue

            # Check if dependencies are met
            if not stage.can_run(current_context):
                missing = [
                    dep
                    for dep in stage.required_stages
                    if current_context.stage_results.get(dep) != StageStatus.COMPLETED
                ]
                logger.warning(f"Stage '{stage.name}' cannot run. Missing dependencies: {missing}")
                continue

            # Execute stage
            logger.info(f"Executing stage: {stage.name}")
            _notify(stage.name, StageStatus.RUNNING)
            try:
                current_context = await stage.execute(current_context)

                # Check if stage failed
                if current_context.stage_results.get(stage.name) == StageStatus.FAILED:
                    error = current_context.error_messages.get(stage.name, "Unknown error")
                    logger.error(f"Stage '{stage.name}' failed: {error}")
                    _notify(stage.name, StageStatus.FAILED)
                    # Continue to next stage (allows partial processing)
                else:
                    _notify(stage.name, StageStatus.COMPLETED)

            except Exception as e:
                logger.error(f"Unexpected error in stage '{stage.name}': {e}", exc_info=True)
                current_context = current_context.mark_stage_failed(stage.name, str(e))
                _notify(stage.name, StageStatus.FAILED)

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

    @staticmethod
    def _parse_reprocess_mode(
        reprocess_mode: Optional[Union[ReprocessMode, str]],
    ) -> Optional[ReprocessMode]:
        """Normalize and validate optional reprocess mode."""
        if reprocess_mode is None:
            return None
        if isinstance(reprocess_mode, ReprocessMode):
            return reprocess_mode
        try:
            return ReprocessMode(reprocess_mode)
        except ValueError as e:
            allowed = ", ".join(mode.value for mode in ReprocessMode)
            raise PipelineError(
                f"Invalid reprocess_mode '{reprocess_mode}'. Allowed values: {allowed}"
            ) from e

    async def process(
        self,
        source: Union[str, int],
        title: Optional[str] = None,
        on_stage_update: Optional[Callable[[str, StageStatus], None]] = None,
        reprocess_mode: Optional[Union[ReprocessMode, str]] = None,
        clear_markdown: bool = False,
    ) -> Dict[str, Any]:
        """
        Process a document through the ingestion pipeline.

        Args:
            source: File path, URL, or document ID to resume
            title: Optional title (will be extracted if not provided)
            on_stage_update: Optional callback(stage_name, status) for UI updates
            reprocess_mode: Optional mode for existing documents:
                - "full": re-parse + chunk + embed + persist
                - "from_chunking": reuse stored markdown, rerun chunking+
                  embedding+persistence
                - "from_embedding": reuse stored chunks, rerun embedding+
                  persistence
            clear_markdown: When reprocessing existing docs, clear
                documents.markdown before pipeline execution.

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
        from db.crud import ChunkCRUD, DocumentCRUD
        from db.database import session_scope
        from db.schema import DocumentStatus

        mode = self._parse_reprocess_mode(reprocess_mode)
        if clear_markdown and mode != ReprocessMode.FULL:
            raise PipelineError("clear_markdown is only supported with reprocess_mode='full'")

        # Create or load document
        document_id = None
        seeded_parsed_content: Optional[str] = None
        seeded_chunks: List[LangchainDocument] = []
        seeded_stage_results: Dict[str, StageStatus] = {}

        if isinstance(source, int):
            # Resume existing document
            chunk_uuids: List[str] = []
            with session_scope() as session:
                doc_crud = DocumentCRUD(session)
                chunk_crud = ChunkCRUD(session)

                doc = doc_crud.get_document_by_id(source)
                if not doc:
                    raise DocumentNotFoundError(f"Document {source} not found")

                source = doc.file_path
                title = title or doc.title
                document_id = doc.id
                existing_markdown = doc.markdown
                existing_doc_metadata = dict(doc.doc_metadata or {})

                existing_chunks = chunk_crud.get_chunks_by_document(document_id)
                chunk_uuids = [chunk.uuid for chunk in existing_chunks]

                if mode == ReprocessMode.FROM_CHUNKING:
                    if not existing_markdown:
                        raise PipelineError(
                            f"Document {document_id} has no stored markdown; "
                            "cannot start from chunking"
                        )
                    seeded_parsed_content = existing_markdown
                    seeded_stage_results = {"parsing": StageStatus.COMPLETED}
                elif mode == ReprocessMode.FROM_EMBEDDING:
                    if not existing_chunks:
                        raise PipelineError(
                            f"Document {document_id} has no stored chunks; "
                            "cannot start from embedding"
                        )
                    seeded_stage_results = {
                        "parsing": StageStatus.COMPLETED,
                        "chunking": StageStatus.COMPLETED,
                    }
                    for chunk_row in existing_chunks:
                        metadata = dict(chunk_row.chunk_metadata or {})
                        metadata["uuid"] = chunk_row.uuid
                        seeded_chunks.append(
                            LangchainDocument(
                                page_content=chunk_row.chunk_text,
                                metadata=metadata,
                            )
                        )

                if mode == ReprocessMode.FULL and not source:
                    raise PipelineError(
                        f"Document {document_id} is missing file_path; "
                        "cannot reprocess from parsing"
                    )

            if mode is not None:
                if chunk_uuids:
                    try:
                        deleted_embeddings = self.vector_store_manager.delete_by_ids(chunk_uuids)
                        logger.info(
                            "Deleted %s existing embeddings for document %s",
                            deleted_embeddings,
                            document_id,
                        )
                    except Exception as e:
                        raise PipelineError(
                            f"Failed to clear existing embeddings for document {document_id}: {e}"
                        ) from e

                with session_scope() as session:
                    doc_crud = DocumentCRUD(session)
                    chunk_crud = ChunkCRUD(session)
                    doc = doc_crud.get_document_by_id(document_id)
                    if not doc:
                        raise DocumentNotFoundError(f"Document {document_id} not found")

                    deleted_chunks = chunk_crud.delete_chunks_by_document(document_id)
                    logger.info(
                        "Deleted %s existing chunk rows for document %s",
                        deleted_chunks,
                        document_id,
                    )

                    doc.chunks = None
                    if clear_markdown:
                        doc.markdown = None

                    # Remove stale derived metadata before rerun.
                    if existing_doc_metadata.pop("table_of_contents", None) is not None:
                        doc.doc_metadata = existing_doc_metadata

                    doc.status = DocumentStatus.PENDING
                    doc.status_details = f"Reprocessing ({mode.value}) - pipeline rerun requested"

                logger.info(
                    "Reprocessing document %s (%s, clear_markdown=%s)",
                    document_id,
                    mode.value,
                    clear_markdown,
                )
            else:
                logger.info(f"Resuming document {document_id}: {title}")
        else:
            if mode is not None:
                raise PipelineError(
                    "reprocess_mode can only be used when source is an existing document ID"
                )
            # Create new document
            with session_scope() as session:
                doc = DocumentCRUD(session).create_document(
                    title=title or "Untitled",
                    file_path=source,
                    status=DocumentStatus.PENDING,
                )
                document_id = doc.id
                logger.info(f"Created document {document_id} for source: {source}")

        stage_running_status = {
            "parsing": DocumentStatus.PARSING,
            "chunking": DocumentStatus.CHUNKING,
            "embedding": DocumentStatus.EMBEDDING,
            # No dedicated persistence enum; keep this under embedding phase.
            "database_persistence": DocumentStatus.EMBEDDING,
        }
        stage_completed_status = {
            "parsing": DocumentStatus.PARSED,
            "chunking": DocumentStatus.CHUNKED,
            # Keep EMBEDDING until database persistence marks COMPLETED.
            "embedding": DocumentStatus.EMBEDDING,
        }

        def _persist_stage_status(stage_name: str, stage_status: StageStatus) -> None:
            """Mirror pipeline stage transitions into document.status for visibility."""
            if not document_id:
                return

            mapped_status: Optional[DocumentStatus] = None
            if stage_status == StageStatus.RUNNING:
                mapped_status = stage_running_status.get(stage_name)
            elif stage_status == StageStatus.COMPLETED:
                mapped_status = stage_completed_status.get(stage_name)
            elif stage_status == StageStatus.FAILED:
                mapped_status = DocumentStatus.FAILED

            if mapped_status is None:
                return

            try:
                with session_scope() as session:
                    DocumentCRUD(session).update_status(
                        document_id=document_id,
                        status=mapped_status,
                        status_details=f"Stage '{stage_name}' {stage_status.value}",
                    )
                logger.info(
                    "Document %s status -> %s (%s: %s)",
                    document_id,
                    mapped_status.value,
                    stage_name,
                    stage_status.value,
                )
            except Exception as e:
                logger.warning(
                    "Failed to persist stage status for document %s (%s=%s): %s",
                    document_id,
                    stage_name,
                    stage_status.value,
                    e,
                )

        def _on_stage_update(stage_name: str, stage_status: StageStatus) -> None:
            _persist_stage_status(stage_name, stage_status)
            if on_stage_update is not None:
                on_stage_update(stage_name, stage_status)

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
            parsed_content=seeded_parsed_content,
            chunks=seeded_chunks,
            stage_results=seeded_stage_results,
        )

        try:
            # Execute pipeline
            logger.info(f"Starting pipeline for document {document_id}")
            final_context = await pipeline.execute(
                context,
                on_stage_update=_on_stage_update,
            )

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
                "reprocess_mode": mode.value if mode else None,
                "stage_results": {
                    name: status.value for name, status in final_context.stage_results.items()
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

    from config.logging_config import setup_logging

    setup_logging()

    # Create orchestrator
    orchestrator = IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(
            collection_name="buddhist_texts",
            db_url=os.getenv("DATABASE_URL"),
        )
    )

    # Test with a source (update this to a real file path or URL)
    source = "https://example.com"  # or "path/to/file.pdf"

    try:
        result = asyncio.run(orchestrator.process(source))
        logger.info("=== Pipeline Result ===")
        logger.info("Source: %s", result["source"])
        logger.info("Title: %s", result["title"])
        logger.info("Chunks: %s", result["chunk_count"])
        logger.info("Success: %s", result["success"])
        logger.info("Stage Results: %s", result["stage_results"])
        if result["errors"]:
            logger.error("Errors: %s", result["errors"])
    except Exception:
        logger.exception("Pipeline failed")
