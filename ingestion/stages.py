"""
Pipeline stages for document ingestion.

Each stage is idempotent and declares its dependencies.
Stages receive a PipelineContext and return an updated context.
"""

import logging
import uuid as uuid_lib
from typing import List

from langchain.schema import Document as LangchainDocument

from core.exceptions import ChunkingError, DatabaseError, EmbeddingError, ParsingError
from core.interfaces import PipelineContext, PipelineStage
from ingestion.chunking import Config as ChunkingConfig
from ingestion.chunking import MarkdownChunker
from ingestion.embed import VectorStoreManager
from ingestion.parsing import ParserFactory

logger = logging.getLogger(__name__)


# ============================================================================
# STAGE 1: PARSING
# ============================================================================


class ParsingStage(PipelineStage):
    """
    Stage 1: Parse source document into markdown.

    Dependencies: None
    Input: context.source (file path or URL)
    Output: context.parsed_content, context.title
    """

    def __init__(self, parser_factory: ParserFactory):
        """
        Initialize parsing stage.

        Args:
            parser_factory: Factory for creating appropriate parsers
        """
        self.parser_factory = parser_factory

    @property
    def name(self) -> str:
        return "parsing"

    @property
    def required_stages(self) -> List[str]:
        return []  # No dependencies

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Parse source document and update context.

        Args:
            context: Pipeline context with source

        Returns:
            Context with parsed_content and title populated

        Raises:
            ParsingError: If parsing fails
        """
        from db.crud import DocumentCRUD
        from db.database import session_scope

        if not context.source:
            raise ParsingError("No source provided in context")

        logger.info(f"Parsing source: {context.source}")

        try:
            # Use ParserFactory to automatically select parser
            result = self.parser_factory.parse(context.source)

            logger.info(f"Successfully parsed: {context.source} (title: {result.title})")

            metadata = result.metadata or {}
            tags = metadata.get("tags")
            structured = {
                key: metadata[key]
                for key in (
                    "source",
                    "uid",
                    "author_uid",
                    "lang",
                    "nikaya",
                    "nikaya_name",
                    "nikaya_english",
                    "reading_url",
                )
                if key in metadata
            }

            # Persist markdown, the parsed title, and source tags/metadata
            if context.document_id:
                with session_scope() as session:
                    doc = DocumentCRUD(session).get_document_by_id(context.document_id)
                    if doc:
                        doc.markdown = result.content
                        if result.title:
                            doc.title = result.title
                        if tags:
                            existing = list(doc.tags or [])
                            doc.tags = existing + [t for t in tags if t not in existing]
                        if structured:
                            doc.doc_metadata = {**(doc.doc_metadata or {}), **structured}
                logger.info(
                    f"Saved markdown/title/tags to database for document {context.document_id}"
                )

            # Update context with parsed results (source_metadata tags the chunks later)
            return context.with_update(
                parsed_content=result.content,
                title=result.title or "Untitled",
                source_metadata=metadata,
            ).mark_stage_completed(self.name)

        except ParsingError as e:
            logger.error(f"Parsing failed: {e}")
            return context.mark_stage_failed(self.name, str(e))
        except Exception as e:
            logger.error(f"Unexpected error in parsing stage: {e}", exc_info=True)
            return context.mark_stage_failed(self.name, f"Unexpected error: {e}")


# ============================================================================
# STAGE 2: CHUNKING
# ============================================================================


class ChunkingStage(PipelineStage):
    """
    Stage 2: Chunk parsed markdown into semantic segments.

    Dependencies: parsing
    Input: context.parsed_content, context.title
    Output: context.chunks
    """

    def __init__(self, chunking_config: ChunkingConfig):
        """
        Initialize chunking stage.

        Args:
            chunking_config: Configuration for chunking behavior
        """
        self.chunking_config = chunking_config

    @property
    def name(self) -> str:
        return "chunking"

    @property
    def required_stages(self) -> List[str]:
        return ["parsing"]

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Chunk parsed content into semantic segments.

        Args:
            context: Pipeline context with parsed content

        Returns:
            Context with chunks populated

        Raises:
            ChunkingError: If chunking fails
        """
        if not context.parsed_content:
            raise ChunkingError("No parsed content available for chunking")

        logger.info(f"Chunking document: {context.title}")

        try:
            chunker = MarkdownChunker(
                text=context.parsed_content, config=self.chunking_config, title=context.title
            )

            chunks, stats = await chunker.chunk()

            logger.info(
                f"Chunking complete: {stats.total_chunks} chunks in "
                f"{stats.processing_time:.2f}s (avg {stats.avg_chunk_size:.0f} words)"
            )

            return context.with_update(chunks=chunks).mark_stage_completed(self.name)

        except ChunkingError as e:
            logger.error(f"Chunking failed: {e}")
            return context.mark_stage_failed(self.name, str(e))
        except Exception as e:
            logger.error(f"Unexpected error in chunking stage: {e}", exc_info=True)
            return context.mark_stage_failed(self.name, f"Unexpected error: {e}")


# ============================================================================
# STAGE 3: EMBEDDING
# ============================================================================


class EmbeddingStage(PipelineStage):
    """
    Stage 3: Embed chunks and store in vector database.

    Dependencies: chunking
    Input: context.chunks, context.document_id, context.title
    Output: Chunks stored in vector database
    """

    def __init__(self, vector_store_manager: VectorStoreManager):
        """
        Initialize embedding stage.

        Args:
            vector_store_manager: Manager for vector store operations
        """
        self.vector_store_manager = vector_store_manager

    @property
    def name(self) -> str:
        return "embedding"

    @property
    def required_stages(self) -> List[str]:
        return ["chunking"]

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Embed chunks and store in vector database.

        Args:
            context: Pipeline context with chunks

        Returns:
            Context marked as embedding completed

        Raises:
            EmbeddingError: If embedding fails
        """
        if not context.chunks:
            raise EmbeddingError("No chunks available for embedding")

        logger.info(f"Embedding {len(context.chunks)} chunks")

        try:
            # Enrich copies, not the shared chunk objects — the input context
            # must stay unchanged (PipelineContext immutability is shallow).
            enriched_chunks: List[LangchainDocument] = []
            expected_ids = []
            for chunk in context.chunks:
                metadata = dict(chunk.metadata)
                if context.document_id is not None:
                    metadata.setdefault("document_id", context.document_id)
                    metadata.setdefault("original_doc_id", context.document_id)
                if context.title:
                    metadata.setdefault("source_title", context.title)
                # Tag each chunk with source/nikaya metadata for retrieval filtering
                for key in ("source", "uid", "author_uid", "lang", "nikaya", "nikaya_name"):
                    if key in context.source_metadata:
                        metadata.setdefault(key, context.source_metadata[key])
                chunk_uuid = str(uuid_lib.uuid4())
                metadata["uuid"] = chunk_uuid
                enriched_chunks.append(
                    LangchainDocument(
                        # PGVector uses Document.id as the persisted vector ID.
                        id=chunk_uuid,
                        page_content=chunk.page_content,
                        metadata=metadata,
                    )
                )
                expected_ids.append(chunk_uuid)

            # Embed and store in vector database
            vector_ids = self.vector_store_manager.embed_documents(enriched_chunks)

            if len(vector_ids) != len(enriched_chunks):
                raise EmbeddingError(
                    f"Embedding mismatch: {len(enriched_chunks)} chunks, "
                    f"{len(vector_ids)} embeddings stored"
                )

            if set(vector_ids) != set(expected_ids):
                missing_ids = sorted(set(expected_ids) - set(vector_ids))
                extra_ids = sorted(set(vector_ids) - set(expected_ids))
                raise EmbeddingError(
                    "Embedding ID mismatch. "
                    f"Missing IDs: {missing_ids[:3]} "
                    f"Extra IDs: {extra_ids[:3]}"
                )

            logger.info(f"Successfully embedded {len(vector_ids)} chunks")

            return context.with_update(chunks=enriched_chunks).mark_stage_completed(self.name)

        except EmbeddingError as e:
            logger.error(f"Embedding failed: {e}")
            return context.mark_stage_failed(self.name, str(e))
        except Exception as e:
            logger.error(f"Unexpected error in embedding stage: {e}", exc_info=True)
            return context.mark_stage_failed(self.name, f"Unexpected error: {e}")


# ============================================================================
# STAGE 4: DATABASE PERSISTENCE
# ============================================================================


class DatabasePersistenceStage(PipelineStage):
    """
    Stage 4: Save document and chunk metadata to database.

    Dependencies: embedding
    Input: context.document_id, context.chunks (with UUIDs from vector store)
    Output: Chunks saved to database, document status updated to COMPLETED
    """

    @property
    def name(self) -> str:
        return "database_persistence"

    @property
    def required_stages(self) -> List[str]:
        return ["embedding"]

    def _build_table_of_contents(self, chunks: List) -> dict:
        """
        Build table of contents from chunk header paths.

        Reads all_header_paths and header_level_map from chunk metadata
        to construct a hierarchical TOC.

        Args:
            chunks: List of LangChain Documents with header path metadata

        Returns:
            Dict with 'entries' (structured list) and 'text' (indented string)
        """
        entries = []
        seen_paths = {}  # path_from_root -> entry_id
        entry_count = 0

        for idx, chunk in enumerate(chunks):
            metadata = chunk.metadata or {}
            paths = metadata.get("all_header_paths", [])
            level_map = metadata.get("header_level_map", {})

            for path in paths:
                segments = [s.strip() for s in path.split(" > ") if s.strip()]
                if not segments:
                    continue

                parent_path = ""
                for depth, segment in enumerate(segments, start=1):
                    current_path = f"{parent_path} > {segment}" if parent_path else segment

                    if current_path in seen_paths:
                        parent_path = current_path
                        continue

                    level = level_map.get(segment, depth)
                    entry_id = f"h{level}_{entry_count}"
                    parent_id = seen_paths.get(parent_path)

                    entries.append(
                        {
                            "id": entry_id,
                            "level": level,
                            "text": segment,
                            "parent_id": parent_id,
                            "chunk_index": idx,
                            "path_from_root": current_path,
                        }
                    )

                    seen_paths[current_path] = entry_id
                    parent_path = current_path
                    entry_count += 1

        text_lines = []
        for entry in entries:
            indent = "  " * (entry["level"] - 1)
            text_lines.append(f"{indent}{entry['text']}")

        logger.debug(f"Built TOC with {len(entries)} entries")
        return {
            "entries": entries,
            "text": "\n".join(text_lines),
        }

    async def execute(self, context: PipelineContext) -> PipelineContext:
        """
        Save document and chunk metadata to database.

        Args:
            context: Pipeline context with embedded chunks

        Returns:
            Context marked as persistence completed

        Raises:
            DatabaseError: If database operations fail
        """
        from db.crud import ChunkCRUD, DocumentCRUD
        from db.database import session_scope
        from db.schema import DocumentStatus

        if not context.document_id:
            raise DatabaseError("No document_id in context")

        if not context.chunks:
            logger.warning("No chunks to persist")
            return context.mark_stage_completed(self.name)

        logger.info(f"Persisting {len(context.chunks)} chunks to database")

        try:
            with session_scope() as session:
                doc_crud = DocumentCRUD(session)
                chunk_crud = ChunkCRUD(session)

                # Prepare chunk data for database
                chunks_data = []
                for idx, chunk in enumerate(context.chunks):
                    # Extract UUID from metadata (added by EmbeddingStage)
                    chunk_uuid = chunk.metadata.get("uuid")
                    if not chunk_uuid:
                        # Generate UUID if not present (shouldn't happen)
                        chunk_uuid = str(uuid_lib.uuid4())
                        logger.warning(f"Chunk {idx} missing UUID, generated: {chunk_uuid}")

                    chunks_data.append(
                        {
                            "uuid": chunk_uuid,
                            "chunk_text": chunk.page_content,
                            "chunk_index": idx,
                            "chunk_metadata": {
                                k: v for k, v in chunk.metadata.items() if k != "uuid"
                            },
                        }
                    )

                # Save chunks to database
                created_chunks = chunk_crud.create_chunks_batch(
                    document_id=context.document_id,
                    chunks_data=chunks_data,
                )

                logger.info(f"✓ Saved {len(created_chunks)} chunks to database")

                # Build and save table of contents from chunk headers
                toc = self._build_table_of_contents(context.chunks)
                if toc["entries"]:
                    doc_crud.update_doc_metadata(
                        document_id=context.document_id,
                        metadata_updates={"table_of_contents": toc},
                        merge=True,
                    )
                    logger.info(f"✓ Saved table of contents with {len(toc['entries'])} entries")

                # Update document status to COMPLETED
                doc_crud.update_status(
                    document_id=context.document_id,
                    status=DocumentStatus.COMPLETED,
                    status_details=f"Successfully processed {len(created_chunks)} chunks",
                )

                # Clear temporary chunk storage
                doc_crud.clear_chunks(context.document_id)

                logger.info(f"✓ Document {context.document_id} marked as COMPLETED")

            return context.mark_stage_completed(self.name)

        except DatabaseError as e:
            logger.error(f"Database persistence failed: {e}")
            return context.mark_stage_failed(self.name, str(e))
        except Exception as e:
            logger.error(f"Unexpected error in persistence stage: {e}", exc_info=True)
            return context.mark_stage_failed(self.name, f"Unexpected error: {e}")
