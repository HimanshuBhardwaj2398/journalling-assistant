"""Tests for ingestion reprocess mode validation."""

import pytest

from core.exceptions import PipelineError
from ingestion.embed import VectorStoreConfig
from ingestion.orchestrator import IngestionOrchestrator, ReprocessMode


def _build_orchestrator() -> IngestionOrchestrator:
    """Create orchestrator without touching live DB/vector connections."""
    return IngestionOrchestrator(
        vector_store_config=VectorStoreConfig(
            collection_name="test_collection",
            db_url="postgresql://user:pass@localhost:5432/test_db",
        )
    )


def test_parse_reprocess_mode_accepts_strings_and_enum():
    assert (
        IngestionOrchestrator._parse_reprocess_mode("full")
        == ReprocessMode.FULL
    )
    assert (
        IngestionOrchestrator._parse_reprocess_mode("from_chunking")
        == ReprocessMode.FROM_CHUNKING
    )
    assert (
        IngestionOrchestrator._parse_reprocess_mode(ReprocessMode.FROM_EMBEDDING)
        == ReprocessMode.FROM_EMBEDDING
    )


def test_parse_reprocess_mode_rejects_invalid_value():
    with pytest.raises(PipelineError, match="Invalid reprocess_mode"):
        IngestionOrchestrator._parse_reprocess_mode("not_a_mode")


@pytest.mark.asyncio
async def test_clear_markdown_requires_full_mode():
    orchestrator = _build_orchestrator()

    with pytest.raises(
        PipelineError,
        match="clear_markdown is only supported with reprocess_mode='full'",
    ):
        await orchestrator.process(source="dummy-source", clear_markdown=True)
