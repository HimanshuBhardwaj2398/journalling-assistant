"""Tests enforcing PipelineContext immutability.

The pipeline's contract is that stages return new contexts instead of
editing the one they received. Two things must hold for that to be true:
the dataclass rejects attribute assignment (frozen), and stages that
enrich chunks copy them instead of mutating the shared objects in place
(``dataclasses.replace`` is shallow — old and new contexts share field
contents unless a stage copies what it changes).
"""

import dataclasses

import pytest
from langchain.schema import Document

from core.interfaces import PipelineContext, StageStatus
from ingestion.stages import EmbeddingStage


class EchoIdsManager:
    """Fake vector store that echoes Document.id values."""

    def __init__(self):
        self.last_documents = []

    def embed_documents(self, documents):
        self.last_documents = documents
        return [doc.id for doc in documents]


def test_pipeline_context_rejects_attribute_assignment():
    context = PipelineContext(title="original")

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.title = "mutated"


def test_with_update_still_produces_new_contexts():
    context = PipelineContext(title="original")

    updated = context.with_update(title="new")

    assert updated.title == "new"
    assert context.title == "original"


async def test_embedding_stage_does_not_mutate_input_chunks():
    input_chunks = [
        Document(page_content="chunk one", metadata={}),
        Document(page_content="chunk two", metadata={}),
    ]
    context = PipelineContext(document_id=42, title="Meditation Manual", chunks=input_chunks)
    stage = EmbeddingStage(EchoIdsManager())

    result = await stage.execute(context)

    assert result.stage_results["embedding"] == StageStatus.COMPLETED
    # The originals must be untouched — no uuid, no id, no injected metadata.
    for chunk in input_chunks:
        assert chunk.metadata == {}
        assert chunk.id is None


async def test_embedding_stage_returns_enriched_copies():
    input_chunks = [Document(page_content="chunk one", metadata={"header": "Intro"})]
    context = PipelineContext(document_id=42, title="Meditation Manual", chunks=input_chunks)
    stage = EmbeddingStage(EchoIdsManager())

    result = await stage.execute(context)

    assert result.chunks is not context.chunks
    enriched = result.chunks[0]
    assert enriched.metadata["uuid"] == enriched.id
    assert enriched.metadata["document_id"] == 42
    assert enriched.metadata["source_title"] == "Meditation Manual"
    # Pre-existing metadata is preserved on the copy.
    assert enriched.metadata["header"] == "Intro"
