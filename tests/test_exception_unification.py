"""One exception hierarchy, rooted in core.exceptions.

ingestion/embed.py historically defined its own VectorStoreError /
EmbeddingError / DatabaseConnectionError. The local EmbeddingError
shadowed core's: EmbeddingStage caught the core class while the vector
store manager raised the embed one, so the specific handler never fired.
These tests pin the unification.
"""

from langchain.schema import Document

from core.interfaces import PipelineContext, StageStatus
from ingestion.stages import EmbeddingStage


def test_embed_embedding_error_is_core_embedding_error():
    from core.exceptions import EmbeddingError as CoreEmbeddingError
    from ingestion.embed import EmbeddingError as EmbedEmbeddingError

    assert EmbedEmbeddingError is CoreEmbeddingError


def test_vector_store_errors_are_rooted_in_core():
    from core.exceptions import MeditationDBError, VectorStoreError
    from ingestion.embed import VectorStoreError as EmbedVectorStoreError

    assert EmbedVectorStoreError is VectorStoreError
    assert issubclass(VectorStoreError, MeditationDBError)


def test_database_connection_error_is_a_vector_store_error():
    from core.exceptions import DatabaseConnectionError, VectorStoreError

    assert issubclass(DatabaseConnectionError, VectorStoreError)


async def test_embedding_stage_specific_handler_catches_manager_errors():
    """Manager failures must hit the specific except branch, not the generic one.

    The generic branch prefixes messages with 'Unexpected error:'; the
    specific branch records the message verbatim.
    """

    class ExplodingManager:
        def embed_documents(self, documents):
            from ingestion.embed import EmbeddingError

            raise EmbeddingError("vector store down")

    stage = EmbeddingStage(ExplodingManager())
    context = PipelineContext(chunks=[Document(page_content="x", metadata={})])

    result = await stage.execute(context)

    assert result.stage_results["embedding"] == StageStatus.FAILED
    assert result.error_messages["embedding"] == "vector store down"
